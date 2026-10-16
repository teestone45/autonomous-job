import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import streamlit as st
from openai import OpenAIError

from ai_services import (
    analyze_resume,
    generate_application_email,
    generate_improved_resume,
    generate_service_offer,
    generate_tailored_resume,
)
from config import AppConfig, Candidate, MatchingPreferences, SearchPreferences
from email_sender import send_resend_email
from job_search import REMOTEOK_URL
from main import run_pipeline


st.set_page_config(page_title="Job Scout", page_icon="🔎", layout="wide")
st.title("Job Scout")
st.caption(
    "AI-assisted resume and job-search tools. Emails are drafts until you review and "
    "approve them. Never contact someone who has not agreed to be contacted."
)
st.markdown(f"Worldwide remote listings provided by [Remote OK]({REMOTEOK_URL}).")

with st.sidebar:
    st.header("Private local setup")
    st.warning(
        "This is a single-user local app, not ready for public hosting. "
        "Do not expose it publicly until authentication, secure data handling, and "
        "per-customer consent controls are implemented."
    )
    openai_api_key = st.text_input(
        "OpenAI API key",
        type="password",
        key="openai_api_key",
    )
    resend_api_key = st.text_input(
        "Resend API key",
        type="password",
        key="resend_api_key",
    )
    sender_email = st.text_input(
        "Verified sender email",
        key="resend_sender_email",
        help="Resend requires a verified sending domain/address.",
    )
    st.caption("Keys are held in this local app session and are not saved to project files.")


def _safe_key(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", value)[:80]


@contextmanager
def _openai_environment() -> Iterator[None]:
    previous_key = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = openai_api_key
    try:
        yield
    finally:
        if previous_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = previous_key


def _send_controls(
    *,
    prefix: str,
    default_recipient: str = "",
    consent_text: str,
) -> None:
    recipient = st.text_input(
        "Recipient email",
        value=default_recipient,
        key=f"{prefix}-recipient",
    )
    recipient_consented = st.checkbox(
        consent_text,
        key=f"{prefix}-consent",
    )
    approved = st.checkbox(
        "I reviewed the exact recipient, subject, and message above and approve sending it.",
        key=f"{prefix}-approval",
    )
    message_id = st.session_state.get(f"{prefix}-message-id")
    send_clicked = st.button(
        "Send approved email",
        key=f"{prefix}-send",
        disabled=not (recipient_consented and approved) or bool(message_id),
    )
    if message_id:
        st.success(f"Already sent. Resend message ID: {message_id}")
    if send_clicked:
        subject = st.session_state.get(f"{prefix}-subject", "")
        body = st.session_state.get(f"{prefix}-body", "")
        try:
            message_id = send_resend_email(
                api_key=resend_api_key,
                sender=sender_email,
                recipient=recipient,
                subject=subject,
                body=body,
                recipient_consented=recipient_consented,
                approved=approved,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            st.error(f"Email was not sent: {exc}")
        else:
            st.session_state[f"{prefix}-message-id"] = message_id
            st.success(f"Email sent. Resend message ID: {message_id}")


def _job_card(path_string: str, resume_text: str, candidate_name: str) -> None:
    path = Path(path_string)
    job_data: dict[str, Any] = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    job = job_data["job"]
    match = job_data["match"]
    key = _safe_key(path.stem)
    title = str(job.get("title", "Untitled role"))
    company = str(job.get("company", "Unknown"))
    with st.expander(f"{title} — {company} ({match['score']}/100)", expanded=False):
        st.markdown(f"**Why it matched:** {match['reasoning']}")
        st.markdown(f"**Listing:** [{title}]({job.get('url', '')})")
        st.markdown("**Cover letter draft**")
        st.write(job_data["cover_letter"])

        if st.button(
            "Generate tailored resume and application email",
            key=f"{key}-generate",
            disabled=not openai_api_key,
        ):
            try:
                with _openai_environment():
                    with st.spinner("Preparing a fact-checked resume and email draft..."):
                        tailored_resume = generate_tailored_resume(
                            resume_text=resume_text,
                            job_description=str(job.get("description", "")),
                            job_title=title,
                            company=company,
                        )
                        application_email = generate_application_email(
                            candidate_name=candidate_name,
                            job_title=title,
                            company=company,
                            cover_letter=job_data["cover_letter"],
                        )
            except (OpenAIError, OSError, RuntimeError, ValueError) as exc:
                st.error(f"Could not create the application materials: {exc}")
            else:
                st.session_state[f"{key}-resume"] = tailored_resume
                st.session_state[f"{key}-subject"] = application_email["subject"]
                st.session_state[f"{key}-body"] = application_email["body"]
                st.rerun()

        resume_state_key = f"{key}-resume"
        if resume_state_key in st.session_state:
            st.text_area(
                "Tailored resume (review and edit before using)",
                key=resume_state_key,
                height=300,
            )
            st.download_button(
                "Download tailored resume",
                data=st.session_state[resume_state_key],
                file_name=f"{key}-resume.txt",
                mime="text/plain",
                key=f"{key}-resume-download",
            )
            st.text_input("Application email subject", key=f"{key}-subject")
            st.text_area("Application email body", key=f"{key}-body", height=220)
            listing_accepts_email = st.checkbox(
                "I verified that this job listing accepts applications by email.",
                key=f"{key}-email-route",
            )
            if listing_accepts_email:
                _send_controls(
                    prefix=f"{key}-application",
                    consent_text=(
                        "The candidate authorized me to send this application email "
                        "to the listed employer contact."
                    ),
                )
            else:
                st.caption("Email sending stays disabled until you verify the listing's application route.")


applicant_tab, service_tab = st.tabs(
    ["Job seeker: tailor and apply", "Resume service: review and offer"]
)

with applicant_tab:
    st.subheader("Find jobs and tailor application materials")
    st.info(
        "Searches Remote OK's recent worldwide remote listings. Employers may still "
        "restrict eligible countries. You approve each application email before it sends."
    )
    with st.form("job_search"):
        candidate_name = st.text_input("Your name", key="applicant-name")
        resume_text = st.text_area(
            "Your resume",
            height=220,
            key="applicant-resume",
            help="The AI may reorganize and rewrite your experience but must not invent facts.",
        )
        target_roles_input = st.text_input(
            "Target roles (comma-separated)",
            value="AI Automation Engineer, Prompt Engineer, Full-Stack Developer",
            key="applicant-roles",
        )
        threshold = st.slider(
            "Minimum match score", min_value=0, max_value=100, value=75, key="applicant-threshold"
        )
        max_jobs = st.number_input(
            "Maximum cover-letter drafts",
            min_value=1,
            max_value=50,
            value=10,
            key="applicant-max-jobs",
        )
        search_submitted = st.form_submit_button(
            "Find matching jobs",
            type="primary",
            use_container_width=True,
            disabled=not openai_api_key,
        )

    if search_submitted:
        roles = [role.strip() for role in target_roles_input.split(",") if role.strip()]
        if not candidate_name.strip() or not resume_text.strip():
            st.error("Enter your name and resume text.")
        elif not roles:
            st.error("Enter at least one target role.")
        else:
            config = AppConfig(
                candidate=Candidate(name=candidate_name.strip(), resume_text=resume_text.strip()),
                search_preferences=SearchPreferences(target_roles=roles),
                matching=MatchingPreferences(
                    min_score_threshold=threshold,
                    max_jobs_per_run=int(max_jobs),
                ),
            )
            try:
                with _openai_environment():
                    with st.spinner("Searching Remote OK and scoring role matches..."):
                        paths = run_pipeline(config, Path("output"))
            except (OpenAIError, OSError, RuntimeError, ValueError) as exc:
                st.error(f"Job search could not be completed: {exc}")
            else:
                for old_path in st.session_state.get("applicant-paths", []):
                    old_key = _safe_key(Path(old_path).stem)
                    for suffix in (
                        "resume",
                        "subject",
                        "body",
                        "recipient",
                        "consent",
                        "approval",
                        "email-route",
                        "message-id",
                    ):
                        st.session_state.pop(f"{old_key}-{suffix}", None)
                    for suffix in ("generate", "resume-download", "application-send"):
                        st.session_state.pop(f"{old_key}-{suffix}", None)
                st.session_state["applicant-paths"] = [str(path) for path in paths]
                st.session_state["applicant-name-result"] = candidate_name.strip()
                st.session_state["applicant-resume-result"] = resume_text.strip()
                st.success(f"Found {len(paths)} role(s) meeting your match threshold.")

    for saved_path in st.session_state.get("applicant-paths", []):
        _job_card(
            saved_path,
            st.session_state["applicant-resume-result"],
            st.session_state["applicant-name-result"],
        )

with service_tab:
    st.subheader("Review an opted-in job seeker's resume")
    st.info(
        "This creates a private review and optional paid-service offer. Only enter a person's "
        "resume if they asked for the review and agreed to email follow-up. The AI must not "
        "invent qualifications or guarantee employment."
    )
    with st.form("service_review"):
        client_name = st.text_input("Client name", key="service-name")
        client_email = st.text_input("Client email", key="service-email")
        client_resume = st.text_area(
            "Client resume",
            height=220,
            key="service-resume",
        )
        service_description = st.text_area(
            "What your paid service includes",
            key="service-description",
            help="Describe the real service. Do not promise a job or guaranteed results.",
        )
        service_price = st.text_input(
            "Price and currency (optional)",
            key="service-price",
        )
        payment_instructions = st.text_input(
            "Payment instructions or link (optional)",
            key="service-payment",
        )
        client_consented = st.checkbox(
            "This person requested the resume review and explicitly agreed to receive email follow-up.",
            key="service-consent",
        )
        review_submitted = st.form_submit_button(
            "Analyze resume and prepare an offer draft",
            type="primary",
            disabled=not openai_api_key,
        )

    if review_submitted:
        if not client_name.strip() or not client_email.strip() or not client_resume.strip():
            st.error("Enter the client's name, email, and resume.")
        elif not service_description.strip():
            st.error("Describe the paid service before generating an offer.")
        elif not client_consented:
            st.error("Do not review or email this person without their explicit consent.")
        else:
            try:
                with _openai_environment():
                    with st.spinner("Reviewing the resume and drafting the optional offer..."):
                        review = analyze_resume(client_resume.strip())
                        offer = generate_service_offer(
                            candidate_name=client_name.strip(),
                            review=review,
                            service_description=service_description.strip(),
                            price=service_price.strip(),
                            payment_instructions=payment_instructions.strip(),
                        )
            except (OpenAIError, OSError, RuntimeError, ValueError) as exc:
                st.error(f"Resume review could not be completed: {exc}")
            else:
                st.session_state["service-review-result"] = review
                st.session_state["service-offer-result"] = offer
                st.session_state["service-client-name-result"] = client_name.strip()
                st.session_state["service-client-email-result"] = client_email.strip()
                st.session_state["service-client-resume-result"] = client_resume.strip()
                st.session_state["service-description-result"] = service_description.strip()
                st.session_state["service-client-consent-result"] = client_consented
                st.session_state["service-payment-confirmed"] = False
                st.session_state.pop("service-improved-resume", None)
                st.session_state["service-offer-subject"] = offer["subject"]
                st.session_state["service-offer-body"] = offer["body"]
                st.session_state["service-offer-recipient"] = client_email.strip()
                st.session_state["service-offer-consent"] = False
                st.session_state["service-offer-approval"] = False
                st.session_state.pop("service-offer-message-id", None)

    review = st.session_state.get("service-review-result")
    if review:
        st.markdown("#### Private review")
        st.write(review["summary"])
        for index, issue in enumerate(review["issues"], start=1):
            st.markdown(f"**{index}. {issue['issue']}**")
            st.write(issue["recommendation"])

        offer = st.session_state["service-offer-result"]
        st.markdown("#### Optional service email draft")
        st.text_input("Offer email subject", value=offer["subject"], key="service-offer-subject")
        st.text_area("Offer email body", value=offer["body"], key="service-offer-body", height=220)
        _send_controls(
            prefix="service-offer",
            default_recipient=st.session_state["service-client-email-result"],
            consent_text=(
                "I confirm this person opted in to this resume review and email follow-up."
            ),
        )

        st.markdown("#### Paid service delivery")
        payment_confirmed = st.checkbox(
            "I manually verified that payment for this service was received.",
            key="service-payment-confirmed",
        )
        if payment_confirmed and st.button(
            "Prepare the paid resume improvement",
            key="service-generate-paid",
            disabled=not openai_api_key,
        ):
            try:
                with _openai_environment():
                    with st.spinner("Preparing a fact-grounded resume improvement..."):
                        improved_resume = generate_improved_resume(
                            resume_text=st.session_state["service-client-resume-result"],
                            review=review,
                            service_description=st.session_state["service-description-result"],
                            payment_verified=True,
                        )
            except (OpenAIError, OSError, RuntimeError, ValueError) as exc:
                st.error(f"Could not prepare the paid resume service: {exc}")
            else:
                st.session_state["service-improved-resume"] = improved_resume
                st.rerun()

        improved_resume = st.session_state.get("service-improved-resume")
        if improved_resume and payment_confirmed:
            st.text_area(
                "Improved resume (review for accuracy with the client)",
                value=improved_resume,
                height=320,
                key="service-improved-resume-display",
            )
            st.download_button(
                "Download improved resume",
                data=improved_resume,
                file_name=f"{_safe_key(st.session_state['service-client-name-result'])}-resume.txt",
                mime="text/plain",
            )
