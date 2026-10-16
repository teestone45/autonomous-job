import unittest
from unittest.mock import patch

from ai_services import generate_application_email
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


if __name__ == "__main__":
    unittest.main()
