"""The model seam. Everything else talks to `LLMClient`; only this file knows about the Anthropic SDK."""
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from anthropic import AsyncAnthropic

from app.config import settings

logger = logging.getLogger(__name__)

# (tool name, arguments the model wrote) -> (text for the model, is_error). Supplied by the caller, so the gateway,
# masking and audit stay outside this file.
ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[tuple[str, bool]]]

MAX_TOOL_ROUNDS = 5  # model turns that may ask for tools; after that the model must answer


class LLMError(Exception):
    """The model call failed or produced nothing usable. The message is safe to store and show to an agent."""


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int  # summed over every model turn of the call (a tool round trip is more than one turn)
    output_tokens: int
    tool_rounds: int = 0


class LLMClient(Protocol):
    model: str

    async def complete(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
        execute_tool: ToolExecutor | None = None,
    ) -> LLMResult: ...


class AnthropicLLM:
    def __init__(self, api_key: str, model: str, max_tokens: int, workspace_id: str = "") -> None:
        self.model = model
        self._max_tokens = max_tokens
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self._client = AsyncAnthropic(api_key=api_key, default_headers=headers)

    async def _turn(self, *, system: str, messages: list[dict[str, Any]], schema: dict[str, Any], tools, no_more_tools: bool):
        kwargs: dict[str, Any] = {}
        if tools:
            kwargs["tools"] = tools
            if no_more_tools:
                kwargs["tool_choice"] = {"type": "none"}  # not a forced tool call: just "answer now"
        try:
            return await self._client.beta.messages.create(
                model=self.model,
                max_tokens=self._max_tokens,
                system=system,
                messages=messages,
                # Structured output: the final reply is JSON matching the schema (no forced tool_choice on this model).
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},  # if a safety classifier declines, retry on the fallback model
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001 -- SDK errors carry no prompt text; keep only the type and message
            logger.exception("anthropic call failed")
            raise LLMError(f"model call failed: {type(exc).__name__}: {exc}") from exc

    async def complete(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
        execute_tool: ToolExecutor | None = None,
    ) -> LLMResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        tools = tools if (tools and execute_tool) else None
        input_tokens = output_tokens = rounds = 0

        while True:
            response = await self._turn(
                system=system, messages=messages, schema=schema, tools=tools, no_more_tools=rounds >= MAX_TOOL_ROUNDS
            )
            input_tokens += response.usage.input_tokens
            output_tokens += response.usage.output_tokens

            if response.stop_reason == "refusal":
                raise LLMError("the model declined to answer this request")
            if response.stop_reason == "max_tokens":
                raise LLMError("the model's answer was cut off (max_tokens)")

            if response.stop_reason == "tool_use" and tools:
                rounds += 1
                # The assistant turn goes back exactly as received (thinking blocks included), then ALL the tool
                # results in one user message, as the API expects.
                messages.append({"role": "assistant", "content": response.content})
                results = []
                for block in response.content:
                    if block.type == "tool_use":
                        text, is_error = await execute_tool(block.name, dict(block.input))
                        results.append(
                            {"type": "tool_result", "tool_use_id": block.id, "content": text, "is_error": is_error}
                        )
                messages.append({"role": "user", "content": results})
                continue

            text = next((block.text for block in response.content if block.type == "text"), "")
            if not text.strip():
                raise LLMError("the model returned no text")
            return LLMResult(
                text=text, model=response.model, input_tokens=input_tokens, output_tokens=output_tokens,
                tool_rounds=rounds,
            )


_override: LLMClient | None = None


def set_client(client: LLMClient | None) -> None:
    """Swap the model client (tests use a fake). Pass None to restore the real one."""
    global _override
    _override = client


def get_client() -> LLMClient:
    if _override is not None:
        return _override
    if not settings.anthropic_api_key:
        raise LLMError("ANTHROPIC_API_KEY is not set")
    return AnthropicLLM(
        settings.anthropic_api_key, settings.ai_model, settings.ai_max_output_tokens, settings.anthropic_workspace_id
    )
