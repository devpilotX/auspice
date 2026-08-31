"""The language model client.

Thin on purpose. Section 7.2 rejects LangChain and agent frameworks outright: abstraction over an
API you must understand precisely, where the debugging cost exceeds the saved code. So this is
direct provider calls plus JSON Schema validation, and nothing else.

Three behaviours worth naming.

**No key means no output.** If no provider is configured, ``complete_structured`` raises
``StageUnavailableError``. It does not return an empty list. A stage that silently produces nothing
looks identical to a stage that found nothing, and in a corpus those two things must never be
confused.

**Schema violations are retried, then recorded.** The model is told what it got wrong and asked
again. After ``llm_max_attempts`` the failure is recorded with the raw response, so a systematic
schema problem is visible rather than showing up as a thin county.

**Everything is cached by content hash and prompt version.** The cache key covers the document, the
schema version, the prompt fingerprint and the model name. Changing a prompt invalidates exactly
the work that depended on it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import httpx
from jsonschema import Draft202012Validator
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from auspice.config import Settings, get_settings
from auspice.errors import SchemaViolationError, StageUnavailableError
from auspice.logging import get_logger
from auspice.pipeline.extract.prompts import Prompt

log = get_logger(__name__, _stage="extract")

ANTHROPIC_VERSION = "2023-06-01"


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens
        )


@dataclass(slots=True)
class Completion:
    payload: dict[str, Any]
    usage: Usage
    model: str
    attempts: int
    raw: dict[str, Any] = field(default_factory=dict)


def cache_key(
    *,
    document_id: str,
    schema_name: str,
    schema_version: str,
    prompt: Prompt,
    model: str,
    extra: str = "",
) -> str:
    """SHA-256 over everything that could change the answer.

    The document id is already a content hash, so identical bytes reaching an identical prompt and
    an identical schema produce an identical key. That is the whole cost control story from section
    7.5, and it is usually a five to ten times saving.
    """
    digest = hashlib.sha256()
    for part in (document_id, schema_name, schema_version, prompt.fingerprint, model, extra):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()


class LanguageModel:
    """One provider, two tiers.

    ``frontier`` is used where accuracy determines everything downstream: structured extraction of
    decisions, and reasoning over conflicting evidence. ``cheap`` is used for triage and closed
    label classification, which is roughly ninety percent of the volume.
    """

    def __init__(
        self, settings: Settings | None = None, *, client: httpx.Client | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=180.0, follow_redirects=False)

    def __enter__(self) -> LanguageModel:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @property
    def available(self) -> bool:
        return self.settings.llm_configured

    def model_for(self, tier: str) -> str:
        if tier == "frontier":
            return self.settings.llm_frontier_model
        if tier == "cheap":
            return self.settings.llm_cheap_model
        raise ValueError(f"unknown tier: {tier}")

    def _require_available(self) -> None:
        if not self.available:
            raise StageUnavailableError(
                "no language model is configured, so extraction cannot run. Set "
                "AUSPICE_LLM_PROVIDER and AUSPICE_LLM_API_KEY. Until then the pipeline reports "
                "this stage as unavailable rather than returning empty results, because an empty "
                "result and a missing key are different things and a corpus must not confuse them."
            )

    def complete_structured(
        self,
        *,
        prompt: Prompt,
        schema: dict[str, Any],
        variables: dict[str, object],
        tier: str = "frontier",
        temperature: float = 0.0,
        max_tokens: int = 8192,
    ) -> Completion:
        """One call, validated against ``schema``, retried on violation."""
        self._require_available()
        model = self.model_for(tier)
        validator = Draft202012Validator(schema)

        user_message = prompt.render(**variables)
        errors: list[str] = []
        total = Usage()

        for attempt in range(1, self.settings.llm_max_attempts + 1):
            message = user_message
            if errors:
                message = (
                    user_message
                    + "\n\nYour previous answer did not satisfy the schema. Problems:\n"
                    + "\n".join(f"- {e}" for e in errors[-6:])
                    + "\n\nReturn only valid JSON matching the schema."
                )

            raw, usage = self._call_provider(
                system=prompt.system,
                user=message,
                schema=schema,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            total = total + usage

            try:
                payload = _extract_json(raw)
            except ValueError as exc:
                errors = [str(exc)]
                log.warning("model returned unparseable output", attempt=attempt, error=str(exc))
                continue

            found = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
            if not found:
                return Completion(
                    payload=payload, usage=total, model=model, attempts=attempt, raw=raw
                )

            errors = [f"{'.'.join(str(p) for p in e.path) or 'root'}: {e.message}" for e in found]
            log.warning("schema violation", attempt=attempt, problems=errors[:4])

        raise SchemaViolationError(
            f"model failed to satisfy {schema.get('title', 'the schema')} after "
            f"{self.settings.llm_max_attempts} attempts",
            errors=errors,
        )

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential_jitter(initial=4.0, max=120.0),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _call_provider(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> tuple[dict[str, Any], Usage]:
        provider = self.settings.llm_provider
        if provider == "anthropic":
            return self._call_anthropic(
                system=system,
                user=user,
                schema=schema,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        if provider == "openai":
            return self._call_openai(
                system=system,
                user=user,
                schema=schema,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        raise StageUnavailableError(f"provider {provider} is not implemented")

    def _call_anthropic(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> tuple[dict[str, Any], Usage]:
        base = self.settings.llm_base_url or "https://api.anthropic.com"
        # A tool with the schema as its input contract is how Anthropic enforces structure.
        # tool_choice forces the model to use it, so there is no prose to parse out.
        response = self._client.post(
            f"{base}/v1/messages",
            headers={
                "x-api-key": self.settings.llm_api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system,
                "tools": [
                    {
                        "name": "record",
                        "description": "Record the extracted facts.",
                        "input_schema": schema,
                    }
                ],
                "tool_choice": {"type": "tool", "name": "record"},
                "messages": [{"role": "user", "content": user}],
            },
        )
        response.raise_for_status()
        body = response.json()
        usage = Usage(
            input_tokens=int(body.get("usage", {}).get("input_tokens", 0)),
            output_tokens=int(body.get("usage", {}).get("output_tokens", 0)),
        )
        for block in body.get("content", []):
            if block.get("type") == "tool_use":
                return {"_tool_input": block.get("input", {})}, usage
        return {"_text": "".join(b.get("text", "") for b in body.get("content", []))}, usage

    def _call_openai(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> tuple[dict[str, Any], Usage]:
        base = self.settings.llm_base_url or "https://api.openai.com"
        response = self._client.post(
            f"{base}/v1/chat/completions",
            headers={
                "authorization": f"Bearer {self.settings.llm_api_key}",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "temperature": temperature,
                "max_completion_tokens": max_tokens,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": str(schema.get("title", "extraction")),
                        "schema": schema,
                        "strict": True,
                    },
                },
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        response.raise_for_status()
        body = response.json()
        usage = Usage(
            input_tokens=int(body.get("usage", {}).get("prompt_tokens", 0)),
            output_tokens=int(body.get("usage", {}).get("completion_tokens", 0)),
        )
        content = body["choices"][0]["message"]["content"]
        return {"_text": content}, usage


def _extract_json(raw: dict[str, Any]) -> dict[str, Any]:
    """Pull the structured payload out of a provider response."""
    if "_tool_input" in raw:
        payload = raw["_tool_input"]
        if not isinstance(payload, dict):
            raise TypeError("tool input was not an object")
        return payload

    text = str(raw.get("_text", "")).strip()
    if not text:
        raise ValueError("model returned no content")

    # Some providers wrap JSON in a fenced block even when asked not to.
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.startswith("```")]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model output was not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise TypeError("model output was valid JSON but not an object")
    return parsed
