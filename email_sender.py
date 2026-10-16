import re

import requests


RESEND_API_URL = "https://api.resend.com/emails"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def send_resend_email(
    *,
    api_key: str,
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    recipient_consented: bool,
    approved: bool,
) -> str:
    """Send one reviewed email through Resend after explicit consent and approval."""
    if not recipient_consented:
        raise ValueError("Do not email a recipient without their consent to this contact.")
    if not approved:
        raise ValueError("Review and approve the exact email before sending.")
    if not api_key.strip():
        raise ValueError("Enter a Resend API key.")
    if not EMAIL_PATTERN.fullmatch(sender.strip()):
        raise ValueError("Enter a valid verified sender email address.")
    if not EMAIL_PATTERN.fullmatch(recipient.strip()):
        raise ValueError("Enter a valid recipient email address.")
    if not subject.strip() or not body.strip():
        raise ValueError("Email subject and body must not be empty.")

    try:
        response = requests.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {api_key.strip()}",
                "Content-Type": "application/json",
            },
            json={
                "from": sender.strip(),
                "to": [recipient.strip()],
                "subject": subject.strip(),
                "text": body.strip(),
            },
            timeout=20,
        )
    except requests.RequestException:
        raise RuntimeError("Resend request failed; check your connection and try again.") from None
    if not response.ok:
        raise RuntimeError(f"Resend returned HTTP {response.status_code}.")
    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError:
        raise RuntimeError("Resend returned an unexpected response.") from None
    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
        raise RuntimeError("Resend did not confirm the email with a message ID.")
    return data["id"]
