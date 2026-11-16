"""Evidence checking and a small durable LangGraph screening workflow."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import TypedDict

from . import ai
from .errors import ServiceError


def validate_matches(segments: list[dict], criteria: list[dict], matches: list[dict]) -> list[dict]:
    sources = {segment["id"]: segment["text"] for segment in segments}
    by_criterion = {}
    for match in matches:
        criterion_id = match.get("criterion_id")
        if criterion_id not in by_criterion:
            by_criterion[criterion_id] = match
    verified = []
    for criterion in criteria:
        match = by_criterion.get(criterion["id"], {})
        evidence = []
        for item in match.get("evidence", [])[:4]:
            quote, source = item.get("quote", ""), sources.get(item.get("segment_id"), "")
            if isinstance(quote, str) and quote.strip() and quote in source:
                evidence.append({"segment_id": item["segment_id"], "quote": quote})
        status = match.get("status", "insufficient")
        if status not in {"supported", "partial", "insufficient"}:
            status = "insufficient"
        invalid_claim = status in {"supported", "partial"} and not evidence
        if invalid_claim:
            status = "insufficient"
        reason = str(match.get("reason", "No verified supporting text found."))[:1000]
        if invalid_claim:
            reason = "The proposed evidence could not be verified in the source. Recruiter clarification is required."
        verified.append({"criterion_id": criterion["id"], "label": criterion["label"],
                         "weight": criterion["weight"], "status": status,
                         "reason": reason, "evidence": evidence})
    return verified


def score_matches(matches: list[dict]) -> dict:
    factors = {"supported": 1.0, "partial": 0.5, "insufficient": 0.0}
    total = sum(float(match["weight"]) for match in matches)
    score = sum(float(match["weight"]) * factors.get(match["status"], 0) for match in matches)
    return {"score": round(score / total * 100, 1) if total else 0,
            "missing_count": sum(match["status"] == "insufficient" for match in matches)}


def verified_score(segments: list[dict], criteria: list[dict], matches: list[dict]) -> dict:
    matches = validate_matches(segments, criteria, matches)
    return {"matches": matches, **score_matches(matches)}


class ScreeningState(TypedDict, total=False):
    segments: list[dict]
    criteria: list[dict]
    mode: str
    matches: list[dict]
    score: float
    missing_count: int
    awaiting_review: bool
    approved: bool
    review_notes: str


@contextmanager
def _checkpointer(url: str):
    # Only JSON-compatible primitives are stored; strict deserialization blocks arbitrary imports.
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    if url.startswith(("postgresql://", "postgres://", "postgresql+psycopg://")):
        from langgraph.checkpoint.postgres import PostgresSaver

        url = url.replace("postgresql+psycopg://", "postgresql://", 1)
        with PostgresSaver.from_conn_string(url) as saver:
            saver.setup()
            yield saver
    else:
        from langgraph.checkpoint.sqlite import SqliteSaver

        path = url.removeprefix("sqlite+aiosqlite:///").removeprefix("sqlite:///")
        if path != ":memory:":
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path, check_same_thread=False, timeout=20) as connection:
            saver = SqliteSaver(connection)
            saver.setup()
            yield saver


def run_screening(thread_id: str, segments: list[dict], criteria: list[dict],
                  checkpointer_url: str, mode: str = "demo", resume: dict | None = None) -> dict:
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command, interrupt

    if not thread_id or len(thread_id) > 250:
        raise ServiceError("A valid screening workflow ID is required.")
    if not criteria or len(criteria) > 12 or abs(sum(c["weight"] for c in criteria) - 100) > .01:
        raise ServiceError("Confirm screening criteria with positive weights totaling 100 before screening.")
    if any(c["weight"] <= 0 for c in criteria):
        raise ServiceError("Every screening criterion needs a positive weight.")
    if resume is not None and (not isinstance(resume.get("approved"), bool)
                               or len(str(resume.get("notes", ""))) > 5000):
        raise ServiceError("Review must include an approval choice and notes shorter than 5,000 characters.")

    def evaluate_node(state: ScreeningState) -> dict:
        result = verified_score(state["segments"], state["criteria"],
                                ai.evaluate(state["segments"], state["criteria"], state["mode"]))
        return {**result, "awaiting_review": True}

    def review_node(state: ScreeningState) -> dict:
        review = interrupt({"score": state["score"], "missing_count": state["missing_count"],
                            "matches": state["matches"], "message": "Recruiter review required"})
        return {"approved": bool(review["approved"]), "review_notes": str(review.get("notes", "")),
                "awaiting_review": False}

    builder = StateGraph(ScreeningState)
    builder.add_node("evaluate", evaluate_node)
    builder.add_node("review", review_node)
    builder.add_edge(START, "evaluate")
    builder.add_edge("evaluate", "review")
    builder.add_edge("review", END)
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 8}
    with _checkpointer(checkpointer_url) as saver:
        graph = builder.compile(checkpointer=saver)
        current = graph.get_state(config)
        if current.values and (not current.next or (resume is None and current.values.get("awaiting_review"))):
            result = current.values
        elif resume is not None:
            if not current.values:
                raise ServiceError("This screening has no pending review. Start screening first.")
            result = graph.invoke(Command(resume=resume), config=config)
        else:
            initial = {"segments": segments, "criteria": criteria, "mode": mode} if not current.values else None
            result = graph.invoke(initial, config=config)
        return {key: result.get(key) for key in
                ["matches", "score", "missing_count", "awaiting_review", "approved", "review_notes"]}
