"""A small GLPI REST client (the legacy apirest.php API, which every GLPI 9.5–12 has): sign in once, then the calls
the tools and the seeder need. GLPI answers errors as ["ERROR_CODE", "message"]; `call` turns those into GLPIError.
"""

import os
from typing import Any

import httpx


class GLPIError(Exception):
    pass


class GLPI:
    def __init__(self, url: str | None = None, login: str | None = None, password: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.url = (url or os.environ.get("GLPI_URL", "http://127.0.0.1:8095")).rstrip("/")
        login = login or os.environ.get("GLPI_LOGIN", "")
        password = password or os.environ.get("GLPI_PASSWORD", "")
        if not (login and password):
            raise GLPIError("GLPI_LOGIN and GLPI_PASSWORD are not set (scripts/up.sh writes them to .env)")
        self.http = httpx.Client(base_url=self.url + "/apirest.php/", timeout=30, transport=transport,
                                 headers={"Content-Type": "application/json"})
        self._auth = (login, password)
        self._session: str | None = None

    def _sign_in(self) -> None:
        r = self.http.get("initSession", auth=self._auth, params={"get_full_session": "false"})
        body = r.json()
        if r.status_code >= 400 or not isinstance(body, dict) or "session_token" not in body:
            raise GLPIError(_message(body) or f"GLPI sign-in failed ({r.status_code})")
        self._session = body["session_token"]
        self.http.headers["Session-Token"] = self._session

    def call(self, method: str, path: str, **kw: Any) -> Any:
        if not self._session:
            self._sign_in()
        for attempt in range(2):
            r = self.http.request(method, path, **kw)
            if r.status_code == 401 and attempt == 0:  # the session expired: sign in again once
                self._sign_in()
                continue
            break
        body = r.json() if r.content else None
        if r.status_code == 404:
            raise GLPIError(_message(body) or "not found")
        if r.status_code >= 400:
            raise GLPIError(_message(body) or f"GLPI answered {r.status_code}")
        return body

    def get(self, path: str, **params: Any) -> Any:
        return self.call("GET", path, params=params)

    def post(self, path: str, data: dict) -> Any:
        return self.call("POST", path, json={"input": data})

    def put(self, path: str, data: dict) -> Any:
        return self.call("PUT", path, json={"input": data})

    def all(self, itemtype: str, **params: Any) -> list[dict]:
        """Every item of a type, page by page (GLPI pages with range=start-end)."""
        out, start = [], 0
        while True:
            page = self.get(itemtype, range=f"{start}-{start + 199}", **params) or []
            out += page
            if len(page) < 200:
                return out
            start += 200


def _message(body: Any) -> str | None:
    if isinstance(body, list) and body:
        return str(body[-1])
    if isinstance(body, dict):
        return body.get("message") or body.get("error")
    return None


