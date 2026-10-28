# GLPI MCP server

Ask Claude about your IT helpdesk and assets in plain words: what's urgent and who owns it, what a person holds
and whether any of it is broken, what a ticket says. Add follow-ups and reassign tickets from the same chat, with a
confirmation step before anything changes.

Built by [Mojood Connect](https://mojood.app/connect) as a working demo for [GLPI](https://glpi-project.org). It
runs against any GLPI 9.5–12 through its REST API. This repository includes a local GLPI with **SAMPLE data** for
the IT department of a made-up company, Harbor Trading, so you can try it without touching a real instance.

## Tools

| Tool | What it does | Changes anything? |
| --- | --- | --- |
| `find_tickets` | Find tickets, highest priority first: status, requester, technicians, groups, deadline, linked assets | No |
| `get_ticket` | One ticket with its description and every follow-up in order, private ones marked | No |
| `person_overview` | The assets a person holds (state, and any open ticket about each) and the tickets they asked for | No |
| `needs_attention` | Tickets with no owner, past their time to resolve, high priority and above, waiting on the requester | No |
| `add_followup` | A follow-up on a ticket: private to technicians unless asked otherwise | Yes, after confirmation |
| `update_ticket` | Reassign to a group, add a technician, or change the priority | Yes, after confirmation |

**How changes are made safe.** A call to `add_followup` or `update_ticket` without a `confirmation` changes nothing:
it returns a plain summary ("On #1 ("VPN drops every 10 minutes at the Riyadh office"): reassign it to Network team
(from Service desk).") and a one-time code. The change happens only when the same request comes back with that code,
within 10 minutes. A code works once, and only for the request it was issued for. The server's instructions tell
the model to show the summary and wait for the user's yes. Follow-ups carry "via Claude (Mojood Connect demo)", and
GLPI records every change in the ticket's history under the signed-in user.

The server signs in as one GLPI user and acts with that user's profile and rights.

## Try it locally

Needs Docker (with Compose), [uv](https://docs.astral.sh/uv/) and Python 3.13.

```
scripts/reset.sh                         # local GLPI on http://localhost:8095, filled with the SAMPLE helpdesk
uv run --env-file .env glpi-mcp          # MCP server on http://127.0.0.1:8006/mcp (Streamable HTTP)
```

`docker/compose.yml` follows GLPI's own `docker-compose.example.yml` (glpi-project/docker-images), pinned to GLPI
12.0.1 and MySQL 8.4, on 127.0.0.1 only and in UTC. `scripts/up.sh` gives GLPI's default accounts (glpi, tech,
normal, post-only) generated passwords, creates the demo's API user and switches the REST API on; every password
stays in the git-ignored files `docker/.env` and `.env`, and nothing is printed.

**Claude Desktop:** add this to `claude_desktop_config.json` (Settings › Developer), with the path to this folder:

```json
{
  "mcpServers": {
    "glpi": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/glpi-mcp", "--env-file", "/path/to/glpi-mcp/.env", "glpi-mcp", "--stdio"]
    }
  }
}
```

Then ask: "What urgent tickets are open, and who owns them?", "What does Sara have, and is any of it broken?", "Add
a note to the VPN ticket that the firewall logs point to the IPsec tunnel, and reassign it to the network team."

**Your own GLPI:** set `GLPI_URL`, `GLPI_LOGIN`, `GLPI_PASSWORD` (a GLPI user; the REST API and login-credential
access switched on in Setup › General › API) and `GLPI_SAMPLE=0`.

## The SAMPLE helpdesk

Harbor Trading's IT: three sites, three groups (Service desk, Network team, Field support), four technicians, eight
staff, 16 assets (laptops, monitors, phones, warehouse scanners) and ten tickets. Times are set relative to the
moment it is seeded, so there is always a major incident with no owner, two tickets past their deadline, one
waiting on the requester and some solved history. Everyone and everything in it is made up.

## Tests

```
uv run --env-file .env pytest            # unit tests (a fake GLPI API), plus live tests when the local GLPI runs
```

## What a production version adds

This demo signs in as one user. A production server for GLPI customers would add sign-in through GLPI 11+'s OAuth
for each technician, so Claude sees exactly their entities and profile; hosting with an audit log of every tool
call; and more of the API (problems and changes, knowledge base, contracts, software and licences). That is what
[Mojood Connect](https://mojood.app/connect) builds.

## License

Apache 2.0. GLPI is a trademark of Teclib'; this project is not made or endorsed by Teclib'.
