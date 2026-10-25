"""Official Responses API adapter and explicit, deterministic local/cloud routing."""
from __future__ import annotations

from copy import deepcopy
from importlib.util import find_spec
import json
import re
import unicodedata
from urllib.parse import urlsplit

from .base import DEFAULT_CAPS, Field, FunctionCall
from .llm_openai import OpenAICompatLLM
from memory import api_usage
from core.api_errors import openai_error


def _number(cfg, key, default, low, high):
    try:
        value = int(cfg.get(key, default))
    except (TypeError, ValueError):
        raise ValueError(f"{key}: introduce un número entero") from None
    if not low <= value <= high:
        raise ValueError(f"{key}: debe estar entre {low} y {high}")
    return value


def _text(content):
    if isinstance(content, str):
        return content
    return "\n".join(str(p.get("text", "")) for p in (content or []) if isinstance(p, dict))


def _images(messages):
    return any(isinstance(m.get("content"), list) and any(
        p.get("type") == "image_url" for p in m["content"] if isinstance(p, dict)) for m in messages)


def response_input(messages):
    """Translate the existing transcript, replaying native outputs unchanged.

    Reasoning items (including encrypted_content) belong in input, never speech
    or the persistent memory. Tool results correlate by call_id, not item id.
    """
    items = []
    for message in messages:
        role, content = message.get("role", "user"), message.get("content")
        if role == "assistant" and message.get("_response_items"):
            items.extend(deepcopy(message["_response_items"]))
            continue
        if role == "tool":
            items.append({"type": "function_call_output", "call_id": message["tool_call_id"],
                          "output": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)})
            continue
        if content:
            if isinstance(content, list):
                parts = []
                for part in content:
                    if part.get("type") == "text":
                        parts.append({"type": "input_text", "text": part["text"]})
                    elif part.get("type") == "image_url":
                        image = part["image_url"]
                        parts.append({"type": "input_image", "image_url": image["url"],
                                      "detail": image.get("detail", "auto")})
                    else:
                        raise ValueError("Tipo de contenido no soportado por Responses")
                content = parts
            items.append({"role": role, "content": content})
        for call in message.get("tool_calls") or []:
            function = call["function"]
            items.append({"type": "function_call", "call_id": call["id"],
                          "name": function["name"], "arguments": function["arguments"]})
    return items


class ResponsesLLM:
    supports_task_routing = True

    def __init__(self, cfg):
        import httpx
        self._httpx = httpx
        self.key = str(cfg.get("api_key") or "").strip()
        self.model = str(cfg.get("model") or "").strip()
        self.mode = str(cfg.get("routing") or "openai")
        if self.mode not in {"openai", "hybrid"}:
            raise ValueError("routing: elige openai o hybrid")
        self.effort = str(cfg.get("reasoning_effort") or "default")
        if self.effort not in {"default", "low", "medium", "high"}:
            raise ValueError("Nivel de razonamiento no válido")
        self.daily_limit = _number(cfg, "daily_requests", 50, 0, 10000)
        self.output_limit = _number(cfg, "max_output_tokens", 2048, 256, 32768)
        self.input_limit = _number(cfg, "max_input_chars", 60000, 1000, 500000)
        self.timeout = _number(cfg, "timeout", 90, 5, 600)
        self.local = None
        if self.mode == "hybrid":
            address = str(cfg.get("local_url") or "http://127.0.0.1:11434/v1").strip()
            url = urlsplit(address)
            # "Local" must remain on this machine, even when proxies are set.
            if url.scheme not in {"http", "https"} or url.hostname not in {"localhost", "127.0.0.1", "::1"} or url.username or url.password:
                raise ValueError("La dirección local debe usar localhost, 127.0.0.1 o ::1")
            local_model = str(cfg.get("local_model") or "").strip()
            if not local_model:
                raise ValueError("El modo híbrido requiere un modelo local instalado")
            self.local = OpenAICompatLLM({"base_url": address, "model": local_model,
                                         "vision": False, "timeout": self.timeout,
                                         "max_tools": 0, "max_tool_chars": 0})
        self.caps = dict(DEFAULT_CAPS, tools=True, tool_format="openai",
                         vision=bool(cfg.get("vision", False)), max_tools=0, max_tool_chars=0)

    def route(self, messages, task=None):
        if not self.local:
            return "openai"
        last = next((m for m in reversed(messages) if m.get("role") == "user"), {})
        text = _text(last.get("content")).strip().casefold()
        folded = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
        # Explicit prefixes win; tool outputs cannot influence this decision.
        if folded.startswith("local:"):
            return "local"
        if folded.startswith(("razona:", "openai:")):
            return "openai"
        if task == "smart" or _images(messages) or len(text) > 1200 or re.search(
                r"\b(analiza|analizar|compara|comparar|investiga|investigar|planifica|planificar|"
                r"resuelve|resolver|depura|disena|razona|estrategia|analyze|compare|debug|reason)\b", folded):
            return "openai"
        return "local"

    def _headers(self):
        if not self.key:
            raise ValueError("Configura tu clave de OpenAI en proveedores de JARVIS")
        return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    def _body(self, messages, tools, stream):
        if not self.model:
            raise ValueError("Selecciona un modelo de OpenAI compatible con Responses")
        inputs = response_input(messages)
        converted = []
        for tool in tools or []:
            function = tool.get("function", tool)
            converted.append({"type": "function", "name": function["name"],
                              "description": function.get("description", ""),
                              "parameters": deepcopy(function.get("parameters") or {"type": "object", "properties": {}}),
                              # Existing tools have optional properties; do not
                              # silently turn every optional field into required.
                              "strict": False})
        size = len(json.dumps([inputs, converted], ensure_ascii=False))
        if size > self.input_limit:
            raise ValueError(f"OpenAI: contexto de {size} caracteres supera el límite de {self.input_limit}. Inicia una sesión nueva o ajusta el límite.")
        if _images(messages) and not self.caps["vision"]:
            raise ValueError("Activa visión únicamente con un modelo que admita imágenes")
        body = {"model": self.model, "input": inputs, "store": False,
                "max_output_tokens": self.output_limit, "stream": stream,
                "parallel_tool_calls": False}
        if self.effort != "default":
            body["reasoning"] = {"effort": self.effort}
        if converted:
            body["tools"] = converted
        return body

    @staticmethod
    def _error(status, payload=None):
        return openai_error(status, payload)

    @staticmethod
    def _result(data, tools):
        if data.get("error"):
            raise openai_error(payload=data)
        if data.get("status") != "completed":
            raise RuntimeError("OpenAI: respuesta incompleta o fallida; no se ejecutaron sus herramientas. Revisa el límite de salida.")
        output, calls, texts, seen = data.get("output") or [], [], [], set()
        allowed = {t.get("function", t)["name"] for t in tools or []}
        for item in output:
            if item.get("type") == "function_call":
                try:
                    args = json.loads(item["arguments"])
                    identifier, name = item["call_id"], item["name"]
                    if not isinstance(args, dict) or not identifier or identifier in seen or name not in allowed:
                        raise ValueError()
                except (ValueError, KeyError, TypeError):
                    raise RuntimeError("OpenAI devolvió una llamada a herramienta no válida; no se ejecutará") from None
                seen.add(identifier)
                calls.append(FunctionCall(id=identifier, name=name, args=args))
            elif item.get("type") == "message":
                for part in item.get("content") or []:
                    if part.get("type") == "output_text":
                        texts.append(part.get("text", ""))
                    elif part.get("type") == "refusal":
                        texts.append(part.get("refusal", ""))
        return "".join(texts), calls, deepcopy(output)

    def complete(self, messages, tools=None, *, timeout=None, temperature=None, task=None):
        if self.route(messages, task) == "local":
            if _images(messages):
                raise ValueError("El modo local de este proveedor solo admite texto")
            return self.local.complete(messages, tools, timeout=timeout, temperature=temperature)
        headers, body = self._headers(), self._body(messages, tools, False)
        reservation = api_usage.reserve(self.model, self.daily_limit)
        status, usage = "unknown", None
        try:
            with self._httpx.Client(timeout=timeout or self.timeout) as client:
                response = client.post("https://api.openai.com/v1/responses", headers=headers, json=body)
                if response.status_code >= 400:
                    raise self._error(response.status_code, response.text)
                data = response.json()
            usage = data.get("usage")
            text, calls, _ = self._result(data, tools)
            status = "completed"
            return text, calls
        finally:
            api_usage.finish(reservation, status, usage)

    async def chat(self, messages, tools=None, *, stream=True, temperature=None):
        if self.route(messages) == "local":
            if _images(messages):
                raise ValueError("El modo local de este proveedor solo admite texto")
            async for event in self.local.chat(messages, tools, stream=stream, temperature=temperature):
                yield event
            return
        headers, body = self._headers(), self._body(messages, tools, stream)
        reservation = api_usage.reserve(self.model, self.daily_limit)
        status, usage, data, emitted = "unknown", None, None, False
        try:
            async with self._httpx.AsyncClient(timeout=self.timeout) as client:
                if stream:
                    async with client.stream("POST", "https://api.openai.com/v1/responses", headers=headers, json=body) as response:
                        if response.status_code >= 400:
                            raise self._error(response.status_code, await response.aread())
                        # Responses emits one JSON data line per SSE event.
                        async for line in response.aiter_lines():
                            if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                                continue
                            try:
                                event = json.loads(line[5:].strip())
                            except ValueError:
                                raise RuntimeError("OpenAI: evento de transmisión no válido") from None
                            kind = event.get("type")
                            if kind in {"response.output_text.delta", "response.refusal.delta"} and event.get("delta"):
                                emitted = True
                                yield {"text": event["delta"]}
                            elif kind in {"response.completed", "response.incomplete", "response.failed"}:
                                data = event.get("response") or {}
                                break
                            elif kind == "error":
                                raise openai_error(payload=event)
                else:
                    response = await client.post("https://api.openai.com/v1/responses", headers=headers, json=body)
                    if response.status_code >= 400:
                        raise self._error(response.status_code, response.text)
                    data = response.json()
            if data is None:
                raise RuntimeError("OpenAI: conexión interrumpida antes de completar la respuesta")
            usage = data.get("usage")
            text, calls, items = self._result(data, tools)
            status = "completed"
            if text and not emitted:
                yield {"text": text}
            yield {"response_items": items}
            if calls:
                yield {"tool_calls": calls}
        finally:
            api_usage.finish(reservation, status, usage)

    def models(self, timeout=8.0):
        with self._httpx.Client(timeout=timeout) as client:
            response = client.get("https://api.openai.com/v1/models", headers=self._headers())
            if response.status_code >= 400:
                raise self._error(response.status_code, response.text)
            # The account list can include models for other APIs. The user
            # chooses a Responses-capable text model; discovery never probes it.
            return sorted(item["id"] for item in response.json().get("data", [])
                          if item["id"].startswith(("gpt-", "o1", "o3", "o4"))
                          and not any(s in item["id"] for s in ("audio", "realtime", "transcribe", "tts", "image")))

    def probe(self):
        models = self.models()
        found = self.model in models
        return found, ("Clave aceptada; modelo listado. No se generó una respuesta de pago." if found
                       else "Clave aceptada. Elige un modelo listado que admita Responses.")


PROVIDER = {
    "id": "openai_responses", "kind": "llm", "label": "OpenAI Responses / híbrido local",
    "hint": "Razonamiento, herramientas y límites de uso; voz actual compatible",
    "requires": ("httpx",), "install": "httpx", "factory": ResponsesLLM,
    "caps": {"tools": True, "tool_format": "openai"},
    "needs": (
        Field("api_key", "Clave API de OpenAI", kind="secret", required=False,
              hint="Se guarda protegida en Windows. Necesaria para usar OpenAI."),
        Field("model", "Modelo de OpenAI (Responses)", kind="choice", choices=(),
              hint="REFRESH consulta tu cuenta. Elige un modelo de texto compatible con Responses."),
        Field("routing", "Modo: openai = siempre API; hybrid = local para lo sencillo", kind="choice",
              choices=("openai", "hybrid"), default="openai"),
        Field("daily_requests", "Máximo de solicitudes OpenAI por día UTC (0 desactiva)", kind="number", default=50),
        Field("max_output_tokens", "Máximo de tokens por respuesta (incluye razonamiento)", kind="number", default=2048),
        Field("local_url", "Servidor local para modo hybrid", default="http://127.0.0.1:11434/v1", required=False),
        Field("local_model", "Modelo local instalado para modo hybrid", required=False,
              hint="Nombre exacto del modelo de Ollama o LM Studio."),
        Field("reasoning_effort", "Esfuerzo de razonamiento", kind="choice", choices=("default", "low", "medium", "high"),
              default="default", advanced=True, required=False, hint="default respeta el modelo; los niveles admitidos varían."),
        Field("vision", "El modelo de OpenAI admite imágenes", kind="bool", default=False, advanced=True, required=False),
        Field("max_input_chars", "Máximo de caracteres de contexto y herramientas", kind="number", default=60000, advanced=True, required=False),
        Field("timeout", "Tiempo máximo de espera en segundos", kind="number", default=90, advanced=True, required=False),
    ),
}


def available():
    return find_spec("httpx") is not None
