"""Fill a fresh local GLPI with the IT helpdesk and assets of Harbor Trading, a made-up Gulf company (SAMPLE data).

Locations, groups, people, computers, monitors, phones and tickets go in through GLPI's own REST API, with
opening dates and resolution deadlines set relative to now, so the desk always has a major incident with no
owner, tickets past their deadline, one waiting on the requester and some solved history. GLPI's timeline shows when
an item was created in the database and who logged it, which the API stamps "now" and the API user, so the seeder
also writes docker/backdate.sql (the real times, and the requester as the ticket's author), applied by
scripts/reset.sh. Run on a fresh GLPI only (scripts/reset.sh).
"""

import secrets
from datetime import UTC, datetime, timedelta

from pathlib import Path

from glpi_mcp.client import GLPI


def at(hours: float) -> str:
    """hours ago (positive) or from now (negative), in GLPI's "Y-m-d H:i:s"."""
    return (datetime.now(UTC) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


LOCATIONS = ["Dammam HQ", "Riyadh office", "Jeddah warehouse"]
GROUPS = ["Service desk", "Network team", "Field support"]
# login, first, last, job title, location, group (IT staff only)
IT = [
    ("ahmed.raza", "Ahmed", "Raza", "IT lead", "Dammam HQ", "Network team"),
    ("ravi.menon", "Ravi", "Menon", "Network engineer", "Riyadh office", "Network team"),
    ("hana.saleh", "Hana", "Saleh", "Service desk engineer", "Dammam HQ", "Service desk"),
    ("joanna.silva", "Joanna", "Silva", "Field support", "Jeddah warehouse", "Field support"),
]
STAFF = [
    ("sara.alqahtani", "Sara", "Al-Qahtani", "Accountant", "Dammam HQ"),
    ("omar.haddad", "Omar", "Haddad", "Finance manager", "Dammam HQ"),
    ("layla.mansour", "Layla", "Mansour", "Account manager", "Riyadh office"),
    ("faisal.aldosari", "Faisal", "Al-Dosari", "Sales lead", "Riyadh office"),
    ("daniel.okafor", "Daniel", "Okafor", "Export sales", "Riyadh office"),
    ("khalid.alotaibi", "Khalid", "Al-Otaibi", "Warehouse manager", "Jeddah warehouse"),
    ("maryam.alharbi", "Maryam", "Al-Harbi", "Dispatcher", "Jeddah warehouse"),
    ("noura.alshehri", "Noura", "Al-Shehri", "Buyer", "Dammam HQ"),
]
# asset name, kind, model, maker, holder (login or None), location, state
ASSETS = [
    ("LAP-0140", "Computer", "ThinkPad T14 Gen 5", "Lenovo", "sara.alqahtani", "Dammam HQ", "In repair"),
    ("LAP-0141", "Computer", "ThinkPad T14 Gen 5", "Lenovo", "omar.haddad", "Dammam HQ", "In use"),
    ("LAP-0142", "Computer", "Latitude 5450", "Dell", "layla.mansour", "Riyadh office", "In use"),
    ("LAP-0143", "Computer", "MacBook Pro 14", "Apple", "faisal.aldosari", "Riyadh office", "In use"),
    ("LAP-0151", "Computer", "Latitude 5450", "Dell", "daniel.okafor", "Riyadh office", "In use"),
    ("LAP-0152", "Computer", "ThinkPad T14 Gen 5", "Lenovo", "khalid.alotaibi", "Jeddah warehouse", "In use"),
    ("LAP-0153", "Computer", "ThinkPad T14 Gen 5", "Lenovo", "noura.alshehri", "Dammam HQ", "In use"),
    ("LAP-0160", "Computer", "ThinkPad T14 Gen 5", "Lenovo", None, "Dammam HQ", "In stock"),
    ("LAP-0161", "Computer", "ThinkPad T14 Gen 5", "Lenovo", "sara.alqahtani", "Dammam HQ", "Loan"),
    ("MON-0210", "Monitor", "UltraSharp U2724D", "Dell", "sara.alqahtani", "Dammam HQ", "In use"),
    ("MON-0211", "Monitor", "UltraSharp U2724D", "Dell", "omar.haddad", "Dammam HQ", "In use"),
    ("MON-0212", "Monitor", "UltraSharp U2724D", "Dell", "layla.mansour", "Riyadh office", "In use"),
    ("PHN-0310", "Phone", "iPhone 16", "Apple", "faisal.aldosari", "Riyadh office", "In use"),
    ("PHN-0311", "Phone", "iPhone 16", "Apple", "daniel.okafor", "Riyadh office", "In use"),
    ("SCN-0410", "Peripheral", "TC22 mobile computer", "Zebra", "maryam.alharbi", "Jeddah warehouse", "In use"),
    ("SCN-0411", "Peripheral", "TC22 mobile computer", "Zebra", None, "Jeddah warehouse", "In use"),
]

# GLPI ticket fields: type 1 incident / 2 request; urgency and impact 1–5; priority 1 very low … 5 very high, 6 major;
# status 1 new, 2 assigned, 3 planned, 4 pending (waiting), 5 solved, 6 closed.
# title, type, priority, status, requester, tech (login or None), group, opened h ago, due in h (negative = late),
# linked asset, follow-ups [(who, h ago, private, text)]
TICKETS = [
    ("VPN drops every 10 minutes at the Riyadh office", 1, 5, 2, "layla.mansour", "hana.saleh", "Service desk", 6, 2, None, [
        ("layla.mansour", 6, False, "Since this morning the VPN disconnects every ten minutes for everyone in Riyadh. We can't reach the ERP."),
        ("hana.saleh", 4, True, "Collected logs from three laptops: the tunnel resets on the firewall side, not the clients. Needs the network team."),
    ]),
    ("Warehouse scanners can't reach the WMS", 1, 6, 1, "khalid.alotaibi", None, None, 1.5, 2.5, "SCN-0411", [
        ("khalid.alotaibi", 1.5, False, "None of the TC22 scanners in Jeddah can log in to the warehouse system. Dispatch is stopped."),
    ]),
    ("Laptop battery is swelling", 1, 4, 3, "sara.alqahtani", "joanna.silva", "Field support", 30, -6, "LAP-0140", [
        ("sara.alqahtani", 30, False, "The trackpad on my laptop is lifting and the case is bulging."),
        ("joanna.silva", 28, False, "Please stop using it and keep it unplugged. A loan laptop (LAP-0161) is on your desk; I've booked the repair."),
    ]),
    ("Laptop won't boot after the update", 1, 4, 2, "noura.alshehri", "ahmed.raza", "Service desk", 9, -1, "LAP-0153", [
        ("noura.alshehri", 9, False, "After last night's update my laptop stops at a blue screen."),
    ]),
    ("Outlook keeps asking for my password", 1, 3, 4, "omar.haddad", "hana.saleh", "Service desk", 40, 30, None, [
        ("omar.haddad", 40, False, "Outlook asks for my password every hour."),
        ("hana.saleh", 26, False, "Could you sign out of Outlook on your phone and laptop, then sign back in, and tell me if it stops?"),
    ]),
    ("Laptop and accounts for a new buyer", 2, 3, 2, "noura.alshehri", "hana.saleh", "Service desk", 50, 46, None, [
        ("noura.alshehri", 50, False, "A new buyer joins my team on Sunday. Please prepare a laptop, email and ERP access."),
    ]),
    ("Printer on the 2nd floor jams", 1, 2, 1, "omar.haddad", None, None, 20, 52, None, [
        ("omar.haddad", 20, False, "The printer by finance jams on every second page."),
    ]),
    ("Cracked phone screen", 2, 3, 2, "daniel.okafor", "joanna.silva", "Field support", 72, 24, "PHN-0311", [
        ("daniel.okafor", 72, False, "Dropped my phone, the screen is cracked but it works."),
    ]),
    ("Access to the finance share", 2, 3, 5, "sara.alqahtani", "ahmed.raza", "Service desk", 120, 0, None, [
        ("sara.alqahtani", 120, False, "Please give me access to the Finance share."),
        ("ahmed.raza", 118, False, "Done: you're in the Finance group. Sign out and in again to see it."),
    ]),
    ("Monitor flickering", 1, 2, 6, "layla.mansour", "hana.saleh", "Service desk", 200, 0, "MON-0212", [
        ("layla.mansour", 200, False, "My monitor flickers when I move windows."),
        ("hana.saleh", 196, False, "Replaced the cable; closing, reopen if it comes back."),
    ]),
]
STATE_NAMES = ["In use", "In stock", "In repair", "Loan"]


def seed(api: GLPI, backdate: Path) -> dict:
    if api.get("Ticket", range="0-0"):
        raise SystemExit("GLPI already has tickets: seed a fresh one (scripts/reset.sh)")

    def made(itemtype: str, data: dict) -> int:
        return api.post(itemtype, data)["id"]

    loc = {n: made("Location", {"name": n, "entities_id": 0, "is_recursive": 1}) for n in LOCATIONS}
    grp = {n: made("Group", {"name": n, "entities_id": 0, "is_recursive": 1, "is_assign": 1, "is_requester": 1}) for n in GROUPS}
    state = {n: made("State", {"name": n, "entities_id": 0, "is_recursive": 1}) for n in STATE_NAMES}
    users: dict[str, int] = {}
    for login, first, last, title, where, *grp_name in [*IT, *STAFF]:
        pw = secrets.token_urlsafe(18)  # sample people never sign in
        uid = made("User", {"name": login, "firstname": first, "realname": last, "password": pw, "password2": pw,
                            "locations_id": loc[where], "comment": title, "entities_id": 0,
                            "_useremails": {"-1": f"{login}@harbor-trading.example"}})
        users[login] = uid
        if grp_name:
            made("Group_User", {"groups_id": grp[grp_name[0]], "users_id": uid})
            made("Profile_User", {"users_id": uid, "profiles_id": 6, "entities_id": 0, "is_recursive": 1})  # Technician
    makers: dict[str, int] = {}
    models: dict[tuple[str, str], int] = {}
    asset_ids: dict[str, tuple[str, int]] = {}
    for name, kind, model, maker, holder, where, st in ASSETS:
        if maker not in makers:
            makers[maker] = made("Manufacturer", {"name": maker})
        if (kind, model) not in models:
            models[(kind, model)] = made(f"{kind}Model", {"name": model})
        aid = made(kind, {"name": name, "serial": f"HT{secrets.token_hex(4).upper()}", "entities_id": 0,
                          "manufacturers_id": makers[maker], f"{kind.lower()}models_id": models[(kind, model)],
                          "users_id": users.get(holder, 0), "locations_id": loc[where], "states_id": state[st],
                          "comment": "SAMPLE data"})
        asset_ids[name] = (kind, aid)

    sql: list[str] = []
    for title, typ, prio, status, req, tech, group, opened, due, asset, followups in TICKETS:
        first = followups[0][3]
        data = {"name": title, "content": first, "type": typ, "priority": prio, "urgency": min(prio, 5),
                "impact": min(prio, 5), "status": 2 if status in (5, 6) else status, "entities_id": 0, "date": at(opened),
                "_users_id_requester": users[req], "locations_id": 0}
        if due:
            data["time_to_resolve"] = at(-due)
        if tech:
            data["_users_id_assign"] = users[tech]
        if group:
            data["_groups_id_assign"] = grp[group]
        tid = made("Ticket", data)
        if asset:
            kind, aid = asset_ids[asset]
            link = {"tickets_id": tid, "itemtype": kind, "items_id": aid}
            made("Item_Ticket", link)
        for who, h, private, text in followups[1:]:
            fid = made("ITILFollowup", {"itemtype": "Ticket", "items_id": tid, "content": text, "is_private": int(private),
                                        "users_id": users[who], "date": at(h)})
            sql.append(f"UPDATE glpi_itilfollowups SET date='{at(h)}', date_creation='{at(h)}', date_mod='{at(h)}' WHERE id={fid};")
        last = at(followups[-1][1])
        sql.append(f"UPDATE glpi_tickets SET date_creation='{at(opened)}', date_mod='{last}', "
                   f"users_id_recipient={users[req]}, users_id_lastupdater={users[followups[-1][0]]} WHERE id={tid};")
        if status in (5, 6):  # created open (a closed ticket takes no links or follow-ups), then solved/closed
            api.put(f"Ticket/{tid}", {"status": status, "solvedate": at(followups[-1][1]),
                                      **({"closedate": at(followups[-1][1])} if status == 6 else {})})
    backdate.write_text("\n".join(sql) + "\n")
    return {"locations": len(loc), "groups": len(grp), "people": len(users), "assets": len(asset_ids),
            "tickets": len(TICKETS)}


def main() -> None:
    print(seed(GLPI(), Path(__file__).resolve().parents[2] / "docker" / "backdate.sql"))
