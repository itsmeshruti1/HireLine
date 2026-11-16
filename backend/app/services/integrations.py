"""Explicit preview/live email and Calendar adapters with test-account restrictions."""

import hashlib
from datetime import datetime, timedelta, timezone as tz
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from .errors import ServiceError
from .storage import setting

CALENDAR_SCOPES = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.freebusy"


def _datetime(value: str | datetime) -> datetime:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("timezone required")
        return result.astimezone(tz.utc)
    except (ValueError, AttributeError) as exc:
        raise ServiceError("Interview times must include a timezone, such as +05:30 or Z.") from exc


def _window(start: str | datetime, end: str | datetime) -> tuple[str, str]:
    first, last = _datetime(start), _datetime(end)
    if last <= first or last - first > timedelta(hours=8):
        raise ServiceError("Choose an interview duration between 1 minute and 8 hours.")
    return first.isoformat(), last.isoformat()


class Integrations:
    def __init__(self, settings=None, client: httpx.Client | None = None):
        self.mode = str(setting(settings, "external_mode", "preview"))
        if self.mode not in {"preview", "live"}:
            raise ServiceError("EXTERNAL_MODE must be preview or live.")
        self.resend_key = str(setting(settings, "resend_api_key"))
        self.inbox = str(setting(settings, "resend_test_inbox", aliases=("test_email",))).strip().lower()
        self.google_id = str(setting(settings, "google_client_id"))
        self.google_secret = str(setting(settings, "google_client_secret"))
        self.redirect_uri = str(setting(settings, "google_redirect_uri", aliases=("google_redirect_url",)))
        allowed = setting(settings, "calendar_allowed_emails", aliases=("calendar_test_emails",))
        self.allowed_emails = {email.strip().lower() for email in (allowed.split(",") if isinstance(allowed, str) else allowed) if email.strip()}
        self.client = client

    def status(self, tokens: dict | None = None) -> dict:
        expiry = tokens.get("expires_at") if tokens else None
        reconnect = not tokens or not tokens.get("refresh_token")
        if tokens and tokens.get("connected_at"):
            try:
                reconnect = reconnect or _datetime(tokens["connected_at"]) + timedelta(days=7) < datetime.now(tz.utc)
            except ServiceError:
                reconnect = True
        return {"mode": self.mode, "email_configured": bool(self.resend_key and self.inbox),
                "email_test_inbox": self.inbox or None,
                "calendar_configured": bool(self.google_id and self.google_secret and self.redirect_uri and self.allowed_emails),
                "calendar_connected": bool(tokens), "calendar_reconnect_required": reconnect,
                "calendar_token_expires_at": expiry,
                "note": "Preview mode makes no external requests." if self.mode == "preview"
                        else "Email routes only to your test inbox; Calendar attendees must be allowlisted owned accounts."}

    def _request(self, method: str, url: str, *, ambiguous: bool = False, **kwargs) -> httpx.Response:
        try:
            if self.client:
                return self.client.request(method, url, **kwargs)
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                return client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise ServiceError("The provider connection failed. Check delivery before retrying." if ambiguous
                               else "The provider is unreachable. Reconnect or retry later.",
                               retryable=not ambiguous, ambiguous=ambiguous) from exc

    @staticmethod
    def _json(response: httpx.Response, message: str, *, ambiguous: bool = False) -> dict:
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Expected an object")
            return result
        except ValueError as exc:
            raise ServiceError(message, ambiguous=ambiguous) from exc

    def _authorized_request(self, tokens: dict, method: str, url: str, **kwargs) -> httpx.Response:
        token = self._access_token(tokens)
        for attempt in range(2):
            response = self._request(method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs)
            if response.status_code != 401:
                return response
            if attempt == 0 and tokens.get("refresh_token"):
                tokens.update(self.refresh_tokens(tokens))
                token = tokens["access_token"]
                continue
            raise ServiceError("Google Calendar authorization expired. Reconnect Calendar.", reconnect_required=True)
        raise ServiceError("Google Calendar authorization expired. Reconnect Calendar.", reconnect_required=True)

    def send_email(self, action_id: str, to: str, subject: str, body: str) -> dict:
        if not action_id or len(action_id) > 200 or "\r" in subject or "\n" in subject:
            raise ServiceError("Email action ID and subject are invalid.")
        if len(subject) > 300 or len(body) > 20_000:
            raise ServiceError("The email is too long. Shorten the subject or message.")
        if self.mode == "preview":
            return {"id": "preview-" + action_id, "status": "preview", "intended_recipient": to,
                    "delivered_to": None, "subject": subject, "body": body}
        if not self.resend_key or not self.inbox or "@" not in self.inbox:
            raise ServiceError("Configure RESEND_API_KEY and RESEND_TEST_INBOX before sending live test email.")
        # All candidate mail is redirected at this final boundary, independently of caller input.
        response = self._request("POST", "https://api.resend.com/emails", ambiguous=True,
            headers={"Authorization": f"Bearer {self.resend_key}", "Idempotency-Key": action_id},
            json={"from": "Recruiter Demo <onboarding@resend.dev>", "to": [self.inbox],
                  "subject": "[Recruiter demo] " + subject,
                  "text": "Synthetic demo. Intended candidate: " + to + "\nActual delivery: your test inbox.\n\n" + body})
        if response.status_code >= 500:
            raise ServiceError("Email delivery is uncertain. Reconcile this action in Resend before retrying.", ambiguous=True)
        if response.status_code == 429:
            raise ServiceError("The email provider quota is exhausted. Wait before sending again.", retryable=True)
        if response.status_code >= 300:
            raise ServiceError("Resend rejected the message. Verify the API key and signup test inbox.")
        provider_id = self._json(response, "Email delivery returned an unreadable receipt. Check Resend before retrying.",
                                 ambiguous=True).get("id")
        if not provider_id:
            raise ServiceError("Email delivery returned no receipt. Check Resend before retrying.", ambiguous=True)
        return {"id": provider_id, "status": "sent", "intended_recipient": to, "delivered_to": self.inbox}

    def authorization_url(self, state: str) -> str:
        if not self.google_id or not self.google_secret or not self.redirect_uri:
            raise ServiceError("Configure Google Calendar client ID, secret and redirect URI first.")
        if not state or len(state) > 500:
            raise ServiceError("A valid OAuth state is required.")
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": self.google_id, "redirect_uri": self.redirect_uri, "response_type": "code",
            "scope": CALENDAR_SCOPES, "state": state, "access_type": "offline", "prompt": "consent"})

    def _token_result(self, response: httpx.Response, previous: dict | None = None) -> dict:
        if response.status_code == 429 or response.status_code >= 500:
            raise ServiceError("Google authorization is temporarily unavailable. Retry later.", retryable=True)
        if response.status_code >= 300:
            raise ServiceError("Google Calendar connection expired or was rejected. Reconnect your owned test account.",
                               reconnect_required=True)
        result = self._json(response, "Google returned an unreadable authorization response. Reconnect Calendar.")
        if not result.get("access_token"):
            raise ServiceError("Google did not return an access token. Reconnect Calendar.", reconnect_required=True)
        try:
            expires_in = int(result.get("expires_in", 3600))
            if not 1 <= expires_in <= 86400:
                raise ValueError("Invalid token lifetime")
        except (ValueError, TypeError) as exc:
            raise ServiceError("Google returned an invalid authorization lifetime. Reconnect Calendar.",
                               reconnect_required=True) from exc
        result["expires_at"] = (datetime.now(tz.utc) + timedelta(seconds=expires_in)).isoformat()
        result["connected_at"] = (previous or {}).get("connected_at", datetime.now(tz.utc).isoformat())
        if previous and not result.get("refresh_token"):
            result["refresh_token"] = previous.get("refresh_token")
        return result

    def exchange_code(self, code: str) -> dict:
        if not self.google_id or not self.google_secret or not self.redirect_uri:
            raise ServiceError("Google Calendar OAuth is not configured.")
        response = self._request("POST", "https://oauth2.googleapis.com/token", data={
            "client_id": self.google_id, "client_secret": self.google_secret,
            "redirect_uri": self.redirect_uri, "code": code, "grant_type": "authorization_code"})
        return self._token_result(response)

    def refresh_tokens(self, refresh_token: str | dict) -> dict:
        previous = refresh_token if isinstance(refresh_token, dict) else {"refresh_token": refresh_token}
        if not previous.get("refresh_token"):
            raise ServiceError("Reconnect Google Calendar to renew its authorization.")
        response = self._request("POST", "https://oauth2.googleapis.com/token", data={
            "client_id": self.google_id, "client_secret": self.google_secret,
            "refresh_token": previous["refresh_token"], "grant_type": "refresh_token"})
        return self._token_result(response, previous)

    def revoke_tokens(self, tokens: dict) -> None:
        token = tokens.get("refresh_token") or tokens.get("access_token")
        if token:
            response = self._request("POST", "https://oauth2.googleapis.com/revoke", data={"token": token})
            if response.status_code not in {200, 400}:
                raise ServiceError("Google could not revoke this connection. Retry disconnection.")

    def _access_token(self, tokens: dict) -> str:
        if not tokens or not tokens.get("access_token"):
            raise ServiceError("Connect Google Calendar before checking availability or creating an interview.",
                               reconnect_required=True)
        if tokens.get("expires_at") and _datetime(tokens["expires_at"]) <= datetime.now(tz.utc):
            # Update the caller's dict so the API can persist rotated tokens.
            tokens.update(self.refresh_tokens(tokens))
        return tokens["access_token"]

    def freebusy(self, tokens: dict, start: str, end: str) -> dict:
        first, last = _datetime(start), _datetime(end)
        if last <= first or last - first > timedelta(days=31):
            raise ServiceError("Choose an availability window of at most 31 days.")
        if self.mode == "preview":
            return {"busy": [], "status": "preview", "note": "Preview availability is not a live calendar check."}
        response = self._authorized_request(tokens, "POST", "https://www.googleapis.com/calendar/v3/freeBusy",
            json={"timeMin": first.isoformat(), "timeMax": last.isoformat(), "items": [{"id": "primary"}]})
        if response.status_code >= 300:
            raise ServiceError("Google Calendar could not check availability. Verify Calendar API access and scopes.",
                               retryable=response.status_code == 429 or response.status_code >= 500)
        payload = self._json(response, "Calendar returned an unreadable availability result. Retry before scheduling.")
        calendars = payload.get("calendars", {})
        calendar = calendars.get("primary", {}) if isinstance(calendars, dict) else {}
        if not isinstance(calendar, dict):
            raise ServiceError("Calendar returned an invalid availability result. Retry before scheduling.")
        if calendar.get("errors"):
            raise ServiceError("Your primary calendar is unavailable. Select a connected account with Calendar access.")
        if "busy" not in calendar or not isinstance(calendar["busy"], list):
            raise ServiceError("Calendar returned no availability result. Retry before scheduling.")
        if any(not isinstance(slot, dict) or not slot.get("start") or not slot.get("end") for slot in calendar["busy"]):
            raise ServiceError("Calendar returned invalid busy slots. Retry before scheduling.")
        return {"busy": calendar["busy"], "status": "checked"}

    def create_event(self, action_id: str, tokens: dict, start: str, end: str, attendees: list[str],
                     summary: str = "Interview", timezone: str = "UTC") -> dict:
        start, end = _window(start, end)
        if not action_id or len(action_id) > 200:
            raise ServiceError("A valid interview action ID is required.")
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ServiceError("Choose a recognized interview timezone.") from exc
        event_id = hashlib.sha256(action_id.encode()).hexdigest()
        if self.mode == "preview":
            return {"id": "preview-" + event_id, "status": "preview", "start": start, "end": end,
                    "summary": summary, "attendees": [], "htmlLink": None}
        normalized = sorted({email.strip().lower() for email in attendees if email.strip()})
        if not self.allowed_emails or any(email not in self.allowed_emails for email in normalized):
            raise ServiceError("Calendar invitations may include only your configured owned test-account addresses.")
        if not normalized:
            raise ServiceError("Include at least one owned test-account attendee.")
        url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        # Reconciliation comes first: retrying a successful booking must not fail its own free/busy check.
        existing = self._authorized_request(tokens, "GET", url + "/" + quote(event_id))
        if existing.status_code == 200:
            event = self._json(existing, "Calendar returned an unreadable booking receipt. Reconcile before trying again.", ambiguous=True)
            if not event.get("id"):
                raise ServiceError("Calendar returned no booking ID. Reconcile before trying again.", ambiguous=True)
            if event.get("status") == "cancelled":
                raise ServiceError("The existing interview was cancelled. Create a new scheduling action.")
            return {"id": event["id"], "status": "sent", "htmlLink": event.get("htmlLink"), "reconciled": True}
        if existing.status_code != 404:
            raise ServiceError("Calendar could not reconcile the interview. Reconnect or retry later.",
                               retryable=existing.status_code == 429 or existing.status_code >= 500)
        availability = self.freebusy(tokens, start, end)
        if availability["busy"]:
            raise ServiceError("That interview slot is now busy. Choose another time and confirm again.")
        response = self._authorized_request(tokens, "POST", url, ambiguous=True, params={"sendUpdates": "all"},
            json={"id": event_id, "summary": summary[:300],
                  "description": "Synthetic recruiting portfolio demonstration. Owned test accounts only.",
                  "start": {"dateTime": start, "timeZone": timezone},
                  "end": {"dateTime": end, "timeZone": timezone},
                  "attendees": [{"email": email} for email in normalized],
                  "guestsCanInviteOthers": False, "guestsCanModify": False})
        if response.status_code == 409:
            existing = self._authorized_request(tokens, "GET", url + "/" + event_id)
            if existing.status_code == 200:
                event = self._json(existing, "Calendar returned an unreadable booking receipt. Reconcile before trying again.", ambiguous=True)
                if not event.get("id"):
                    raise ServiceError("Calendar returned no booking ID. Reconcile before trying again.", ambiguous=True)
                if event.get("status") == "cancelled":
                    raise ServiceError("The existing interview was cancelled. Create a new scheduling action.")
                return {"id": event["id"], "status": "sent", "htmlLink": event.get("htmlLink"), "reconciled": True}
            raise ServiceError("Calendar reports an existing interview but its receipt is unavailable. Reconcile before retrying.",
                               ambiguous=True)
        if response.status_code >= 500:
            raise ServiceError("Calendar booking is uncertain. Reconcile the saved event ID before retrying.", ambiguous=True)
        if response.status_code >= 300:
            raise ServiceError("Google Calendar rejected the interview. Reconnect and check your calendar permissions.",
                               retryable=response.status_code == 429)
        event = self._json(response, "Calendar returned an unreadable booking receipt. Reconcile before trying again.", ambiguous=True)
        if not event.get("id"):
            raise ServiceError("Calendar returned no booking receipt. Reconcile before trying again.", ambiguous=True)
        return {"id": event["id"], "status": "sent", "htmlLink": event.get("htmlLink")}
