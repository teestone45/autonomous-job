import hmac
import os
import secrets
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from openai import OpenAIError
from werkzeug.exceptions import BadRequest

from dotenv import load_dotenv
from ai_services import (
    analyze_resume,
    generate_application_email,
    generate_improved_resume,
    generate_service_offer,
    generate_tailored_resume,
)
from email_sender import send_resend_email
from job_matcher import calculate_match_score
from job_search import search_jobs
from job_tailor import generate_cover_letter
from main import _job_identity, _role_matches_job


if not os.environ.get("VERCEL"):
    load_dotenv()

app = Flask(__name__, static_folder="public", static_url_path="")
app.config.update(
    SECRET_KEY=os.environ.get("APP_SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=128 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=bool(os.environ.get("VERCEL")),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=4),
)


def _configured() -> bool:
    password = os.environ.get("APP_PASSWORD", "")
    secret = os.environ.get("APP_SECRET_KEY", "")
    return len(password) >= 16 and len(secret) >= 32


def _csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@app.before_request
def protect_requests():
    if request.endpoint in {"static", "health"}:
        return None
    if not _configured():
        if request.path.startswith("/api/"):
            return jsonify(error="Set APP_PASSWORD and APP_SECRET_KEY in Vercel settings."), 503
        return render_template("index.html", configured=False, authenticated=False), 503
    if request.method == "POST":
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf", "")
        expected = session.get("csrf", "")
        if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
            return jsonify(error="Your session expired. Refresh the page and try again."), 403
    if request.endpoint in {"index", "login"}:
        return None
    if not session.get("authenticated"):
        return jsonify(error="Sign in before using this feature."), 401
    return None


@app.after_request
def protect_responses(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'"
    )
    return response


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/")
def index():
    return render_template(
        "index.html",
        configured=True,
        authenticated=bool(session.get("authenticated")),
        csrf=_csrf_token(),
    )


@app.post("/login")
def login():
    password = request.form.get("password", "")
    if not hmac.compare_digest(
        password.encode("utf-8"), os.environ["APP_PASSWORD"].encode("utf-8")
    ):
        return render_template(
            "index.html", configured=True, authenticated=False,
            csrf=_csrf_token(), error="Incorrect app password.",
        ), 401
    session.clear()
    session["authenticated"] = True
    session.permanent = True
    _csrf_token()
    return redirect(url_for("index"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


def _data() -> dict[str, Any]:
    data = request.get_json()
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object.")
    return data


def _text(data: dict[str, Any], field: str, limit: int = 10000, optional: bool = False) -> str:
    value = data.get(field, "")
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{field} must be text of at most {limit} characters.")
    if not optional and not value.strip():
        raise ValueError(f"Enter {field.replace('_', ' ')}.")
    return value.strip()


def _consent(data: dict[str, Any], field: str) -> None:
    if data.get(field) is not True:
        raise ValueError(f"Confirm {field.replace('_', ' ')} before continuing.")


def _review(data: dict[str, Any]) -> dict[str, Any]:
    review = data.get("review")
    if not isinstance(review, dict):
        raise ValueError("Generate a resume review first.")
    summary = _text(review, "summary", 5000)
    issues = review.get("issues")
    if not isinstance(issues, list) or not 1 <= len(issues) <= 6:
        raise ValueError("The review must contain 1 to 6 improvement opportunities.")
    cleaned = []
    for issue in issues:
        if not isinstance(issue, dict):
            raise ValueError("Invalid review issue.")
        cleaned.append({
            "issue": _text(issue, "issue", 3000),
            "recommendation": _text(issue, "recommendation", 3000),
        })
    return {"summary": summary, "issues": cleaned}


@app.errorhandler(ValueError)
def invalid_input(exc):
    return jsonify(error=str(exc)), 400


@app.errorhandler(BadRequest)
def bad_json(exc):
    return jsonify(error="The request was not valid JSON."), 400


@app.errorhandler(OpenAIError)
def ai_error(exc):
    app.logger.warning("AI request failed (%s)", type(exc).__name__)
    return jsonify(error="The AI provider could not complete the request. Check your key, quota, and try again."), 502


@app.errorhandler(RuntimeError)
def provider_error(exc):
    app.logger.warning("Provider request failed (%s)", type(exc).__name__)
    return jsonify(error=str(exc)), 502


@app.errorhandler(413)
def too_large(exc):
    return jsonify(error="This request is too large. Shorten the resume or message."), 413


@app.post("/api/jobs")
def jobs():
    data = _data()
    roles = _text(data, "roles", 500)
    role_list = [role.strip() for role in roles.split(",") if role.strip()]
    if not role_list:
        raise ValueError("Enter at least one target role.")
    found = {}
    for job in search_jobs():
        if any(_role_matches_job(role, job) for role in role_list):
            url = str(job.get("url", ""))
            if urlsplit(url).scheme not in {"http", "https"}:
                continue
            found.setdefault(_job_identity(job), job)
    return jsonify(jobs=list(found.values())[:50])


@app.post("/api/score")
def score():
    data = _data()
    result = calculate_match_score(
        _text(data, "description", 20000),
        _text(data, "resume"),
        _text(data, "title", 500),
        _text(data, "company", 500),
        api_key=_text(data, "api_key", 1000),
    )
    return jsonify(result)


@app.post("/api/cover-letter")
def cover_letter():
    data = _data()
    letter = generate_cover_letter(
        _text(data, "description", 20000),
        _text(data, "resume"),
        _text(data, "title", 500),
        _text(data, "company", 500),
        _text(data, "name", 200),
        api_key=_text(data, "api_key", 1000),
    )
    email = generate_application_email(
        candidate_name=data["name"], job_title=data["title"],
        company=data["company"], cover_letter=letter,
    )
    return jsonify(letter=letter, email=email)


@app.post("/api/tailored-resume")
def tailored_resume():
    data = _data()
    resume = generate_tailored_resume(
        _text(data, "resume"),
        _text(data, "description", 20000),
        _text(data, "title", 500),
        _text(data, "company", 500),
        api_key=_text(data, "api_key", 1000),
    )
    return jsonify(resume=resume)


@app.post("/api/review")
def review():
    data = _data()
    _consent(data, "client_consented")
    return jsonify(review=analyze_resume(
        _text(data, "resume"), api_key=_text(data, "api_key", 1000),
    ))


@app.post("/api/offer")
def offer():
    data = _data()
    _consent(data, "client_consented")
    email = generate_service_offer(
        _text(data, "name", 200),
        _review(data),
        _text(data, "service_description", 3000),
        _text(data, "price", 200, optional=True),
        _text(data, "payment_instructions", 1000, optional=True),
        api_key=_text(data, "api_key", 1000),
    )
    return jsonify(email=email)


@app.post("/api/improve")
def improve():
    data = _data()
    _consent(data, "client_consented")
    _consent(data, "payment_verified")
    resume = generate_improved_resume(
        _text(data, "resume"),
        _review(data),
        _text(data, "service_description", 3000),
        payment_verified=True,
        api_key=_text(data, "api_key", 1000),
    )
    return jsonify(resume=resume)


@app.post("/api/send")
def send():
    data = _data()
    _consent(data, "recipient_consented")
    _consent(data, "approved")
    kind = data.get("kind")
    if kind == "application":
        _consent(data, "accepts_email")
    elif kind == "service":
        _consent(data, "client_consented")
    else:
        raise ValueError("Select an application or service email.")
    message_id = send_resend_email(
        api_key=_text(data, "resend_key", 1000),
        sender=_text(data, "sender", 320),
        recipient=_text(data, "recipient", 320),
        subject=_text(data, "subject", 500),
        body=_text(data, "body", 30000),
        recipient_consented=True, approved=True,
        resume_text=_text(data, "attachment", optional=True),
    )
    return jsonify(id=message_id)
