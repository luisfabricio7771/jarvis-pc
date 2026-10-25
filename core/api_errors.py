"""Actionable OpenAI errors without echoing server messages, inputs or keys."""
from __future__ import annotations

import json


class OpenAIRequestError(RuntimeError):
    """Only trusted, locally written text reaches logs and spoken feedback."""

    def __init__(self, message: str, *, code="", status=None):
        self.code = code
        self.status = status
        self.user_message = message
        prefix = f"OpenAI HTTP {status}" if status else "OpenAI"
        super().__init__(f"{prefix}: {message}")


_MESSAGES = {
    "credit_balance_exhausted": "No quedan créditos de API. Revisa el saldo en la facturación de OpenAI.",
    "insufficient_quota": "La API no tiene cuota disponible. Revisa saldo y límites de la organización y del proyecto en OpenAI.",
    "organization_spend_limit_exceeded": "Se alcanzó el límite de gasto de la organización en OpenAI. Revisa su facturación.",
    "project_spend_limit_exceeded": "Se alcanzó el límite de gasto del proyecto en OpenAI. Revisa sus límites.",
    "organization_usage_limit_exceeded": "Se alcanzó el límite de uso asignado a la organización en OpenAI.",
    "rate_limit_exceeded": "Se alcanzó el límite de frecuencia de OpenAI. Espera antes de volver a intentarlo.",
    "slow_down": "OpenAI pide reducir la frecuencia de solicitudes. Espera antes de volver a intentarlo.",
    "server_is_overloaded": "El modelo de OpenAI está sobrecargado temporalmente. Inténtalo más tarde.",
    "server_error": "OpenAI informó de un error interno. Inténtalo más tarde.",
    "invalid_api_key": "La clave API fue rechazada. Revisa la clave configurada en proveedores.",
    "model_not_found": "El modelo no está disponible para esta clave. Revisa el nombre y el acceso de tu proyecto.",
    "permission_denied": "El proyecto no tiene permiso para realizar esta solicitud en OpenAI.",
    "context_length_exceeded": "El contexto supera la capacidad del modelo. Inicia una sesión nueva o reduce el contenido.",
    "unsupported_parameter": "El modelo no admite un parámetro de la solicitud.",
    "unsupported_value": "El modelo no admite un valor de la configuración.",
    "invalid_value": "OpenAI rechazó un valor de la configuración.",
}
_PARAMS = {"model", "reasoning", "reasoning.effort", "parallel_tool_calls", "tools", "input",
           "max_output_tokens", "store", "stream", "response_format", "temperature"}


def openai_error(status=None, payload=None) -> OpenAIRequestError:
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    error = payload.get("error", payload)
    if not isinstance(error, dict):
        error = {}
    code = error.get("code")
    if not isinstance(code, str):
        code = ""
    kind = error.get("type")
    # Historical responses sometimes supply only the broad quota type. Use
    # narrowly recognized wording to distinguish credits; never echo the text.
    message = str(error.get("message") or "").casefold()
    if code not in _MESSAGES:
        if (kind == "insufficient_quota" or status == 429) and any(
                phrase in message for phrase in ("no credits remaining", "credit balance exhausted", "no prepaid credits")):
            code = "credit_balance_exhausted"
        elif kind == "insufficient_quota":
            code = "insufficient_quota"
        elif kind == "rate_limit_error":
            code = "rate_limit_exceeded"
        else:
            code = ""
    text = _MESSAGES.get(code)
    if text is None:
        text = {
            400: "OpenAI rechazó la solicitud. Revisa el modelo y sus parámetros.",
            401: _MESSAGES["invalid_api_key"],
            403: _MESSAGES["permission_denied"],
            404: _MESSAGES["model_not_found"],
            429: "OpenAI informó de un límite de cuota o frecuencia. Revisa saldo y límites antes de reintentar.",
            500: _MESSAGES["server_error"],
            503: _MESSAGES["server_is_overloaded"],
        }.get(status, "OpenAI interrumpió la respuesta sin una causa reconocida. No se reintentó automáticamente.")
    param = error.get("param")
    if code in {"unsupported_parameter", "unsupported_value", "invalid_value"} and isinstance(param, str) and param in _PARAMS:
        text += f" Parámetro: {param}."
    return OpenAIRequestError(text, code=code, status=status)
