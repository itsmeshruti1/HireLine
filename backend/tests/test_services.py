from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from docx import Document
from pypdf import PdfWriter

from backend.app.services import ai
from backend.app.services.documents import extract_document
from backend.app.services.errors import ServiceError
from backend.app.services.integrations import Integrations
from backend.app.services.screening import run_screening, verified_score
from backend.app.services.storage import DocumentStorage


def test_fabricated_and_wrong_page_evidence_cannot_contribute():
    result = verified_score([{"id": "page-1", "text": "Built Python APIs."}],
        [{"id": "python", "label": "Python", "weight": 100}],
        [{"criterion_id": "python", "status": "supported", "weight": 1000,
          "evidence": [{"segment_id": "page-1", "quote": "Python expert with ten years"},
                       {"segment_id": "page-2", "quote": "Built Python APIs."}]}])
    assert result["score"] == 0
    assert result["missing_count"] == 1
    assert result["matches"][0]["weight"] == 100


def test_weighted_score_and_unknown_criteria():
    criteria = [{"id": "python", "label": "Python", "weight": 60},
                {"id": "react", "label": "React", "weight": 40}]
    result = verified_score([{"id": "p1", "text": "Python React"}], criteria,
        [{"criterion_id": "python", "status": "supported", "evidence": [{"segment_id": "p1", "quote": "Python"}]},
         {"criterion_id": "react", "status": "partial", "evidence": [{"segment_id": "p1", "quote": "React"}]},
         {"criterion_id": "invented", "status": "supported", "weight": 5000}])
    assert result["score"] == 80
    assert len(result["matches"]) == 2


def test_pause_and_review_survive_new_graph_and_do_not_repeat_ai(tmp_path, monkeypatch):
    calls = []
    original = ai.evaluate

    def evaluate(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(ai, "evaluate", evaluate)
    kwargs = dict(thread_id="application-v1", segments=[{"id": "p1", "text": "Built Python APIs."}],
                  criteria=[{"id": "python", "label": "Python", "weight": 100}],
                  checkpointer_url="sqlite:///" + str(tmp_path / "checkpoints.db"))
    assert run_screening(**kwargs)["awaiting_review"]
    assert run_screening(**kwargs)["awaiting_review"]
    approved = run_screening(**kwargs, resume={"approved": True, "notes": "Verified sources"})
    assert approved["approved"] and not approved["awaiting_review"]
    assert run_screening(**kwargs, resume={"approved": False})["approved"]
    assert len(calls) == 1


def test_invalid_workflow_inputs(tmp_path):
    with pytest.raises(ServiceError, match="totaling 100"):
        run_screening("a", [{"id": "p1", "text": "Python"}],
                      [{"id": "p", "label": "Python", "weight": 60}], str(tmp_path / "c.db"))


def test_demo_profile_extraction_skips_banner_and_preserves_missing_values():
    profile = ai.extract_profile([{"id": "p1", "text":
        "SYNTHETIC PORTFOLIO RESUME - FICTIONAL PERSON\nName: Ada Example\nada@example.test\n"
        "Backend engineer\nExperience: 4 years\nLocation: Pune\nSkills: Python, PostgreSQL\nNotice period: 30 days"}])
    assert profile["name"] == "Ada Example"
    assert profile["email"] == "ada@example.test"
    assert profile["headline"] == "Backend engineer"
    assert profile["experience_years"] == 4
    assert profile["notice_period_days"] == 30


def test_demo_negative_statement_is_not_positive_evidence():
    matches = ai.evaluate([{"id": "p1", "text": "No FastAPI project is described. Built Python APIs."}],
                          [{"id": "f", "label": "FastAPI", "weight": 100}])
    assert matches[0]["status"] == "insufficient"


def test_draft_criteria_sum_to_100_and_short_answer_requires_review():
    criteria = ai.draft_criteria("Build Python APIs with FastAPI and PostgreSQL. Write automated tests.")
    assert sum(row["weight"] for row in criteria) == 100
    feedback = ai.assess_short_answers([{"id": "q1", "kind": "short", "prompt": "Describe a test."}], {"q1": "A test"})
    assert feedback[0]["requires_review"]


def test_draft_criteria_keeps_small_provider_weights_positive(monkeypatch):
    rows = [{"label": f"Criterion {index}", "weight": weight}
            for index, weight in enumerate([1, 1, 99, 99, 99, 99, 99, 99])]
    monkeypatch.setattr(ai, "_generate", lambda *args: ai.CriteriaResponse(criteria=rows))
    criteria = ai.draft_criteria("A synthetic job description", "gemini")
    assert sum(row["weight"] for row in criteria) == 100
    assert all(row["weight"] >= 1 for row in criteria)


def test_gemini_quota_error_is_actionable_without_leaking_key(monkeypatch):
    from google import genai

    class QuotaError(Exception):
        code = 429

    def generate(**kwargs):
        raise QuotaError("RESOURCE_EXHAUSTED private-key")

    monkeypatch.setenv("GEMINI_API_KEY", "private-key")
    monkeypatch.setenv("GEMINI_MODEL", "configured-model")
    monkeypatch.setattr(genai, "Client", lambda **kwargs: SimpleNamespace(
        models=SimpleNamespace(generate_content=generate), close=lambda: None))
    with pytest.raises(ServiceError, match="quota is exhausted") as caught:
        ai.draft_criteria("Python APIs", "gemini")
    assert "private-key" not in str(caught.value)


def test_gemini_reads_dotenv_settings_without_exported_environment(tmp_path, monkeypatch):
    from google import genai
    from backend.app import config

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    (tmp_path / ".env").write_text(
        "APP_ENV=test\nGEMINI_API_KEY=dotenv-private-key\nGEMINI_MODEL=dotenv-model\n", encoding="utf-8")
    captured = {}

    def client(**kwargs):
        captured.update(kwargs)

        def generate(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text='{"criteria":[{"label":"Python experience","weight":100}]}')

        return SimpleNamespace(models=SimpleNamespace(generate_content=generate), close=lambda: None)

    monkeypatch.setattr(genai, "Client", client)
    config.get_settings.cache_clear()
    try:
        criteria = ai.draft_criteria("Python APIs", "gemini")
        assert captured["api_key"] == "dotenv-private-key"
        assert captured["model"] == "dotenv-model"
        assert criteria[0]["weight"] == 100
        assert "dotenv-private-key" not in captured["contents"]
    finally:
        config.get_settings.cache_clear()


def test_docx_extraction_and_invalid_file():
    document = Document()
    document.add_paragraph("Name: Synthetic Example")
    document.add_paragraph("Built Python APIs with PostgreSQL and automated testing.")
    content = BytesIO()
    document.save(content)
    assert any("Python" in row["text"] for row in extract_document("resume.docx", content.getvalue()))
    with pytest.raises(ValueError, match="valid"):
        extract_document("invalid.docx", b"not a zip document")
    with pytest.raises(ValueError, match="Only PDF"):
        extract_document("executable.exe", b"MZ...")


def test_blank_scanned_pdf_and_too_many_pages():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    content = BytesIO()
    writer.write(content)
    with pytest.raises(ValueError, match="Scanned PDFs"):
        extract_document("scan.pdf", content.getvalue())
    for _ in range(30):
        writer.add_blank_page(width=200, height=200)
    content = BytesIO()
    writer.write(content)
    with pytest.raises(ValueError, match="30 pages"):
        extract_document("too-many.pdf", content.getvalue())


def test_private_local_storage_and_traversal(tmp_path):
    storage = DocumentStorage({"local_storage_dir": str(tmp_path)})
    storage.put("candidate/resume.pdf", b"resume")
    assert storage.read("candidate/resume.pdf") == b"resume"
    with pytest.raises(ServiceError, match="Invalid"):
        storage.put("../escape.pdf", b"no")
    with pytest.raises(ServiceError, match="authenticated"):
        storage.signed_url("candidate/resume.pdf")
    storage.delete("candidate/resume.pdf")


@pytest.mark.parametrize("key, bearer", [("legacy-test-token", "Bearer legacy-test-token"), ("sb_secret_test", None)])
def test_supabase_private_storage_signed_link(key, bearer):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"signedURL": "/object/sign/resumes/a.pdf?token=abc"})

    storage = DocumentStorage({"supabase_url": "https://example.supabase.co", "supabase_service_role_key": key},
                              httpx.Client(transport=httpx.MockTransport(respond)))
    url = storage.signed_url("a.pdf", 9999)
    assert requests[0].headers["apikey"] == key
    assert requests[0].headers.get("authorization") == bearer
    assert url.startswith("https://example.supabase.co/storage/v1/object/sign/")
    assert b'"expiresIn":300' in requests[0].content


def test_preview_integrations_do_not_make_network_calls():
    def forbidden(request):
        raise AssertionError("preview should make no provider requests")

    integrations = Integrations({"external_mode": "preview"}, httpx.Client(transport=httpx.MockTransport(forbidden)))
    assert integrations.send_email("a1", "candidate@example.test", "Hello", "Message")["status"] == "preview"
    assert integrations.create_event("a2", {}, "2027-01-01T10:00:00Z", "2027-01-01T11:00:00Z",
                                     ["candidate@example.test"])["status"] == "preview"


def test_live_email_always_redirects_to_signup_inbox_with_idempotency():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "email-provider-id"})

    integration = Integrations({"external_mode": "live", "resend_api_key": "secret",
                                "resend_test_inbox": "owner@example.com"},
                               httpx.Client(transport=httpx.MockTransport(respond)))
    receipt = integration.send_email("stable-action", "outsider@example.com", "Interview", "Text")
    import json
    assert json.loads(requests[0].content)["to"] == ["owner@example.com"]
    assert requests[0].headers["Idempotency-Key"] == "stable-action"
    assert receipt["delivered_to"] == "owner@example.com"


def test_ambiguous_email_send_requires_reconciliation():
    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)

    integration = Integrations({"external_mode": "live", "resend_api_key": "secret",
                                "resend_test_inbox": "owner@example.com"},
                               httpx.Client(transport=httpx.MockTransport(timeout)))
    with pytest.raises(ServiceError) as caught:
        integration.send_email("action", "candidate@example.test", "Interview", "Text")
    assert caught.value.ambiguous and not caught.value.retryable


def calendar(handler):
    return Integrations({"external_mode": "live", "calendar_allowed_emails": "owner@example.com"},
                        httpx.Client(transport=httpx.MockTransport(handler)))


def test_calendar_recipient_allowlist_is_checked_before_network():
    with pytest.raises(ServiceError, match="owned test-account"):
        calendar(lambda request: pytest.fail("unexpected network")).create_event(
            "event1", {"access_token": "secret"}, "2027-01-01T10:00:00Z", "2027-01-01T11:00:00Z", ["outsider@example.com"])


def test_calendar_reconciles_existing_booking_before_freebusy():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "existing-event", "htmlLink": "https://calendar.google.com/event"})

    result = calendar(respond).create_event("event1", {"access_token": "secret"},
        "2027-01-01T10:00:00Z", "2027-01-01T11:00:00Z", ["owner@example.com"])
    assert result["reconciled"]
    assert len(requests) == 1 and requests[0].method == "GET"


def test_calendar_busy_slot_is_rejected_before_create():
    def respond(request):
        if request.method == "GET":
            return httpx.Response(404, json={})
        assert request.url.path.endswith("freeBusy")
        return httpx.Response(200, json={"calendars": {"primary": {"busy": [
            {"start": "2027-01-01T10:00:00Z", "end": "2027-01-01T11:00:00Z"}]}}})

    with pytest.raises(ServiceError, match="now busy"):
        calendar(respond).create_event("event1", {"access_token": "secret"},
            "2027-01-01T10:00:00Z", "2027-01-01T11:00:00Z", ["owner@example.com"])


def test_calendar_create_uses_stable_id_and_owned_attendees():
    captured = []

    def respond(request):
        captured.append(request)
        if request.method == "GET":
            return httpx.Response(404, json={})
        if request.url.path.endswith("freeBusy"):
            return httpx.Response(200, json={"calendars": {"primary": {"busy": []}}})
        import json
        return httpx.Response(200, json={"id": json.loads(request.content)["id"]})

    result = calendar(respond).create_event("stable-action", {"access_token": "secret"},
        "2027-01-01T10:00:00Z", "2027-01-01T11:00:00Z", ["OWNER@example.com"])
    import hashlib
    assert result["id"] == hashlib.sha256(b"stable-action").hexdigest()
    assert captured[-1].url.params["sendUpdates"] == "all"


def test_oauth_refresh_token_is_preserved():
    integration = calendar(lambda request: httpx.Response(200, json={"access_token": "renewed", "expires_in": 3600}))
    old = {"access_token": "old", "refresh_token": "refresh", "connected_at": datetime.now(timezone.utc).isoformat()}
    renewed = integration.refresh_tokens(old)
    assert renewed["refresh_token"] == "refresh"
    assert renewed["connected_at"] == old["connected_at"]
    assert datetime.fromisoformat(renewed["expires_at"]) > datetime.now(timezone.utc) + timedelta(minutes=55)


def test_known_email_quota_rejection_is_retryable_not_ambiguous():
    integration = Integrations({"external_mode": "live", "resend_api_key": "secret",
                                "resend_test_inbox": "owner@example.com"},
                               httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(429))))
    with pytest.raises(ServiceError) as caught:
        integration.send_email("action", "candidate@example.test", "Interview", "Text")
    assert caught.value.retryable and not caught.value.ambiguous


def test_unreadable_successful_email_receipt_is_ambiguous():
    integration = Integrations({"external_mode": "live", "resend_api_key": "secret",
                                "resend_test_inbox": "owner@example.com"},
                               httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="not-json"))))
    with pytest.raises(ServiceError) as caught:
        integration.send_email("action", "candidate@example.test", "Interview", "Text")
    assert caught.value.ambiguous and not caught.value.retryable


def test_calendar_refreshes_once_after_unexpected_401_and_preserves_connection():
    requests = []
    connected_at = datetime.now(timezone.utc).isoformat()
    tokens = {"access_token": "old", "refresh_token": "refresh", "connected_at": connected_at,
              "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}

    def respond(request):
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "new", "expires_in": 3600})
        if request.headers["Authorization"] == "Bearer old":
            return httpx.Response(401)
        assert request.headers["Authorization"] == "Bearer new"
        return httpx.Response(200, json={"calendars": {"primary": {"busy": []}}})

    result = calendar(respond).freebusy(tokens, "2027-01-01T10:00:00Z", "2027-01-01T11:00:00Z")
    assert result["busy"] == []
    assert len(requests) == 3
    assert tokens["access_token"] == "new"
    assert tokens["refresh_token"] == "refresh" and tokens["connected_at"] == connected_at


def test_calendar_persistent_401_requests_reconnection_without_unbounded_retry():
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "new"})
        return httpx.Response(401)

    with pytest.raises(ServiceError) as caught:
        calendar(respond).freebusy({"access_token": "old", "refresh_token": "refresh"},
                                   "2027-01-01T10:00:00Z", "2027-01-01T11:00:00Z")
    assert caught.value.reconnect_required
    assert len(requests) == 3


def test_invalid_refresh_grant_requires_reconnect_but_transient_outage_does_not():
    for status, reconnect, retryable in [(400, True, False), (503, False, True)]:
        with pytest.raises(ServiceError) as caught:
            calendar(lambda request: httpx.Response(status)).refresh_tokens({"refresh_token": "refresh"})
        assert caught.value.reconnect_required == reconnect
        assert caught.value.retryable == retryable


def test_unreadable_successful_booking_receipt_is_ambiguous():
    def respond(request):
        if request.method == "GET":
            return httpx.Response(404)
        if request.url.path.endswith("freeBusy"):
            return httpx.Response(200, json={"calendars": {"primary": {"busy": []}}})
        return httpx.Response(200, text="unreadable-receipt")

    with pytest.raises(ServiceError) as caught:
        calendar(respond).create_event("action", {"access_token": "secret"},
            "2027-01-01T10:00:00Z", "2027-01-01T11:00:00Z", ["owner@example.com"])
    assert caught.value.ambiguous


def test_calendar_rejects_invalid_busy_result_instead_of_assuming_available():
    integration = calendar(lambda request: httpx.Response(200, json={"calendars": {"primary": {"busy": None}}}))
    with pytest.raises(ServiceError, match="availability result"):
        integration.freebusy({"access_token": "secret"}, "2027-01-01T10:00:00Z", "2027-01-01T11:00:00Z")


def test_screening_accepts_same_fractional_weight_tolerance_as_api(tmp_path):
    result = run_screening("fractional-weight", [{"id": "p1", "text": "Built Python APIs."}],
        [{"id": "python", "label": "Python", "weight": 99.999}], "sqlite:///" + str(tmp_path / "fractional.db"))
    assert result["awaiting_review"] and result["score"] == 100
