"""Error diagnostics use fixtures only; no API calls or personal settings."""
import json
import unittest
from unittest import mock

import httpx
from core.api_errors import OpenAIRequestError, openai_error


class APIErrorTests(unittest.TestCase):
    def test_credits_and_frequency_errors_have_different_actions(self):
        credits = openai_error(429, {"error": {"code": "credit_balance_exhausted", "type": "insufficient_quota"}})
        frequency = openai_error(429, {"error": {"code": "rate_limit_exceeded", "type": "rate_limit_error"}})
        self.assertIn("créditos", str(credits))
        self.assertIn("frecuencia", str(frequency))
        self.assertNotIn("Espera", str(credits))

    def test_specific_billing_code_wins_over_broad_quota_type(self):
        for code in ("organization_spend_limit_exceeded", "project_spend_limit_exceeded", "organization_usage_limit_exceeded"):
            with self.subTest(code=code):
                error = openai_error(429, {"error": {"code": code, "type": "insufficient_quota"}})
                self.assertEqual(error.code, code)
                self.assertNotIn("No quedan créditos", str(error))

    def test_historical_credit_message_is_recognized_but_not_echoed(self):
        payload = {"error": {"type": "insufficient_quota", "message": "You have no credits remaining. private user data"}}
        error = openai_error(429, payload)
        self.assertEqual(error.code, "credit_balance_exhausted")
        self.assertNotIn("private user data", str(error))

    def test_unrecognized_values_never_echo_keys_inputs_or_raw_codes(self):
        for payload in ("private body", {"error": "private body"},
                        {"error": {"code": "sk-private", "message": "private body", "param": "private input"}},
                        {"error": {"code": [], "type": [], "message": "private body"}}):
            error = openai_error(payload=payload)
            self.assertIsInstance(error, OpenAIRequestError)
            self.assertNotIn("private", str(error))

    def test_only_known_parameter_names_reach_diagnostics(self):
        error = openai_error(400, {"error": {"code": "unsupported_parameter", "param": "reasoning.effort", "message": "secret"}})
        self.assertIn("reasoning.effort", str(error))
        self.assertNotIn("secret", str(error))
        error = openai_error(400, {"error": {"code": "unsupported_parameter", "param": "private-input"}})
        self.assertNotIn("private-input", str(error))

    def test_spoken_feedback_uses_the_safe_specific_diagnosis(self):
        from providers.engine_pipeline import _failure_line
        error = openai_error(payload={"code": "credit_balance_exhausted", "message": "secret"})
        spoken = _failure_line("the language model", error)
        self.assertEqual(spoken, error.user_message)
        self.assertIn("créditos", spoken)
        self.assertNotIn("secret", spoken)

    def test_openai_whisper_rejects_without_echoing_server_body(self):
        from providers.stt_whisper import WhisperSTT
        provider = WhisperSTT({"backend": "api", "base_url": "https://api.openai.com/v1", "model": "whisper-1", "api_key": "fake-test-key"})
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(429, json={"error": {"type": "insufficient_quota", "code": "credit_balance_exhausted", "message": "secret audio input"}})
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with mock.patch("httpx.Client", return_value=client):
            with self.assertRaises(OpenAIRequestError) as caught:
                provider._api_blocking(b"\0" * 320, 16000)
        self.assertIn("créditos", str(caught.exception))
        self.assertNotIn("secret audio", str(caught.exception))
        self.assertEqual(len(requests), 1)


if __name__ == "__main__":
    unittest.main()
