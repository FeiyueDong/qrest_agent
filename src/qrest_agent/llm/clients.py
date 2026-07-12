from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class LLMResponse:
    text: str
    raw: dict[str, Any] | None = None


class BaseLLMClient(Protocol):
    model: str

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


class OllamaClient:
    def __init__(self, model: str, base_url: str = "http://localhost:11434", retries: int = 1) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.retries = retries

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
        data = _post_json(f"{self.base_url}/api/chat", payload, retries=self.retries)
        content = data.get("message", {}).get("content", "{}")
        return _parse_json_object(content)


class OllamaCliClient:
    def __init__(self, model: str) -> None:
        self.model = model

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        prompt = "\n\n".join(f"{message['role'].upper()}:\n{message['content']}" for message in messages)
        completed = subprocess.run(
            ["ollama", "run", self.model, prompt],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"ollama run failed: {completed.stderr}")
        return _parse_json_object(_strip_ansi(completed.stdout))


class OpenAICompatibleClient:
    def __init__(self, model: str, api_key: str, base_url: str, retries: int = 1) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.retries = retries

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        data = _post_json(
            f"{self.base_url}/chat/completions",
            payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
            retries=self.retries,
        )
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        return _parse_json_object(content)


def _post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    retries: int = 0,
    timeout: int = 120,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    attempts = max(0, retries) + 1
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(
                f"LLM request failed: HTTP {exc.code} {exc.reason}; attempt={attempt}/{attempts}; detail={detail}"
            )
        except urllib.error.URLError as exc:
            last_error = RuntimeError(f"LLM request failed: {exc}; attempt={attempt}/{attempts}")
        if attempt < attempts:
            time.sleep(min(0.2 * attempt, 1.0))
    assert last_error is not None
    raise last_error


def _parse_json_object(content: str) -> dict[str, Any]:
    content = _strip_ansi(content).strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        extracted = _extract_json_object(content)
        if extracted is None:
            repaired = _repair_common_json_issues(content)
            try:
                parsed = json.loads(repaired, strict=False)
            except json.JSONDecodeError:
                raise ValueError(f"model did not return valid JSON: {content}") from exc
            if not isinstance(parsed, dict):
                raise ValueError("model JSON response must be an object")
            return parsed
        try:
            parsed = json.loads(extracted)
        except json.JSONDecodeError as nested_exc:
            repaired = _repair_common_json_issues(extracted)
            try:
                parsed = json.loads(repaired, strict=False)
            except json.JSONDecodeError:
                raise ValueError(f"model did not return valid JSON: {content}") from nested_exc
    if not isinstance(parsed, dict):
        raise ValueError("model JSON response must be an object")
    return parsed


def _extract_json_object(content: str) -> str | None:
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.DOTALL)
    if fence_match:
        return fence_match.group(1)

    start = content.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(content)):
        char = content[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start : index + 1]
    return None


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)


def _repair_common_json_issues(content: str) -> str:
    repaired = re.sub(r'("confidence"\s*:\s*)([0-9]+(?:\.[0-9]+)?)"', r"\1\2", content)
    return repaired
