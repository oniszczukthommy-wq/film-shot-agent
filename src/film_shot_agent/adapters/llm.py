"""OpenAI-compatible chat client with tool calling.

DeepSeek, Moonshot, Qwen and OpenAI all speak this shape. We keep the client tiny so the
research service owns the loop, the retries and the evidence policy.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import httpx

from film_shot_agent.core.config import Settings, get_settings


class LLMError(RuntimeError):
    """The model call failed. The message never contains a key or a request URL."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatResult:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def assistant_message(self) -> dict:
        message: dict = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in self.tool_calls
            ]
        return message


class LLMClient:
    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None):
        self.settings = settings or get_settings()
        self._client = client

    @property
    def available(self) -> bool:
        return self.settings.has_llm

    def chat(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 1600,
    ) -> ChatResult:
        if not self.available:
            raise LLMError("模型未配置。")
        payload: dict = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                data = self._post(payload)
                return _parse_chat(data)
            except LLMError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.6 * (attempt + 1))
        raise LLMError(str(last_error) if last_error else "模型调用失败。")

    def _post(self, payload: dict) -> dict:
        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key.strip()}",
            "Content-Type": "application/json",
        }
        client = self._client or httpx.Client()
        try:
            response = client.post(
                url, json=payload, headers=headers, timeout=self.settings.llm_timeout
            )
        except httpx.TimeoutException as exc:
            raise LLMError("模型响应超时。") from exc
        except httpx.HTTPError as exc:
            raise LLMError("模型连接失败。") from exc
        if response.status_code >= 400:
            # Deliberately do not forward the provider body: it can echo the request URL.
            raise LLMError(f"模型返回错误（HTTP {response.status_code}）。")
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("模型返回了无法解析的内容。") from exc
        if not isinstance(data, dict) or not data.get("choices"):
            raise LLMError("模型没有返回结果。")
        return data


def _parse_chat(data: dict) -> ChatResult:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    if not isinstance(content, str):
        content = str(content)
    calls: list[ToolCall] = []
    for raw in message.get("tool_calls") or []:
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") or {}
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        arguments = _parse_arguments(function.get("arguments"))
        calls.append(ToolCall(id=str(raw.get("id") or name), name=name, arguments=arguments))
    usage = data.get("usage") or {}
    return ChatResult(
        content=content,
        tool_calls=calls,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
    )


def _parse_arguments(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
