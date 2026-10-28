"""The six tools, as plain functions over a GLPI client (the MCP wiring is in server.py).

Four only read. The two that change something (add a follow-up, update a ticket) never act on the first call: they
return a preview and a one-time confirmation code, and act only when called again with that code and the same
request. Follow-ups are private (technicians only) unless asked otherwise, and GLPI records every change in the
ticket's history under the signed-in user.
"""

import secrets
import time
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from glpi_mcp.client import GLPI, GLPIError

NOTE = "via Claude (Mojood Connect demo)"
CONFIRM_TTL_S = 10 * 60
STATUS = {1: "new", 2: "assigned", 3: "planned", 4: "waiting", 5: "solved", 6: "closed"}
OPEN = {1, 2, 3, 4}
PRIORITY = {1: "very low", 2: "low", 3: "medium", 4: "high", 5: "very high", 6: "major"}
TYPE = {1: "incident", 2: "request"}
ASSET_KINDS = ("Computer", "Monitor", "Phone", "Peripheral")


def _people(api: GLPI) -> dict[str, str]:
    """login → "First Last"."""
    return {u["name"]: f"{u.get('firstname') or ''} {u.get('realname') or ''}".strip() or u["name"]
            for u in api.all("User")}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _hours(since: str | None) -> float | None:
    if not since:
        return None
    t = datetime.strptime(since, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    return round((datetime.now(UTC) - t).total_seconds() / 3600, 1)


class Ticket(BaseModel):
    id: int
    title: str
    type: str
    status: str
    priority: str
    requester: str | None = None
    technicians: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list, description="the groups it's assigned to")
    opened: str | None = None
    due: str | None = Field(None, description="time to resolve")
    late: bool = Field(False, description="open and past its time to resolve")
    assets: list[str] = Field(default_factory=list, description="assets linked to the ticket")
    link: str | None = None


def ticket_of(api: GLPI, t: dict, names: dict[str, str]) -> Ticket:
    tu = api.get(f"Ticket/{t['id']}/Ticket_User", expand_dropdowns="true") or []
    gt = api.get(f"Ticket/{t['id']}/Group_Ticket", expand_dropdowns="true") or []
    it = api.get(f"Ticket/{t['id']}/Item_Ticket", expand_dropdowns="true") or []
    due = t.get("time_to_resolve")
    return Ticket(
        id=t["id"], title=t["name"], type=TYPE.get(t.get("type"), "ticket"), status=STATUS.get(t["status"], str(t["status"])),
        priority=PRIORITY.get(t["priority"], str(t["priority"])),
        requester=next((names.get(x["users_id"], x["users_id"]) for x in tu if x["type"] == 1), None),
        technicians=[names.get(x["users_id"], x["users_id"]) for x in tu if x["type"] == 2],
        groups=[x["groups_id"] for x in gt if x["type"] == 2],
        opened=t.get("date"), due=due, late=bool(due and t["status"] in OPEN and due < _now()),
        assets=[x["items_id"] for x in it], link=f"{api.url}/front/ticket.form.php?id={t['id']}",
    )


def _ticket(api: GLPI, tid: int) -> dict | None:
    try:
        return api.get(f"Ticket/{int(tid)}")
    except (GLPIError, ValueError):
        return None


# ---------- read ----------

class Tickets(BaseModel):
    tickets: list[Ticket]
    total: int


def find_tickets(api: GLPI, query: str | None = None, status: str = "open", technician: str | None = None,
                 group: str | None = None) -> Tickets:
    rows = api.all("Ticket")
    keep = {"open": lambda s: s in OPEN, "closed": lambda s: s in (5, 6), "all": lambda s: True}[status if status in ("open", "closed", "all") else "open"]
    rows = [t for t in rows if keep(t["status"])]
    if query:
        q = query.lower()
        rows = [t for t in rows if q in t["name"].lower() or q in (t.get("content") or "").lower()]
    names = _people(api)
    out = [ticket_of(api, t, names) for t in sorted(rows, key=lambda t: (-t["priority"], t["date"]))]
    if technician:
        out = [t for t in out if any(technician.lower() in x.lower() for x in t.technicians)]
    if group:
        out = [t for t in out if any(group.lower() in x.lower() for x in t.groups)]
    return Tickets(tickets=out[:25], total=len(out))


class FollowUp(BaseModel):
    who: str
    when: str | None
    private: bool = Field(description="visible to technicians only")
    text: str


class Detail(BaseModel):
    ticket: Ticket | None = None
    description: str | None = None
    follow_ups: list[FollowUp] = Field(default_factory=list)
    problem: str | None = None


def _plain(html: str | None) -> str:
    import html as h
    import re
    return re.sub(r"\s+\n", "\n", re.sub(r"<[^>]+>", "", h.unescape(h.unescape(html or "")))).strip()[:800]


def get_ticket(api: GLPI, ticket_id: int) -> Detail:
    t = _ticket(api, ticket_id)
    if not t:
        return Detail(problem=f"No ticket has the id {ticket_id}.")
    names = _people(api)
    fus = api.get(f"Ticket/{t['id']}/ITILFollowup", expand_dropdowns="true") or []
    return Detail(ticket=ticket_of(api, t, names), description=_plain(t.get("content")),
                  follow_ups=[FollowUp(who=names.get(f["users_id"], f["users_id"]), when=f.get("date"),
                                       private=bool(f["is_private"]), text=_plain(f["content"])) for f in fus])


class Asset(BaseModel):
    name: str
    kind: str
    model: str | None = None
    state: str | None = None
    location: str | None = None
    serial: str | None = None
    open_tickets: list[str] = Field(default_factory=list, description="open tickets that name this asset")


class Holdings(BaseModel):
    person: str | None = None
    assets: list[Asset] = Field(default_factory=list)
    open_tickets: list[Ticket] = Field(default_factory=list, description="open tickets this person asked for")
    candidates: list[str] = Field(default_factory=list, description="when the name matched several people: ask which")
    problem: str | None = None


def person_overview(api: GLPI, person: str) -> Holdings:
    q = person.strip().lower()
    users = [u for u in api.all("User") if q in f"{u.get('firstname') or ''} {u.get('realname') or ''} {u['name']}".lower()
             and u["name"] not in ("claude", "glpi", "tech", "normal", "post-only", "glpi-system")]
    if not users:
        return Holdings(problem=f'No one matches "{person}".')
    if len(users) > 1:
        return Holdings(candidates=[f"{u['firstname']} {u['realname']}" for u in users])
    u = users[0]
    names = _people(api)
    open_rows = [t for t in api.all("Ticket") if t["status"] in OPEN]
    tickets = [ticket_of(api, t, names) for t in open_rows]
    mine = [t for t in tickets if t.requester == names.get(u["name"])]
    assets = []
    for kind in ASSET_KINDS:
        for a in api.all(kind, expand_dropdowns="true"):
            if a.get("users_id") == u["name"]:
                assets.append(Asset(name=a["name"], kind=kind, model=a.get(f"{kind.lower()}models_id") or None,
                                    state=a.get("states_id") or None, location=a.get("locations_id") or None,
                                    serial=a.get("serial") or None,
                                    open_tickets=[f"#{t.id} {t.title}" for t in tickets if a["name"] in t.assets]))
    return Holdings(person=names.get(u["name"]), assets=assets, open_tickets=mine)


class Attention(BaseModel):
    unassigned: list[Ticket] = Field(description="open tickets with no technician and no group")
    late: list[Ticket] = Field(description="open tickets past their time to resolve")
    urgent: list[Ticket] = Field(description="open tickets at high priority or above")
    waiting_on_requester: list[Ticket] = Field(description="pending tickets, waiting for the requester to answer")


def needs_attention(api: GLPI) -> Attention:
    names = _people(api)
    tickets = [ticket_of(api, t, names) for t in api.all("Ticket") if t["status"] in OPEN]
    rank = {v: k for k, v in PRIORITY.items()}
    tickets.sort(key=lambda t: (-rank.get(t.priority, 0), t.opened or ""))
    return Attention(unassigned=[t for t in tickets if not t.technicians and not t.groups],
                     late=[t for t in tickets if t.late],
                     urgent=[t for t in tickets if rank.get(t.priority, 0) >= 4],
                     waiting_on_requester=[t for t in tickets if t.status == "waiting"])


# ---------- change (preview, then confirm) ----------

class Change(BaseModel):
    done: bool = Field(description="false: nothing has changed yet; true: GLPI has made the change")
    summary: str
    confirmation: str | None = Field(None, description="when done is false: the code to pass back, only after the user says yes")
    expires_in_minutes: int | None = None
    ticket: Ticket | None = None
    problem: str | None = Field(None, description="why it can't be done; nothing was changed")


_pending: dict[str, tuple[float, tuple]] = {}


def _ask(request: tuple, summary: str, ticket: Ticket) -> Change:
    now = time.monotonic()
    for k in [k for k, (t, _) in _pending.items() if now - t > CONFIRM_TTL_S]:
        del _pending[k]
    code = secrets.token_hex(3)
    _pending[code] = (now, request)
    return Change(done=False, summary=summary + " Nothing has changed yet: ask the user to confirm.",
                  confirmation=code, expires_in_minutes=CONFIRM_TTL_S // 60, ticket=ticket)


def _confirmed(code: str, request: tuple) -> bool:
    held = _pending.get(code.strip())
    if not held or time.monotonic() - held[0] > CONFIRM_TTL_S or held[1] != request:
        return False
    del _pending[code.strip()]
    return True


def _expired(summary: str, ticket: Ticket) -> Change:
    return Change(done=False, summary=summary, ticket=ticket,
                  problem="That confirmation code doesn't match this request or has expired. Ask again.")


def add_followup(api: GLPI, ticket_id: int, text: str, private: bool = True, confirmation: str | None = None) -> Change:
    t = _ticket(api, ticket_id)
    if not t:
        return Change(done=False, summary="", problem=f"No ticket has the id {ticket_id}.")
    if not text.strip():
        return Change(done=False, summary="", problem="The follow-up is empty.")
    tk = ticket_of(api, t, _people(api))
    if t["status"] == 6:
        return Change(done=False, summary="", ticket=tk, problem=f"Ticket #{tk.id} is closed.")
    request = ("followup", t["id"], text.strip(), private)
    who = "technicians only" if private else f"{tk.requester} will see it"
    summary = f'Add a follow-up to #{tk.id} ("{tk.title}"), {who}: "{text.strip()}"'
    if not confirmation:
        return _ask(request, summary, tk)
    if not _confirmed(confirmation, request):
        return _expired(summary, tk)
    api.post("ITILFollowup", {"itemtype": "Ticket", "items_id": t["id"], "content": f"{text.strip()}\n\n({NOTE})",
                              "is_private": int(private)})
    return Change(done=True, summary=f"Done: the follow-up is on #{tk.id}.", ticket=tk)


def _group(api: GLPI, name: str) -> tuple[dict | None, str | None]:
    groups = [g for g in api.all("Group") if name.strip().lower() in g["name"].lower()]
    if len(groups) == 1:
        return groups[0], None
    return None, f'"{name}" matches {", ".join(g["name"] for g in groups) or "no group"}. Ask which group.'


def _technician(api: GLPI, name: str) -> tuple[dict | None, str | None]:
    techs = {pu["users_id"] for pu in api.all("Profile_User") if pu["profiles_id"] == 6}  # Technician profile
    hits = [u for u in api.all("User") if u["id"] in techs
            and name.strip().lower() in f"{u.get('firstname') or ''} {u.get('realname') or ''}".lower()]
    if len(hits) == 1:
        return hits[0], None
    return None, f'"{name}" matches {", ".join(f"{u["firstname"]} {u["realname"]}" for u in hits) or "no technician"}. Ask which one.'


def update_ticket(api: GLPI, ticket_id: int, group: str | None = None, technician: str | None = None,
                  priority: str | None = None, confirmation: str | None = None) -> Change:
    """Reassign to a group (replacing the assigned group), add a technician, or change the priority."""
    t = _ticket(api, ticket_id)
    if not t:
        return Change(done=False, summary="", problem=f"No ticket has the id {ticket_id}.")
    names = _people(api)
    tk = ticket_of(api, t, names)
    if t["status"] not in OPEN:
        return Change(done=False, summary="", ticket=tk, problem=f"Ticket #{tk.id} is {tk.status}.")
    plan, parts = [], []
    if group:
        g, why = _group(api, group)
        if not g:
            return Change(done=False, summary="", ticket=tk, problem=why)
        plan.append(("group", g["id"]))
        parts.append(f"reassign it to {g['name']}" + (f" (from {', '.join(tk.groups)})" if tk.groups else ""))
    if technician:
        u, why = _technician(api, technician)
        if not u:
            return Change(done=False, summary="", ticket=tk, problem=why)
        plan.append(("tech", u["id"]))
        parts.append(f"assign {u['firstname']} {u['realname']}")
    if priority:
        rank = {v: k for k, v in PRIORITY.items()}
        if priority not in rank:
            return Change(done=False, summary="", ticket=tk, problem=f"Priority must be one of: {', '.join(PRIORITY.values())}.")
        plan.append(("priority", rank[priority]))
        parts.append(f"set the priority to {priority}")
    if not parts:
        return Change(done=False, summary="", ticket=tk, problem="Nothing to change: give a group, a technician or a priority.")
    request = ("update", t["id"], tuple(plan))
    summary = f'On #{tk.id} ("{tk.title}"): ' + ", ".join(parts) + "."
    if not confirmation:
        return _ask(request, summary, tk)
    if not _confirmed(confirmation, request):
        return _expired(summary, tk)
    for kind, value in plan:
        if kind == "group":
            for gt in api.get(f"Ticket/{t['id']}/Group_Ticket") or []:
                if gt["type"] == 2:
                    api.call("DELETE", f"Group_Ticket/{gt['id']}")
            api.post("Group_Ticket", {"tickets_id": t["id"], "groups_id": value, "type": 2})
        elif kind == "tech":
            api.post("Ticket_User", {"tickets_id": t["id"], "users_id": value, "type": 2})
        elif kind == "priority":
            api.put(f"Ticket/{t['id']}", {"priority": value})
    return Change(done=True, summary=f"Done: #{tk.id} updated.", ticket=ticket_of(api, api.get(f"Ticket/{t['id']}"), names))
