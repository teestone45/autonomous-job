import os
import unittest
from unittest.mock import patch

from app import app


class HostedAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {
            "APP_PASSWORD": "a-private-password-123",
            "APP_SECRET_KEY": "a-test-secret-at-least-32-characters-long",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        app.config.update(TESTING=True, SECRET_KEY="test-signing-key")
        self.client = app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as session:
            self.csrf = session["csrf"]

    def login(self) -> None:
        response = self.client.post("/login", data={
            "csrf": self.csrf, "password": os.environ["APP_PASSWORD"],
        })
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.csrf = session["csrf"]

    def post(self, path, data):
        return self.client.post(
            f"/api/{path}", json=data, headers={"X-CSRF-Token": self.csrf},
        )

    def test_unconfigured_deployment_is_fail_closed(self) -> None:
        with patch.dict(os.environ, {"APP_PASSWORD": "", "APP_SECRET_KEY": ""}):
            response = self.client.get("/")
            self.assertEqual(response.status_code, 503)
            self.assertIn(b"Finish private access setup", response.data)
            self.assertEqual(self.post("jobs", {"roles": "Engineer"}).status_code, 503)
        self.assertEqual(self.client.get("/health").json, {"status": "ok"})

    def test_authentication_and_csrf_are_required(self) -> None:
        self.assertEqual(self.post("jobs", {"roles": "Engineer"}).status_code, 401)
        response = self.client.post("/login", data={"password": os.environ["APP_PASSWORD"]})
        self.assertEqual(response.status_code, 403)
        self.login()
        self.assertEqual(self.client.post("/api/jobs", json={}).status_code, 403)
        page = self.client.get("/")
        self.assertIn(b"Find jobs", page.data)
        self.assertIn(b"/app.js", page.data)
        self.assertIn("frame-ancestors 'none'", page.headers["Content-Security-Policy"])
        self.assertEqual(page.headers["Cache-Control"], "no-store")
        for path in ("/app.js", "/style.css"):
            with self.client.get(path) as asset:
                self.assertEqual(asset.status_code, 200)

    @patch("app.search_jobs")
    def test_free_search_is_stateless_and_deduplicated(self, search) -> None:
        search.return_value = [
            {"title": "Automation Engineer", "tags": ["ai"], "url": "https://remoteok.com/job/1"},
            {"title": "Automation Engineer", "tags": ["ai"], "url": "https://remoteok.com/job/1"},
            {"title": "Automation Engineer", "tags": ["ai"], "url": "javascript:alert(1)"},
            {"title": "Writer", "tags": [], "url": "https://remoteok.com/job/2"},
        ]
        self.login()
        response = self.post("jobs", {"roles": "AI Automation Engineer"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["jobs"]), 1)
        search.assert_called_once_with()

    @patch("app.calculate_match_score")
    def test_api_key_is_passed_per_request_without_changing_environment(self, score) -> None:
        self.login()
        score.return_value = {"score": 80, "reasoning": "Relevant skills"}
        previous = os.environ.get("OPENAI_API_KEY")
        response = self.post("score", {
            "api_key": "request-only-key", "resume": "Python",
            "description": "Python role", "title": "Engineer", "company": "Example",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["score"], 80)
        self.assertEqual(score.call_args.kwargs["api_key"], "request-only-key")
        self.assertEqual(os.environ.get("OPENAI_API_KEY"), previous)

    @patch("app.analyze_resume")
    @patch("app.generate_improved_resume")
    def test_review_consent_and_manual_payment_gates(self, improve, review) -> None:
        self.login()
        self.assertEqual(self.post("review", {
            "resume": "Resume", "api_key": "key", "client_consented": "yes",
        }).status_code, 400)
        self.assertEqual(self.post("improve", {
            "client_consented": True, "payment_verified": False,
        }).status_code, 400)
        review.assert_not_called()
        improve.assert_not_called()

    @patch("app.send_resend_email")
    def test_send_requires_exact_boolean_approval_and_application_route(self, send) -> None:
        self.login()
        base = {
            "recipient_consented": True, "approved": True, "kind": "application",
            "resend_key": "key", "sender": "owner@example.com",
            "recipient": "hiring@example.com", "subject": "Application",
            "body": "Reviewed message", "attachment": "Reviewed resume",
        }
        self.assertEqual(self.post("send", base).status_code, 400)
        self.assertEqual(self.post("send", {**base, "accepts_email": True, "approved": "true"}).status_code, 400)
        send.assert_not_called()
        send.return_value = "message-1"
        response = self.post("send", {**base, "accepts_email": True})
        self.assertEqual(response.json, {"id": "message-1"})
        self.assertEqual(send.call_args.kwargs["resume_text"], "Reviewed resume")

    @patch("app.analyze_resume")
    def test_provider_errors_are_visible_and_do_not_expose_keys(self, review) -> None:
        self.login()
        review.side_effect = RuntimeError("The resume model returned an empty draft.")
        response = self.post("review", {
            "client_consented": True, "resume": "Resume", "api_key": "private-key",
        })
        self.assertEqual(response.status_code, 502)
        self.assertIn("empty draft", response.json["error"])
        self.assertNotIn(b"private-key", response.data)

    def test_invalid_json_and_body_limits(self) -> None:
        self.login()
        self.assertEqual(self.post("jobs", []).status_code, 400)
        response = self.client.post(
            "/api/jobs", data="{", content_type="application/json",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.post("jobs", {"roles": "x" * 501}).status_code, 400)

    def test_logout_removes_authorization(self) -> None:
        self.login()
        self.client.post("/logout", data={"csrf": self.csrf})
        self.client.get("/")
        with self.client.session_transaction() as session:
            self.csrf = session["csrf"]
        self.assertEqual(self.post("jobs", {"roles": "Engineer"}).status_code, 401)

    @patch("app.generate_cover_letter", return_value="A truthful cover letter")
    @patch("app.generate_tailored_resume", return_value="A truthful tailored resume")
    def test_application_materials_are_returned_without_saving_files(self, tailor, cover) -> None:
        self.login()
        payload = {
            "api_key": "request-key", "name": "Candidate", "resume": "Python experience",
            "description": "Python role", "title": "Engineer", "company": "Example",
        }
        response = self.post("tailored-resume", payload)
        self.assertEqual(response.json, {"resume": "A truthful tailored resume"})
        response = self.post("cover-letter", payload)
        self.assertEqual(response.json["letter"], "A truthful cover letter")
        self.assertIn("Candidate", response.json["email"]["subject"])
        self.assertEqual(cover.call_args.kwargs["api_key"], "request-key")
        self.assertEqual(tailor.call_args.kwargs["api_key"], "request-key")

    @patch("app.generate_service_offer")
    @patch("app.generate_improved_resume", return_value="Improved draft")
    @patch("app.analyze_resume")
    def test_opted_in_service_review_offer_and_paid_delivery(self, analyze, improve, offer) -> None:
        self.login()
        review = {
            "summary": "Resume has unclear outcomes.",
            "issues": [{"issue": "Unclear outcomes", "recommendation": "Clarify real outcomes"}],
        }
        analyze.return_value = review
        payload = {
            "client_consented": True, "api_key": "key", "resume": "Source resume",
            "name": "Client", "service_description": "Resume improvement",
        }
        self.assertEqual(self.post("review", payload).json["review"], review)
        offer.return_value = {"subject": "Optional help", "body": "An optional service"}
        payload["review"] = review
        self.assertEqual(self.post("offer", payload).json["email"]["subject"], "Optional help")
        self.assertEqual(self.post("improve", {
            **payload, "payment_verified": True,
        }).json["resume"], "Improved draft")
        self.assertIs(improve.call_args.kwargs["payment_verified"], True)
        self.assertEqual(improve.call_args.kwargs["api_key"], "key")


if __name__ == "__main__":
    unittest.main()
