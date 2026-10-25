"""Responses/routing tests with HTTP mocks, fake keys and isolated SQLite files."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import httpx
from memory import api_usage, state_store
from providers.llm_responses import ResponsesLLM, response_input


TOOLS = [{"type": "function", "function": {"name": "manage_tasks", "description": "Tasks",
          "parameters": {"type": "object", "properties": {"action": {"type": "string"}}}}}]
MESSAGES = [{"role": "system", "content": "Eres JARVIS"}, {"role": "user", "content": "Razona: revisa mis pendientes"}]
REASON = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque-state"}
CALL = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "manage_tasks", "arguments": '{"action":"list"}'}


def result(output=None, status="completed"):
    return {"status": status, "output": output if output is not None else [
        {"id": "msg_1", "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Listo."}]}],
        "usage": {"input_tokens": 123, "output_tokens": 45}}


def sse(data, *events):
    items = list(events) + [{"type": "response." + data["status"], "response": data}]
    return "".join("data: " + json.dumps(item) + "\n\n" for item in items)


class IsolatedUsage(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="jarvis-responses-test-")
        patch = mock.patch.object(state_store, "DB_PATH", Path(self.folder.name) / "assistant.db")
        patch.start()
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(patch.stop)
        self.requests = []

    def provider(self, **settings):
        return ResponsesLLM(dict(api_key="fake-test-key", model="test-model", **settings))

    def http(self, provider, handler):
        def record(request):
            self.requests.append(request)
            return handler(request)
        transport = httpx.MockTransport(record)
        provider._httpx = SimpleNamespace(
            Client=lambda **kw: httpx.Client(transport=transport, **kw),
            AsyncClient=lambda **kw: httpx.AsyncClient(transport=transport, **kw))


class ResponsesTests(IsolatedUsage):
    def test_request_shape_and_confirmed_usage(self):
        provider = self.provider(reasoning_effort="medium")
        self.http(provider, lambda r: httpx.Response(200, json=result()))
        text, calls = provider.complete(MESSAGES, TOOLS, temperature=0.3)
        body = json.loads(self.requests[0].content)
        self.assertEqual(str(self.requests[0].url), "https://api.openai.com/v1/responses")
        self.assertFalse(body["store"])
        self.assertEqual(body["max_output_tokens"], 2048)
        self.assertEqual(body["reasoning"], {"effort": "medium"})
        self.assertFalse(body["tools"][0]["strict"])
        self.assertNotIn("function", body["tools"][0])
        self.assertNotIn("temperature", body)
        self.assertEqual((text, calls), ("Listo.", []))
        self.assertEqual(api_usage.today(), dict(requests=1, input_tokens=123, output_tokens=45, uncertain_requests=0))

    def test_native_items_replayed_exactly_and_tool_correlates_call_id(self):
        native = [REASON, CALL]
        history = deepcopy(MESSAGES) + [{"role": "assistant", "content": None,
            "tool_calls": [{"id": "call_1", "function": {"name": "manage_tasks", "arguments": CALL["arguments"]}}],
            "_response_items": native}, {"role": "tool", "tool_call_id": "call_1", "content": "pendiente"}]
        converted = response_input(history)
        self.assertEqual(converted[2:4], native)
        self.assertEqual(converted[4], {"type": "function_call_output", "call_id": "call_1", "output": "pendiente"})
        self.assertEqual(sum(item.get("type") == "function_call" for item in converted), 1)
        converted[2]["encrypted_content"] = "changed"
        self.assertEqual(REASON["encrypted_content"], "opaque-state")

    def test_streaming_uses_completed_arguments_not_partial_deltas(self):
        provider = self.provider()
        payload = sse(result([REASON, CALL]),
                      {"type": "response.function_call_arguments.delta", "delta": '{"action":'},
                      {"type": "response.output_text.delta", "delta": "Un momento."})
        self.http(provider, lambda r: httpx.Response(200, text=payload))
        async def run():
            return [event async for event in provider.chat(MESSAGES, TOOLS)]
        events = asyncio.run(run())
        self.assertEqual(events[0], {"text": "Un momento."})
        self.assertEqual(events[1], {"response_items": [REASON, CALL]})
        self.assertEqual(events[2]["tool_calls"][0].id, "call_1")
        self.assertEqual(events[2]["tool_calls"][0].args, {"action": "list"})

    def test_invalid_or_unoffered_tool_never_dispatched(self):
        provider = self.provider()
        for call in [dict(CALL, arguments="{"), dict(CALL, arguments="[]"), dict(CALL, name="unknown")]:
            with self.subTest(call=call):
                self.http(provider, lambda r: httpx.Response(200, json=result([call])))
                with self.assertRaisesRegex(RuntimeError, "no válida"):
                    provider.complete(MESSAGES, TOOLS)

    def test_incomplete_stream_does_not_dispatch_partial_tools(self):
        provider = self.provider()
        for payload in [sse(result([CALL], "incomplete")), 'data: {"type":"response.output_text.delta","delta":"Hola"}\n\n']:
            self.http(provider, lambda r: httpx.Response(200, text=payload))
            async def run():
                return [event async for event in provider.chat(MESSAGES, TOOLS)]
            with self.assertRaises(RuntimeError):
                asyncio.run(run())
        self.assertEqual(api_usage.today()["uncertain_requests"], 2)

    def test_cancelled_stream_is_counted_without_saving_text(self):
        provider = self.provider()
        self.http(provider, lambda r: httpx.Response(200, text=sse(result(), {"type": "response.output_text.delta", "delta": "private text"})))
        async def run():
            generator = provider.chat(MESSAGES)
            await anext(generator)
            await generator.aclose()
        asyncio.run(run())
        self.assertEqual(api_usage.today()["uncertain_requests"], 1)
        binary = state_store.DB_PATH.read_bytes()
        self.assertNotIn(b"private text", binary)
        self.assertNotIn(b"fake-test-key", binary)
        self.assertNotIn(b"Eres JARVIS", binary)

    def test_budget_exhaustion_prevents_second_http_request(self):
        provider = self.provider(daily_requests=1)
        self.http(provider, lambda r: httpx.Response(200, json=result()))
        provider.complete(MESSAGES)
        with self.assertRaises(api_usage.BudgetExceeded):
            provider.complete(MESSAGES)
        self.assertEqual(len(self.requests), 1)
        other = self.provider(daily_requests=1)
        self.http(other, lambda r: self.fail("Limit must survive new provider instances"))
        with self.assertRaises(api_usage.BudgetExceeded):
            other.complete(MESSAGES)

    def test_zero_budget_and_preflight_errors_make_no_http_request(self):
        provider = self.provider(daily_requests=0)
        self.http(provider, lambda r: self.fail("No request authorized"))
        with self.assertRaises(api_usage.BudgetExceeded):
            provider.complete(MESSAGES)
        provider = self.provider(max_input_chars=1000)
        with self.assertRaisesRegex(ValueError, "contexto"):
            provider.complete([{"role": "user", "content": "x" * 1100}])
        provider.key = ""
        with self.assertRaisesRegex(ValueError, "clave"):
            provider.complete(MESSAGES)
        self.assertEqual(api_usage.today()["requests"], 0)

    def test_error_does_not_echo_response_body_or_retry(self):
        provider = self.provider()
        self.http(provider, lambda r: httpx.Response(401, text="secret-key and private input"))
        with self.assertRaisesRegex(RuntimeError, "HTTP 401") as caught:
            provider.complete(MESSAGES)
        self.assertNotIn("secret-key", str(caught.exception))
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(api_usage.today()["requests"], 1)

    def test_stream_error_reports_credits_without_retrying_or_executing_tools(self):
        from core.api_errors import OpenAIRequestError
        provider = self.provider()
        payload = {"type": "error", "code": "credit_balance_exhausted", "message": "private prompt"}
        self.http(provider, lambda r: httpx.Response(200, text="data: " + json.dumps(payload) + "\n\n"))
        events = []
        async def run():
            async for event in provider.chat(MESSAGES, TOOLS):
                events.append(event)
        with self.assertRaises(OpenAIRequestError) as caught:
            asyncio.run(run())
        self.assertEqual(caught.exception.code, "credit_balance_exhausted")
        self.assertIn("créditos", str(caught.exception))
        self.assertNotIn("private prompt", str(caught.exception))
        self.assertEqual(events, [])
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(api_usage.today()["requests"], 1)

    def test_failed_response_preserves_the_safe_server_diagnosis(self):
        from core.api_errors import OpenAIRequestError
        provider = self.provider()
        failed = result([CALL], "failed")
        failed["error"] = {"code": "model_not_found", "message": "private input"}
        self.http(provider, lambda r: httpx.Response(200, text=sse(failed)))
        async def run():
            return [event async for event in provider.chat(MESSAGES, TOOLS)]
        with self.assertRaises(OpenAIRequestError) as caught:
            asyncio.run(run())
        self.assertEqual(caught.exception.code, "model_not_found")
        self.assertNotIn("private input", str(caught.exception))

    def test_http_quota_response_is_actionable(self):
        provider = self.provider()
        self.http(provider, lambda r: httpx.Response(429, json={"error": {"code": "insufficient_quota", "message": "private input"}}))
        with self.assertRaisesRegex(RuntimeError, "cuota disponible"):
            provider.complete(MESSAGES)
        self.assertEqual(len(self.requests), 1)

    def test_hybrid_routes_by_request_and_explicit_tier_without_classifier_call(self):
        provider = self.provider(routing="hybrid", local_model="fake-local")
        def route(text, task=None):
            return provider.route([{"role": "user", "content": text},
                {"role": "assistant", "content": "investiga"}, {"role": "tool", "content": "razona:"}], task)
        self.assertEqual(route("Abre la calculadora"), "local")
        self.assertEqual(route("Analiza mis prioridades"), "openai")
        self.assertEqual(route("Local: compara mis pendientes", "smart"), "local")
        self.assertEqual(route("Razona: hola"), "openai")
        self.assertEqual(route("Una tarea", "smart"), "openai")
        self.assertEqual(route("Una tarea", "fast"), "local")
        self.assertEqual(route("x" * 1201), "openai")
        with mock.patch.object(provider.local, "complete", return_value=("local answer", [])) as local:
            self.assertEqual(provider.complete([{"role": "user", "content": "Hola"}])[0], "local answer")
        local.assert_called_once()
        self.assertEqual(api_usage.today()["requests"], 0)

    def test_local_address_must_stay_on_machine(self):
        for address in ["http://external.example/v1", "http://localhost.external.example/v1", "http://key@localhost/v1", "file://localhost/a"]:
            with self.assertRaises(ValueError):
                self.provider(routing="hybrid", local_model="local", local_url=address)

    def test_concurrent_reservations_respect_shared_limit(self):
        def reserve(_):
            try:
                return api_usage.reserve("model", 5)
            except api_usage.BudgetExceeded:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(reserve, range(16)))
        self.assertEqual(sum(bool(identifier) for identifier in results), 5)
        self.assertEqual(api_usage.today()["requests"], 5)

    def test_limit_survives_a_new_process(self):
        api_usage.reserve("model", 1)
        code = "from memory.api_usage import today; assert today()['requests'] == 1"
        result = subprocess.run([sys.executable, "-B", "-c", code], env=dict(os.environ, JARVIS_DATA_DIR=self.folder.name),
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_selected_responses_never_falls_back_to_gemini(self):
        from core import gemini
        with mock.patch.object(gemini, "_provider_rungs", return_value=("prov:openai_responses",)), \
             mock.patch.object(gemini, "_provider_call", side_effect=api_usage.BudgetExceeded("daily limit")) as provider, \
             mock.patch.object(gemini, "api_key", return_value="fake-gemini-key"), \
             mock.patch.object(gemini, "client", side_effect=AssertionError("Gemini must not be contacted")):
            self.assertIsNone(gemini.call("hello", tier=gemini.SMART))
        provider.assert_called_once()

    def test_recordings_keep_the_dedicated_gemini_route(self):
        from core import gemini
        recording = {"inline_data": {"mime_type": "audio/wav", "data": b"fake audio"}}
        generate = mock.Mock(return_value=SimpleNamespace(text="recording summary"))
        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        with mock.patch.object(gemini, "_provider_rungs", return_value=("prov:openai_responses",)), \
             mock.patch.object(gemini, "_provider_call", side_effect=AssertionError("Responses must not receive recordings")), \
             mock.patch.object(gemini, "api_key", return_value="fake-gemini-key"), \
             mock.patch.object(gemini, "client", return_value=client):
            self.assertEqual(gemini.call(recording).text, "recording summary")
        generate.assert_called_once()

    def test_internal_responses_metadata_is_not_sent_to_local_chat_endpoint(self):
        from providers.llm_openai import OpenAICompatLLM
        local = OpenAICompatLLM({"base_url": "http://127.0.0.1:11434/v1", "model": "local"})
        messages = [{"role": "assistant", "content": "Listo", "_response_items": [REASON]}]
        body = local._body(messages, None, False, None)
        self.assertEqual(body["messages"], [{"role": "assistant", "content": "Listo"}])
        self.assertIn("_response_items", messages[0])

    def test_pipeline_preserves_native_items_through_a_tool_round(self):
        from providers.engine_pipeline import PipelineEngine
        provider = self.provider()
        bodies = []
        def handler(request):
            bodies.append(json.loads(request.content))
            output = [REASON, CALL] if len(bodies) == 1 else None
            return httpx.Response(200, text=sse(result(output)))
        self.http(provider, handler)
        config = SimpleNamespace(system_instruction="Eres JARVIS", tools=[{"function_declarations": [{
            "name": "manage_tasks", "description": "Tasks", "parameters": TOOLS[0]["function"]["parameters"]}]}])
        engine = PipelineEngine(provider, config=config, history_chars=10)
        executed, heard = [], []
        async def run():
            async def consume():
                async for event in engine.receive():
                    if event.tool_call:
                        for call in event.tool_call.function_calls:
                            executed.append(call.id)
                            await engine.send_tool_response(function_responses=[SimpleNamespace(
                                id=call.id, name=call.name, response={"result": "sin pendientes"})])
                    if event.server_content:
                        if event.server_content.output_transcription:
                            heard.append(event.server_content.output_transcription.text)
                        if event.server_content.turn_complete:
                            return
            task = asyncio.create_task(consume())
            await engine.send_client_content(turns={"role": "user", "parts": [{"text": "Revisa mis pendientes"}]})
            await asyncio.wait_for(task, 5)
            await engine.close()
        asyncio.run(run())
        self.assertEqual(executed, ["call_1"])
        self.assertEqual(bodies[1]["input"][2:4], [REASON, CALL])
        self.assertEqual(bodies[1]["input"][4]["call_id"], "call_1")
        self.assertEqual(heard, ["Listo."])


if __name__ == "__main__":
    unittest.main()
