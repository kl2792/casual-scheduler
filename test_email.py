#!/usr/bin/env python3
"""Tests for outbid email notification feature."""

import smtplib
import threading
import unittest
from unittest.mock import MagicMock, call, patch


class TestSendOutbidEmail(unittest.TestCase):
    """Unit tests for send_outbid_email."""

    def setUp(self):
        # Import here so SMTP constants can be patched per-test
        import app
        self.app = app

    def test_no_op_when_smtp_host_unset(self):
        with patch.object(self.app, "SMTP_HOST", ""), \
             patch("smtplib.SMTP") as mock_smtp:
            self.app.send_outbid_email("user@columbia.edu", "alice", ["w|s|0"])
            mock_smtp.assert_not_called()

    def test_no_op_when_email_empty(self):
        with patch.object(self.app, "SMTP_HOST", "smtp.columbia.edu"), \
             patch("smtplib.SMTP") as mock_smtp:
            self.app.send_outbid_email("", "alice", ["w|s|0"])
            mock_smtp.assert_not_called()

    def test_sends_to_correct_address(self):
        mock_smtp_instance = MagicMock()
        mock_smtp_cls = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)

        with patch.object(self.app, "SMTP_HOST", "smtp.columbia.edu"), \
             patch.object(self.app, "SMTP_PORT", 587), \
             patch.object(self.app, "SMTP_USER", "bot@columbia.edu"), \
             patch.object(self.app, "SMTP_PASS", "secret"), \
             patch.object(self.app, "SMTP_FROM", "bot@columbia.edu"), \
             patch("smtplib.SMTP", mock_smtp_cls):
            self.app.send_outbid_email(
                "alice@columbia.edu", "alice",
                ["2025-11-15|2025-11-15T14:00|0"]
            )

        mock_smtp_instance.sendmail.assert_called_once()
        recipients = mock_smtp_instance.sendmail.call_args[0][1]
        self.assertIn("alice@columbia.edu", recipients)

    def test_email_body_contains_slot_info(self):
        captured = {}

        def fake_sendmail(from_addr, to_addrs, msg_str):
            captured["msg"] = msg_str

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)
        mock_smtp_instance.sendmail.side_effect = fake_sendmail

        with patch.object(self.app, "SMTP_HOST", "smtp.columbia.edu"), \
             patch.object(self.app, "SMTP_PORT", 587), \
             patch.object(self.app, "SMTP_USER", ""), \
             patch.object(self.app, "SMTP_PASS", ""), \
             patch.object(self.app, "SMTP_FROM", "bot@columbia.edu"), \
             patch("smtplib.SMTP", MagicMock(return_value=mock_smtp_instance)):
            self.app.send_outbid_email(
                "alice@columbia.edu", "alice",
                ["2025-11-15|2025-11-15T14:00|3", "2025-11-15|2025-11-15T15:00|7"]
            )

        import base64, quopri
        # MIMEText may base64-encode non-ASCII; decode for assertion
        import email as emaillib
        parsed = emaillib.message_from_string(captured["msg"])
        body = parsed.get_payload(decode=True).decode()
        self.assertIn("GPU 3", body)
        self.assertIn("GPU 7", body)
        self.assertIn("2025-11-15T14:00", body)

    def test_smtp_error_does_not_raise(self):
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)
        mock_smtp_instance.sendmail.side_effect = smtplib.SMTPException("connection refused")

        with patch.object(self.app, "SMTP_HOST", "smtp.columbia.edu"), \
             patch.object(self.app, "SMTP_FROM", "bot@columbia.edu"), \
             patch("smtplib.SMTP", MagicMock(return_value=mock_smtp_instance)):
            # Must not raise
            self.app.send_outbid_email("alice@columbia.edu", "alice", ["w|s|0"])

    def test_skips_login_when_no_credentials(self):
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)

        with patch.object(self.app, "SMTP_HOST", "smtp.columbia.edu"), \
             patch.object(self.app, "SMTP_USER", ""), \
             patch.object(self.app, "SMTP_PASS", ""), \
             patch.object(self.app, "SMTP_FROM", "bot@columbia.edu"), \
             patch("smtplib.SMTP", MagicMock(return_value=mock_smtp_instance)):
            self.app.send_outbid_email("alice@columbia.edu", "alice", ["w|s|0"])

        mock_smtp_instance.login.assert_not_called()
        mock_smtp_instance.sendmail.assert_called_once()


class TestFireOutbidEmails(unittest.TestCase):
    """Unit tests for _fire_outbid_emails."""

    def setUp(self):
        import app
        self.app = app

    def test_sends_one_email_per_user(self):
        sent = []

        def fake_send(to, username, slot_ids):
            sent.append((to, username, slot_ids))

        fake_state = {
            "users": {
                "alice": {"email": "alice@columbia.edu"},
                "bob": {"email": "bob@columbia.edu"},
            }
        }

        with patch.object(self.app, "state", fake_state), \
             patch.object(self.app, "send_outbid_email", side_effect=fake_send):
            t_before = threading.active_count()
            self.app._fire_outbid_emails({
                "alice": ("alice@columbia.edu", ["w|s|0", "w|s|1"]),
                "bob": ("bob@columbia.edu", ["w|s|2"]),
            })
            # Give the daemon thread time to finish
            import time; time.sleep(0.1)

        usernames = {u for _, u, _ in sent}
        self.assertEqual(usernames, {"alice", "bob"})

        alice_entry = next(e for e in sent if e[1] == "alice")
        self.assertEqual(sorted(alice_entry[2]), ["w|s|0", "w|s|1"])

    def test_skips_users_without_email(self):
        sent = []

        fake_state = {
            "users": {
                "alice": {"email": ""},
                "bob": {"email": "bob@columbia.edu"},
            }
        }

        with patch.object(self.app, "state", fake_state), \
             patch.object(self.app, "send_outbid_email", side_effect=lambda *a: sent.append(a)):
            self.app._fire_outbid_emails({
                "alice": ("", ["w|s|0"]),
                "bob": ("bob@columbia.edu", ["w|s|1"]),
            })
            import time; time.sleep(0.1)

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1], "bob")

    def test_skips_unknown_users(self):
        sent = []
        fake_state = {"users": {}}

        with patch.object(self.app, "state", fake_state), \
             patch.object(self.app, "send_outbid_email", side_effect=lambda *a: sent.append(a)):
            # email_map has pre-resolved addresses; empty email means no send
            self.app._fire_outbid_emails({"ghost": ("", ["w|s|0"])})
            import time; time.sleep(0.1)

        self.assertEqual(sent, [])


class TestEmailFieldOnUser(unittest.TestCase):
    """Tests that email is stored and updated correctly."""

    def setUp(self):
        import app
        self.app = app
        # Minimal state for user ops
        self.app.state = {
            "users": {},
            "days": {},
            "bid_log": [],
            "config": {},
        }

    def test_create_user_account_sets_empty_email(self):
        user = self.app.create_user_account("alice", "pw")
        self.assertIn("email", user)
        self.assertEqual(user["email"], "")

    def test_update_user_sets_email(self):
        self.app.state["users"]["alice"] = {
            "username": "alice",
            "role": "user",
            "balance": 100.0,
            "weekly_budget": 100,
            "rollover_applied": 0,
            "email": "",
        }
        with patch.object(self.app, "save_state"):
            result = self.app.update_user({"username": "alice", "email": "alice@columbia.edu"})
        self.assertEqual(result["ok"], True)
        # email goes to email_pending until verified, not directly to email
        self.assertEqual(self.app.state["users"]["alice"]["email_pending"], "alice@columbia.edu")
        self.assertEqual(self.app.state["users"]["alice"].get("email", ""), "")

    def test_update_user_strips_whitespace(self):
        self.app.state["users"]["alice"] = {
            "username": "alice", "role": "user", "balance": 100.0,
            "weekly_budget": 100, "rollover_applied": 0, "email": "",
        }
        with patch.object(self.app, "save_state"):
            self.app.update_user({"username": "alice", "email": "  alice@columbia.edu  "})
        self.assertEqual(self.app.state["users"]["alice"]["email_pending"], "alice@columbia.edu")


if __name__ == "__main__":
    unittest.main()
