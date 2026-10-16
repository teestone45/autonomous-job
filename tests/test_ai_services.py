import unittest
import base64
from unittest.mock import patch

from ai_services import generate_application_email, generate_improved_resume
from email_sender import send_resend_email


class ApplicationEmailTests(unittest.TestCase):
    def test_application_email_uses_provided_details(self) -> None:
        email = generate_application_email(
            candidate_name="Test Candidate",
            job_title="Python Engineer",
            company="Example Co",
            cover_letter="I am interested in this role.",
        )

        self.assertEqual(email["subject"], "Application: Python Engineer — Test Candidate")
        self.assertIn("I am interested in this role.", email["body"])
        self.assertIn("Example Co hiring team", email["body"])


class PaidResumeTests(unittest.TestCase):
    @patch("ai_services._client")
    def test_refuses_to_prepare_paid_improvement_before_payment(
        self,
        client_mock: unittest.mock.Mock,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "Confirm payment"):
            generate_improved_resume(
                resume_text="Original resume",
                review={"summary": "Summary", "issues": []},
                service_description="Resume rewrite",
                payment_verified=False,
            )

        client_mock.assert_not_called()


class ResendTests(unittest.TestCase):
    @patch("email_sender.requests.post")
    def test_refuses_to_send_without_both_consent_and_approval(
        self,
        post_mock: unittest.mock.Mock,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "consent"):
            send_resend_email(
                api_key="key",
                sender="verified@example.com",
                recipient="candidate@example.com",
                subject="Resume review",
                body="May I help?",
                recipient_consented=False,
                approved=True,
            )
        with self.assertRaisesRegex(ValueError, "approve"):
            send_resend_email(
                api_key="key",
                sender="verified@example.com",
                recipient="candidate@example.com",
                subject="Resume review",
                body="May I help?",
                recipient_consented=True,
                approved=False,
            )

        post_mock.assert_not_called()

    @patch("email_sender.requests.post")
    def test_sends_only_the_approved_message(
        self,
        post_mock: unittest.mock.Mock,
    ) -> None:
        response = unittest.mock.Mock()
        response.ok = True
        response.json.return_value = {"id": "email-id-123"}
        post_mock.return_value = response

        message_id = send_resend_email(
            api_key="test-key",
            sender="verified@example.com",
            recipient="candidate@example.com",
            subject="Resume review",
            body="Here is the exact approved message.",
            recipient_consented=True,
            approved=True,
        )

        self.assertEqual(message_id, "email-id-123")
        self.assertEqual(
            post_mock.call_args.kwargs["headers"]["Authorization"], "Bearer test-key"
        )
        self.assertEqual(
            post_mock.call_args.kwargs["json"],
            {
                "from": "verified@example.com",
                "to": ["candidate@example.com"],
                "subject": "Resume review",
                "text": "Here is the exact approved message.",
            },
        )

    @patch("email_sender.requests.post")
    def test_rejects_invalid_email_addresses_without_sending(
        self,
        post_mock: unittest.mock.Mock,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "recipient"):
            send_resend_email(
                api_key="test-key",
                sender="verified@example.com",
                recipient="not-an-email",
                subject="Resume review",
                body="Message",
                recipient_consented=True,
                approved=True,
            )

        post_mock.assert_not_called()

    @patch("email_sender.requests.post")
    def test_attaches_reviewed_resume_and_deduplicates_identical_sends(self, post_mock) -> None:
        post_mock.return_value.ok = True
        post_mock.return_value.json.return_value = {"id": "message"}
        kwargs = dict(
            api_key="key", sender="sender@example.com", recipient="to@example.com",
            subject="Application", body="Body", recipient_consented=True,
            approved=True, resume_text="Reviewed resume",
        )
        send_resend_email(**kwargs)
        first_key = post_mock.call_args.kwargs["headers"]["Idempotency-Key"]
        attachment = post_mock.call_args.kwargs["json"]["attachments"][0]
        self.assertEqual(base64.b64decode(attachment["content"]).decode(), "Reviewed resume")
        send_resend_email(**kwargs)
        self.assertEqual(first_key, post_mock.call_args.kwargs["headers"]["Idempotency-Key"])
        send_resend_email(**{**kwargs, "body": "Different body"})
        self.assertNotEqual(first_key, post_mock.call_args.kwargs["headers"]["Idempotency-Key"])


if __name__ == "__main__":
    unittest.main()
