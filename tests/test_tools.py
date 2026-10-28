"""Unit tests over a fake GLPI REST API (httpx.MockTransport): no Docker needed."""

import json

import httpx
import pytest

from glpi_mcp import tools
from glpi_mcp.client import GLPI, GLPIError

USERS = [{"id": 1, "name": "claude", "firstname": "Claude", "realname": "Connector"},
         {"id": 10, "name": "hana.saleh", "firstname": "Hana", "realname": "Saleh"},
         {"id": 14, "name": "layla.mansour", "firstname": "Layla", "realname": "Mansour"}]
TICKET = {"id": 1, "name": "VPN drops every 10 minutes", "status": 2, "priority": 5, "type": 1,
          "date": "2026-10-28 08:00:00", "time_to_resolve": "2026-10-28 09:00:00", "content": "&lt;p&gt;VPN drops&lt;/p&gt;"}


class Fake:
    def __init__(self):
        self.ticket = dict(TICKET)
        self.groups = [{"id": 5, "tickets_id": 1, "groups_id": "Service desk", "type": 2}]
        self.writes: list[tuple[str, str, dict | None]] = []
        self.sessions = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.removeprefix("/apirest.php/")
        if path == "initSession":
            self.sessions += 1
            return httpx.Response(200, json={"session_token": "s"})
        if req.method in ("POST", "PUT", "DELETE"):
            body = json.loads(req.content)["input"] if req.content else None
            self.writes.append((req.method, path, body))
            if path == "Group_Ticket" and req.method == "POST":
                self.groups = [{"id": 6, "tickets_id": 1, "groups_id": "Network team", "type": 2}]
            return httpx.Response(200, json={"id": 99})
        rng = req.url.params.get("range", "0-199")
        first_page = rng.startswith("0-")
        routes = {
            "User": USERS if first_page else [],
            "Ticket": [self.ticket] if first_page else [],
            "Ticket/1": self.ticket,
            "Ticket/1/Ticket_User": [{"users_id": "layla.mansour", "type": 1}, {"users_id": "hana.saleh", "type": 2}],
            "Ticket/1/Group_Ticket": self.groups,
            "Ticket/1/Item_Ticket": [],
            "Ticket/1/ITILFollowup": [{"users_id": "hana.saleh", "is_private": 1, "date": "x", "content": "Logs point to the firewall"}],
            "Group": [{"id": 1, "name": "Service desk"}, {"id": 2, "name": "Network team"}] if first_page else [],
            "Profile_User": [{"users_id": 10, "profiles_id": 6}] if first_page else [],
        }
        if path in routes:
            return httpx.Response(200, json=routes[path])
        if path == "Ticket/404":
            return httpx.Response(404, json=["ERROR_ITEM_NOT_FOUND", "Item not found"])
        return httpx.Response(200, json=[])


@pytest.fixture
def fake():
    return Fake()


def api(fake: Fake) -> GLPI:
    return GLPI("http://glpi.test", "claude", "pw", transport=httpx.MockTransport(fake))


def test_needs_a_login(monkeypatch):
    monkeypatch.delenv("GLPI_LOGIN", raising=False)
    monkeypatch.delenv("GLPI_PASSWORD", raising=False)
    with pytest.raises(GLPIError):
        GLPI("http://glpi.test", "", "")


def test_errors_carry_glpis_message(fake):
    with pytest.raises(GLPIError, match="Item not found"):
        api(fake).get("Ticket/404")


def test_ticket_reads_people_groups_and_lateness(fake):
    a = api(fake)
    t = tools.ticket_of(a, TICKET, tools._people(a))
    assert (t.priority, t.status, t.requester, t.technicians, t.groups) == ("very high", "assigned", "Layla Mansour", ["Hana Saleh"], ["Service desk"])
    assert t.late  # due 09:00 on 28 Oct 2026, long past


def test_get_ticket_unescapes_glpi_html(fake):
    d = tools.get_ticket(api(fake), 1)
    assert d.description == "VPN drops" and d.follow_ups[0].private


def test_followup_changes_nothing_without_a_code(fake):
    c = tools.add_followup(api(fake), 1, "Check the gateway.")
    assert not c.done and c.confirmation and "technicians only" in c.summary and fake.writes == []


def test_followup_with_the_code_is_private_and_marked(fake):
    a = api(fake)
    code = tools.add_followup(a, 1, "Check the gateway.").confirmation
    assert tools.add_followup(a, 1, "Check the gateway.", confirmation=code).done
    (method, path, body), = fake.writes
    assert (method, path, body["is_private"]) == ("POST", "ITILFollowup", 1) and tools.NOTE in body["content"]
    assert not tools.add_followup(a, 1, "Check the gateway.", confirmation=code).done  # used once


def test_a_code_only_fits_its_own_request(fake):
    a = api(fake)
    code = tools.add_followup(a, 1, "Check the gateway.").confirmation
    assert not tools.add_followup(a, 1, "Check the gateway.", private=False, confirmation=code).done
    assert not tools.update_ticket(a, 1, group="Network", confirmation=code).done
    assert fake.writes == []


def test_reassign_replaces_the_group(fake):
    a = api(fake)
    p = tools.update_ticket(a, 1, group="Network")
    assert "Network team (from Service desk)" in p.summary and fake.writes == []
    d = tools.update_ticket(a, 1, group="Network", confirmation=p.confirmation)
    assert d.done and d.ticket.groups == ["Network team"]
    assert [(m, pth) for m, pth, _ in fake.writes] == [("DELETE", "Group_Ticket/5"), ("POST", "Group_Ticket")]


def test_only_technicians_can_be_assigned(fake):
    assert "no technician" in tools.update_ticket(api(fake), 1, technician="Layla").problem
    assert "Nothing to change" in tools.update_ticket(api(fake), 1).problem


def test_an_expired_code_is_refused(fake, monkeypatch):
    a = api(fake)
    code = tools.update_ticket(a, 1, priority="major").confirmation
    monkeypatch.setattr(tools, "CONFIRM_TTL_S", -1)
    assert not tools.update_ticket(a, 1, priority="major", confirmation=code).done
    assert fake.writes == []


def test_signs_in_once(fake):
    a = api(fake)
    a.get("User")
    a.get("Ticket")
    assert fake.sessions == 1
