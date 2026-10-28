"""GLPI MCP server (Mojood Connect demo): ask about the IT helpdesk and assets in plain words, and add follow-ups or
reassign tickets with a confirmation step.

Run:  uv run --env-file .env glpi-mcp          → http://127.0.0.1:8006/mcp (Streamable HTTP)
      uv run --env-file .env glpi-mcp --stdio  → for Claude Desktop's config file

Settings (environment, written to .env by scripts/up.sh):
  GLPI_URL       the GLPI instance (default http://127.0.0.1:8095)
  GLPI_LOGIN, GLPI_PASSWORD  the GLPI user the server signs in as (it acts with that user's rights)
  GLPI_SAMPLE    "1" (default) says in every session that the data is SAMPLE
  GLPI_MCP_PORT  default 8006
"""

import logging
import os
import sys
from typing import Annotated, Literal

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from glpi_mcp import tools
from glpi_mcp.client import GLPI

SAMPLE = os.environ.get("GLPI_SAMPLE", "1") != "0"
_api: GLPI | None = None


def api() -> GLPI:
    global _api
    if _api is None:
        _api = GLPI()
    return _api


INSTRUCTIONS = f"""\
GLPI IT service management: helpdesk tickets (incidents and requests), their follow-ups, who asked and who works
them, and the IT assets (laptops, monitors, phones, scanners) each person holds.
{"This is a demo with SAMPLE data for a made-up company, Harbor Trading. " if SAMPLE else ""}\
Answer only from these tools; never guess a ticket, an asset or who owns something. Tickets are numbered (e.g. 1).
add_followup and update_ticket change real tickets. Call one without `confirmation` first: it changes nothing and
returns what it would do plus a code. Show the user that summary and ask them to confirm. Only after they say yes,
call again with the same arguments and the code. Never confirm on the user's behalf. If a tool returns `problem`,
nothing changed: tell the user why. Follow-ups are private to technicians unless the user asks for the requester to
see one."""

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
CHANGE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

server = MCPServer(
    name="glpi-mcp",
    title="GLPI",
    description="IT helpdesk and assets in GLPI: find and read tickets, who holds what, what needs attention, follow-ups and reassignment.",
    instructions=INSTRUCTIONS,
    website_url="https://mojood.app/connect",
    version="0.1.0",
)


@server.tool(title="Find tickets", annotations=READ)
def find_tickets(
    query: Annotated[str | None, Field(description='words from the title or description, e.g. "VPN"')] = None,
    status: Annotated[Literal["open", "closed", "all"], Field(description="open includes new, assigned, planned and waiting")] = "open",
    technician: Annotated[str | None, Field(description="a technician's name")] = None,
    group: Annotated[str | None, Field(description='an assigned group, e.g. "Network team"')] = None,
) -> tools.Tickets:
    """Find tickets, highest priority first, with status, priority, requester, technicians, groups, deadline and
    linked assets."""
    return tools.find_tickets(api(), query, status, technician, group)


@server.tool(title="Read a ticket", annotations=READ)
def get_ticket(ticket_id: Annotated[int, Field(description="e.g. 1")]) -> tools.Detail:
    """One ticket with its description and every follow-up in order, private ones marked."""
    return tools.get_ticket(api(), ticket_id)


@server.tool(title="A person's assets and tickets", annotations=READ)
def person_overview(person: Annotated[str, Field(description='a name, e.g. "Sara"')]) -> tools.Holdings:
    """The assets a person holds (with their state, and any open ticket about each) and the open tickets they asked
    for. If the name matches several people, returns them as candidates: ask which."""
    return tools.person_overview(api(), person)


@server.tool(title="What needs attention", annotations=READ)
def needs_attention() -> tools.Attention:
    """Open tickets with no owner, tickets past their time to resolve, high-priority ones, and those waiting on the
    requester."""
    return tools.needs_attention(api())


@server.tool(title="Add a follow-up", annotations=CHANGE)
def add_followup(
    ticket_id: Annotated[int, Field(description="e.g. 1")],
    text: Annotated[str, Field(description="the follow-up")],
    private: Annotated[bool, Field(description="true (default): technicians only; false: the requester sees it")] = True,
    confirmation: Annotated[str | None, Field(description="leave empty first; pass the code only after the user confirms")] = None,
) -> tools.Change:
    """Add a follow-up to a ticket. The first call changes nothing and returns a summary and a confirmation code; the
    follow-up is added only on a second call with the code, after the user has said yes."""
    return tools.add_followup(api(), ticket_id, text, private, confirmation)


@server.tool(title="Update a ticket", annotations=CHANGE)
def update_ticket(
    ticket_id: Annotated[int, Field(description="e.g. 1")],
    group: Annotated[str | None, Field(description="reassign to this group, replacing the assigned group")] = None,
    technician: Annotated[str | None, Field(description="add this technician")] = None,
    priority: Annotated[Literal["very low", "low", "medium", "high", "very high", "major"] | None, Field(description="new priority")] = None,
    confirmation: Annotated[str | None, Field(description="leave empty first; pass the code only after the user confirms")] = None,
) -> tools.Change:
    """Reassign a ticket to a group, add a technician, or change its priority. The first call changes nothing and
    returns a summary and a confirmation code; the change happens only on a second call with the code, after the user
    has said yes."""
    return tools.update_ticket(api(), ticket_id, group, technician, priority, confirmation)


def app():
    security = TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
    )
    # Stateful sessions: a confirmation code must reach the same server process that issued it.
    return server.streamable_http_app(json_response=True, transport_security=security)


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per GLPI call is noise in a client's log
    if "--stdio" in sys.argv:
        server.run("stdio")
        return
    uvicorn.run(app(), host="127.0.0.1", port=int(os.environ.get("GLPI_MCP_PORT", "8006")), log_level="info",
                timeout_graceful_shutdown=5)
