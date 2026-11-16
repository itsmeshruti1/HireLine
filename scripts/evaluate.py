"""Evaluate the selected provider on fictional fixtures; never imply demo matching is an LLM."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["demo", "gemini"], default="demo")
    parser.add_argument("--confirm-synthetic", action="store_true")
    args = parser.parse_args()
    if args.mode == "gemini" and not args.confirm_synthetic:
        parser.error("Hosted evaluation requires --confirm-synthetic and consumes free-tier quota.")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    from app.services import ai
    from app.services.documents import extract_document
    from app.services.screening import verified_score

    data = json.loads((ROOT / "fixtures/synthetic.json").read_text(encoding="utf-8"))
    labels = json.loads((ROOT / "fixtures/labels.json").read_text(encoding="utf-8"))
    if data.get("synthetic") is not True:
        raise ValueError("Evaluation accepts only the synthetic fixture set.")
    extracted = {}
    correct, count, skills_found, skill_count = 0, 0, 0, 0
    failures = []
    for person in data["candidates"]:
        try:
            path = ROOT / person["sample_file"]
            segments = extract_document(path.name, path.read_bytes())
            profile = ai.extract_profile(segments, mode=args.mode)
            extracted[person["id"]] = segments
            for field in ["name", "email", "experience_years", "location", "notice_period_days", "salary_expectation"]:
                actual_value, expected_value = profile.get(field, ""), person[field]
                if isinstance(expected_value, (int, float)):
                    correct += actual_value == expected_value
                else:
                    correct += str(actual_value).strip().casefold() == str(expected_value).strip().casefold()
                count += 1
            actual = {skill.lower() for skill in profile.get("skills", [])}
            skills_found += sum(skill.lower() in actual for skill in person["skills"])
            skill_count += len(person["skills"])
        except Exception as exc:
            failures.append({"candidate_id": person["id"], "error": str(exc)})
    rankings = []
    evidence_count, valid_evidence = 0, 0
    for job in data["jobs"]:
        scores, baseline = [], []
        for person in data["candidates"]:
            if person["id"] not in extracted:
                continue
            segments = extracted[person["id"]]
            try:
                raw = ai.evaluate(segments, job["criteria"], mode=args.mode)
                result = verified_score(segments, job["criteria"], raw)
                scores.append((person["id"], result["score"]))
                for match in result["matches"]:
                    for evidence in match["evidence"]:
                        evidence_count += 1
                        valid_evidence += any(s["id"] == evidence["segment_id"] and evidence["quote"] in s["text"] for s in segments)
                text = " ".join(s["text"] for s in segments).lower()
                terms = [c["label"].lower() for c in job["criteria"]]
                baseline.append((person["id"], sum(bool(re.search(r"\b" + re.escape(term) + r"\b", text)) for term in terms)))
            except Exception as exc:
                failures.append({"candidate_id": person["id"], "job_id": job["id"], "error": str(exc)})
        relevant = set(labels["relevant_candidates"][job["id"]])
        top = [cid for cid, _ in sorted(scores, key=lambda item: (-item[1], item[0]))[:5]]
        keyword_top = [cid for cid, _ in sorted(baseline, key=lambda item: (-item[1], item[0]))[:5]]
        rankings.append({"job": job["title"], "top_five": top,
            "precision_at_5": sum(cid in relevant for cid in top) / 5,
            "keyword_precision_at_5": sum(cid in relevant for cid in keyword_top) / 5})
    result = {"mode": args.mode, "timestamp": datetime.now(timezone.utc).isoformat(),
        "resumes": len(data["candidates"]), "scalar_field_accuracy": correct / max(count, 1),
        "skill_recall": skills_found / max(skill_count, 1),
        "verified_source_quotes": valid_evidence, "accepted_source_quotes": evidence_count,
        "rankings": rankings, "failures": failures}
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs/evaluation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    rows = "\n".join(f"| {r['job']} | {r['precision_at_5']:.0%} | {r['keyword_precision_at_5']:.0%} |" for r in rankings)
    report = f"""# Screening evaluation

Provider mode: **{args.mode}**. Generated {result['timestamp']}.

Evaluated {result['resumes']} fictional resumes, split between PDF and DOCX, against three jobs.

| Measurement | Observed result |
| --- | --- |
| Exact scalar field accuracy (name, email, experience, location, notice, salary) | {result['scalar_field_accuracy']:.1%} |
| Expected skill recall | {result['skill_recall']:.1%} |
| Accepted quotes found verbatim in their source | {valid_evidence}/{evidence_count} |
| Processing failures | {len(failures)} |

| Job | Evidence matcher precision@5 | Keyword baseline precision@5 |
| --- | --- | --- |
{rows}

## Interpretation

Demo mode uses deterministic term matching; these results are **not Gemini accuracy measurements**.
Run `python scripts/evaluate.py --mode gemini --confirm-synthetic` after configuring a free-tier model to measure that provider.
Only extraction and matching are evaluated; human decisions are never automated.

The fixtures and relevance labels were authored together by the project author. They are small,
synthetic, and not independently annotated or representative of hiring performance. Skill recall
does not measure false-positive skills. Verbatim source validation proves a quote exists, not that
the interpretation is correct. A keyword-heavy resume can still mislead the demo matcher.
Top-five ties are broken by candidate ID for reproducibility. Review both results and limitations
before making claims in a portfolio presentation.
"""
    (ROOT / "docs/evaluation.md").write_text(report, encoding="utf-8")
    print(json.dumps(result, indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
