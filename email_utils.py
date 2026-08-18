import os
import re
import time
from datetime import datetime
from html import escape
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv()


MICROSOFT_TENANT_ID = os.getenv("MICROSOFT_TENANT_ID") or os.getenv("MICROSOFT_ENTRA_TENANT_ID")
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID") or os.getenv("MICROSOFT_ENTRA_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_OVERRIDE_TO = os.getenv("EMAIL_OVERRIDE_TO", "")
EDGE_PORTAL_URL = "http://edge.nicesoftwaresolutions.com/"
GRAPH_BATCH_SIZE = 20
GRAPH_RETRY_STATUSES = {429, 503, 504}


def format_notification_email_body(body: str) -> str:
    return (
        "Hi,\n\n"
        f"{body}\n\n"
        f"Please log in to the EDGE portal for more details and any required actions: {EDGE_PORTAL_URL}\n\n"
        "Regards,\n"
        "EDGE"
    )


def format_notification_email_html(body: str) -> str:
    body_html = escape(body).replace("\n", "<br>")
    body_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body_html)
    edge_link = f'<a href="{EDGE_PORTAL_URL}">EDGE</a>'
    return (
        "<p>Hi,</p>"
        f"<p>{body_html}</p>"
        f"<p>Please log in to the {edge_link} portal for more details and any required actions.</p>"
        "<p>Regards,<br>EDGE</p>"
    )


def format_password_reset_email_body(reset_link: str, expires_minutes: int = 10) -> str:
    return (
        "Hi,\n\n"
        "We received a request to reset your EDGE password.\n\n"
        f"Open this link to set a new password: {reset_link}\n\n"
        f"This link will expire in {expires_minutes} minutes. If you did not request this, please ignore this email.\n\n"
        "Regards,\n"
        "EDGE"
    )


def format_password_reset_email_html(reset_link: str, expires_minutes: int = 10) -> str:
    safe_link = escape(reset_link, quote=True)
    return (
        "<p>Hi,</p>"
        "<p>We received a request to reset your EDGE password.</p>"
        f'<p><a href="{safe_link}">Reset your EDGE password</a></p>'
        f"<p>This link will expire in {expires_minutes} minutes. If you did not request this, please ignore this email.</p>"
        "<p>Regards,<br>EDGE</p>"
    )


def _graph_access_token():
    if not MICROSOFT_TENANT_ID or not MICROSOFT_CLIENT_ID or not MICROSOFT_CLIENT_SECRET:
        print("Microsoft Graph email credentials are not configured; skipping email notification")
        return None

    token_url = f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}/oauth2/v2.0/token"
    response = requests.post(
        token_url,
        data={
            "client_id": MICROSOFT_CLIENT_ID,
            "client_secret": MICROSOFT_CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _graph_email_payload(to_email, subject, html_content):
    recipient = EMAIL_OVERRIDE_TO or to_email
    if not recipient:
        return None

    return {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": html_content,
            },
            "toRecipients": [
                {"emailAddress": {"address": recipient}},
            ],
        },
        "saveToSentItems": False,
    }


def _send_graph_email(to_email, subject, html_content, text_content=None):
    if not EMAIL_FROM:
        print("EMAIL_FROM is not configured; skipping email notification")
        return False

    payload = _graph_email_payload(to_email, subject, html_content)
    if not payload:
        return False

    access_token = _graph_access_token()
    if not access_token:
        return False

    recipient = EMAIL_OVERRIDE_TO or to_email
    graph_url = f"https://graph.microsoft.com/v1.0/users/{quote(EMAIL_FROM)}/sendMail"
    response = requests.post(
        graph_url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    print(f"Graph email accepted for {recipient}: {subject}")
    return True


def send_notification_email(to_email, subject, body):
    return _send_graph_email(
        to_email,
        subject,
        format_notification_email_html(body),
        format_notification_email_body(body),
    )


def _retry_after_seconds(response):
    retry_after = response.headers.get("Retry-After")
    if not retry_after:
        return 2
    try:
        return min(max(int(retry_after), 1), 30)
    except ValueError:
        return 2


def _post_graph_batch(access_token, requests_payload):
    response = requests.post(
        "https://graph.microsoft.com/v1.0/$batch",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"requests": requests_payload},
        timeout=60,
    )
    if response.status_code in GRAPH_RETRY_STATUSES:
        time.sleep(_retry_after_seconds(response))
        response = requests.post(
            "https://graph.microsoft.com/v1.0/$batch",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"requests": requests_payload},
            timeout=60,
        )
    response.raise_for_status()
    return response.json().get("responses", [])


def _batch_request_for_payload(request_id, payload):
    message = _graph_email_payload(
        payload.get("to_email"),
        payload.get("title"),
        format_notification_email_html(payload.get("body", "")),
    )
    if not message:
        return None
    return {
        "id": request_id,
        "method": "POST",
        "url": f"/users/{quote(EMAIL_FROM)}/sendMail",
        "headers": {"Content-Type": "application/json"},
        "body": message,
    }


def _log_failed_batch_response(notification_id, response):
    status = response.get("status")
    body = response.get("body") or {}
    error = body.get("error", body)
    print(f"Graph email failed for {notification_id}: status={status} error={error}")


def _batch_retry_after_seconds(responses):
    retry_after_values = []
    for response in responses:
        headers = response.get("headers") or {}
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if retry_after:
            try:
                retry_after_values.append(int(retry_after))
            except ValueError:
                pass
    if not retry_after_values:
        return 2
    return min(max(max(retry_after_values), 1), 30)


def send_notification_email_batch(payloads):
    if not payloads:
        return []
    if not EMAIL_FROM:
        print("EMAIL_FROM is not configured; skipping email notifications")
        return []

    access_token = _graph_access_token()
    if not access_token:
        return []

    sent_ids = []
    for start in range(0, len(payloads), GRAPH_BATCH_SIZE):
        chunk = payloads[start:start + GRAPH_BATCH_SIZE]
        request_payloads = {}
        requests_payload = []

        for index, payload in enumerate(chunk, start=1):
            notification_id = payload.get("notification_id")
            request_id = str(notification_id or index)
            batch_request = _batch_request_for_payload(request_id, payload)
            if batch_request:
                requests_payload.append(batch_request)
                request_payloads[request_id] = payload

        if not requests_payload:
            continue

        try:
            responses = _post_graph_batch(access_token, requests_payload)
        except Exception as exc:
            print(f"Graph email batch failed for {len(requests_payload)} notifications: {exc}")
            continue

        retry_requests = []
        retry_payloads = {}
        request_by_id = {request["id"]: request for request in requests_payload}
        for response in responses:
            request_id = response.get("id")
            payload = request_payloads.get(request_id)
            notification_id = payload.get("notification_id") if payload else None
            status = response.get("status") or 0
            if 200 <= status < 300:
                if notification_id:
                    sent_ids.append(notification_id)
            elif status in GRAPH_RETRY_STATUSES and request_id in request_by_id:
                retry_requests.append(request_by_id[request_id])
                retry_payloads[request_id] = payload
            else:
                _log_failed_batch_response(notification_id, response)

        if not retry_requests:
            continue

        time.sleep(_batch_retry_after_seconds(responses))
        try:
            retry_responses = _post_graph_batch(access_token, retry_requests)
        except Exception as exc:
            print(f"Graph email batch retry failed for {len(retry_requests)} notifications: {exc}")
            continue

        for response in retry_responses:
            request_id = response.get("id")
            payload = retry_payloads.get(request_id)
            notification_id = payload.get("notification_id") if payload else None
            status = response.get("status") or 0
            if 200 <= status < 300:
                if notification_id:
                    sent_ids.append(notification_id)
            else:
                _log_failed_batch_response(notification_id, response)

    return sent_ids


def send_password_reset_email(to_email, reset_link, expires_minutes=10):
    return _send_graph_email(
        to_email,
        "EDGE password reset",
        format_password_reset_email_html(reset_link, expires_minutes),
        format_password_reset_email_body(reset_link, expires_minutes),
    )


def mark_email_sent(notification):
    notification.email_sent_at = datetime.utcnow()
