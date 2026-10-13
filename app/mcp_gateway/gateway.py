"""The tool gateway: the ONLY way the AI layer reaches product systems.

For one AI run it opens one MCP session to the right product server, discovers the server's tools, exposes only the
allowlisted ones, and for every call: checks the allowlist and the call budget, swaps masked placeholders in the
arguments for the real values (server side: the model never sees them), calls the tool, masks the result again, and
returns an audit detail. It cannot call anything that is not allowlisted, and the mock servers have no write tools.
"""
import asyncio
import importlib
import os
import re
import time
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from app.ai.masking import Masker
from app.mcp_gateway import registry as default_registry
from app.mcp_gateway.registry import ServerConfig

MAX_RESULT_CHARS = 4000
RESOLVABLE_KINDS = {"EMAIL", "PHONE", "ACCOUNT"}  # card numbers are never passed to any tool
_TOKEN = re.compile(r"\[(EMAIL|PHONE|CARD|ACCOUNT)_\d+\]")


class ToolsUnavailable(Exception):
    """No tools for this tenant/product (not mapped, unknown product, server unreachable). Safe to show."""


@dataclass
class ToolOutcome:
    text: str  # what the model sees: masked and truncated
    is_error: bool
    denied: bool  # refused by the gateway itself (the tool was not called)
    detail: dict[str, Any]  # what is logged on the run: arguments as the model wrote them (placeholders), masked result


@dataclass
class ToolSession:
    config: ServerConfig
    client: Any  # an mcp ClientSession
    tools: dict[str, Any]  # exposed (allowlisted AND offered by the server) tools by name
    blocked: list[str]  # offered by the server but not allowlisted: invisible to the model
    missing: list[str]  # allowlisted but not offered by the server
    max_calls: int
    timeout_seconds: float
    calls_made: int = 0
    log: list[dict[str, Any]] = field(default_factory=list)

    def definitions(self) -> list[dict[str, Any]]:
        """Tool definitions in the shape the model API expects."""
        return [
            {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
            for t in self.tools.values()
        ]

    async def call(self, name: str, arguments: dict[str, Any], masker: Masker) -> ToolOutcome:
        base = {"server": self.config.name, "tool": name, "arguments": _mask_tree(arguments, masker)}

        def denied(reason: str) -> ToolOutcome:
            return ToolOutcome(text=f"Error: {reason}", is_error=True, denied=True, detail={**base, "denied": reason})

        if name not in self.tools:
            return denied(f"tool {name!r} is not available")
        if self.calls_made >= self.max_calls:
            return denied(f"tool call limit ({self.max_calls}) reached for this request")
        resolved, problem = resolve_arguments(arguments, masker.mapping)
        if problem:
            return denied(problem)

        self.calls_made += 1
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(self.client.call_tool(name, resolved), timeout=self.timeout_seconds)
            text = "\n".join(getattr(block, "text", "") for block in result.content)
            is_error = bool(result.isError)
        except asyncio.TimeoutError:
            text, is_error = f"the tool did not answer within {self.timeout_seconds:.0f} seconds", True
        except Exception as exc:  # noqa: BLE001 -- a broken tool must never break the run
            text, is_error = f"the tool failed: {type(exc).__name__}", True

        # The result goes back through the SAME masker: real emails/phones/account numbers become placeholders.
        masked = masker.mask(text)
        if len(masked) > MAX_RESULT_CHARS:
            masked = masked[:MAX_RESULT_CHARS] + "... [truncated]"
        latency_ms = int((time.perf_counter() - started) * 1000)
        detail = {**base, "is_error": is_error, "result": masked, "latency_ms": latency_ms}
        return ToolOutcome(text=masked if not is_error else f"Error: {masked}", is_error=is_error, denied=False, detail=detail)


def _mask_tree(value: Any, masker: Masker) -> Any:
    """Mask every string in a nested structure, so what is logged never holds a raw sensitive value."""
    if isinstance(value, dict):
        return {k: _mask_tree(v, masker) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_tree(v, masker) for v in value]
    return masker.mask(value) if isinstance(value, str) else value


def resolve_arguments(arguments: Any, mapping: dict[str, str]) -> tuple[Any, str | None]:
    """Replace masked placeholders in tool arguments with the real values (kept server-side). Returns (arguments,
    problem); `problem` is set when an argument uses a placeholder kind that must never reach a tool (card numbers)."""
    problem: list[str] = []

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, str):

            def swap(match: re.Match) -> str:
                if match.group(1) not in RESOLVABLE_KINDS:
                    problem.append(f"{match.group(1).lower()} numbers are never sent to tools")
                    return match.group(0)
                return mapping.get(match.group(0), match.group(0))  # an unknown placeholder stays as written

            return _TOKEN.sub(swap, value)
        return value

    resolved = walk(arguments)
    return resolved, (problem[0] if problem else None)


@asynccontextmanager
async def _connect(config: ServerConfig) -> AsyncIterator[Any]:
    if config.transport == "inprocess":
        from mcp.shared.memory import create_connected_server_and_client_session

        module_name, _, attr = config.target.partition(":")
        server = getattr(importlib.import_module(module_name), attr)
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            yield client
    else:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        token = os.environ.get(config.auth_env, "") if config.auth_env else ""
        headers = {"Authorization": f"Bearer {token}"} if token else None
        async with streamablehttp_client(config.target, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                yield client


class ToolGateway:
    def __init__(
        self,
        servers: dict[str, ServerConfig] | None = None,
        tenant_products: dict[str, tuple[str, ...]] | None = None,
        *,
        max_calls: int = 4,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.servers = default_registry.SERVERS if servers is None else servers
        self.tenant_products = default_registry.TENANT_PRODUCTS if tenant_products is None else tenant_products
        self.max_calls = max_calls
        self.timeout_seconds = timeout_seconds

    @asynccontextmanager
    async def open(self, tenant_id: str | None, product: str | None) -> AsyncIterator[ToolSession]:
        """Open a session for this tenant + product, or raise ToolsUnavailable with the reason."""
        if not tenant_id or not product:
            raise ToolsUnavailable("no tenant or product on this message")
        if product not in self.tenant_products.get(tenant_id, ()):
            raise ToolsUnavailable(f"tenant {tenant_id!r} is not mapped to product {product!r}")
        config = self.servers.get(product)
        if config is None:
            raise ToolsUnavailable(f"no tool server is registered for product {product!r}")
        stack = AsyncExitStack()
        try:
            # Only the connect + discovery phase is guarded: an error raised later, inside the caller's `async with`
            # body, must propagate as itself and not be mistaken for "tools unavailable".
            client = await stack.enter_async_context(_connect(config))
            offered = {t.name: t for t in (await client.list_tools()).tools}
        except Exception as exc:  # noqa: BLE001 -- unreachable server, missing module, bad handshake...
            await stack.aclose()
            raise ToolsUnavailable(f"tool server for {product!r} is unavailable: {type(exc).__name__}") from exc
        allowed = set(config.allowed_tools)
        try:
            yield ToolSession(
                config=config,
                client=client,
                tools={n: t for n, t in offered.items() if n in allowed},
                blocked=sorted(n for n in offered if n not in allowed),
                missing=sorted(n for n in allowed if n not in offered),
                max_calls=self.max_calls,
                timeout_seconds=self.timeout_seconds,
            )
        finally:
            await stack.aclose()
