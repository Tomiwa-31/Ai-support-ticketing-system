"""A stub MCP server for gateway tests. It deliberately offers tools the registry must NOT expose (a write tool), and
counts executions so tests can prove a refused call never reached the server."""
import asyncio

from mcp.server.fastmcp import FastMCP

stub = FastMCP("stub")
executions: list[str] = []


@stub.tool()
def echo(text: str) -> str:
    """Return the text it was given (what the tool actually received)."""
    executions.append("echo")
    return f"got:{text}"


@stub.tool()
def refund_payment(amount: float) -> str:
    """A WRITE tool. The allowlist must keep it invisible and uncallable."""
    executions.append("refund_payment")
    return f"refunded {amount}"


@stub.tool()
async def slow() -> str:
    """Takes longer than any test timeout."""
    await asyncio.sleep(0.6)
    return "done"


@stub.tool()
def boom() -> str:
    """Always fails."""
    raise ValueError("kaboom")


@stub.tool()
def big() -> str:
    """A very long answer."""
    return "x" * 10000


@stub.tool()
def reveal() -> str:
    """Returns sensitive-looking values, so tests can check results are masked."""
    return "Owner jamie@acme.com, phone +234 802 555 0147, account 0123456789, last4 6789"
