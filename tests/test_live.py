"""Against the local GLPI with the SAMPLE helpdesk (scripts/reset.sh). Skipped when it isn't running.

Run: uv run --env-file .env pytest tests/test_live.py
"""

import os

import httpx
import pytest

from glpi_mcp import tools
from glpi_mcp.client import GLPI


def _up() -> bool:
    try:
        return bool(os.environ.get("GLPI_PASSWORD")) and httpx.get(
            os.environ.get("GLPI_URL", "http://127.0.0.1:8095") + "/", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="local GLPI not running (scripts/up.sh)")


@pytest.fixture(scope="module")
def api():
    return GLPI()


def test_the_seeded_desk_needs_attention(api):
    n = tools.needs_attention(api)
    assert any(t.priority == "major" for t in n.unassigned) and len(n.late) == 2 and n.waiting_on_requester


def test_saras_laptop_is_in_repair_with_its_ticket(api):
    p = tools.person_overview(api, "Sara Al-Qahtani")
    lap = next(a for a in p.assets if a.name == "LAP-0140")
    assert lap.state == "In repair" and lap.open_tickets


def test_private_followup_on_a_solved_ticket(api):
    t = tools.find_tickets(api, "finance share", status="closed").tickets[0]
    p = tools.add_followup(api, t.id, "Live test follow-up.")
    assert tools.add_followup(api, t.id, "Live test follow-up.", confirmation=p.confirmation).done
    last = tools.get_ticket(api, t.id).follow_ups[-1]
    assert last.private and tools.NOTE in last.text
