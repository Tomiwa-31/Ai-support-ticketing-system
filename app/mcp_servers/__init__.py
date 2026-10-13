"""MOCK MCP SERVERS: fake data, read-only tools, for the demo only.

Credipay, FinSaaS and FinSaaS Lending expose governed interfaces through MCP, but we have no access to the real ones
yet. These stand-ins speak the real MCP protocol, so replacing a mock with the real server is a CONFIGURATION change in
app/mcp_gateway/registry.py (point the entry at the real endpoint), not a code change.

Everything here is invented: names, balances, references and the TOOL NAMES themselves (they are guesses and must be
confirmed against the real interfaces once access exists). No server here has a write tool, by design.
"""
