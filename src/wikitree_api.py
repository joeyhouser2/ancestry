"""Small read-only client for the WikiTree API (https://api.wikitree.com/api.php).

Two ways to log in (both end with an authcode that this script confirms, which
gives it its own session cookies):

  browser (default, WikiTree's recommended flow)
      Opens WikiTree's own login page in your browser. After you sign in there,
      WikiTree redirects to a tiny one-shot server on 127.0.0.1 with the authcode.
      The script never sees your password.

  password (--password-login)
      POST action=clientLogin, doLogin=1, wpEmail, wpPassword without following
      the redirect; the authcode is in the Location header. The password is read
      with getpass and never stored.

Only the session cookies are cached, in data/.session.json (gitignored).
"""

from __future__ import annotations

import getpass
import http.server
import json
import os
import re
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests

API_URL = "https://api.wikitree.com/api.php"
APP_ID = "HouserTree"
ROOT = Path(__file__).resolve().parent.parent
SESSION_FILE = ROOT / "data" / ".session.json"


class WikiTreeError(RuntimeError):
    pass


def describe(r: requests.Response) -> str:
    """Short, safe description of a failed response (never includes request data)."""
    msg = ""
    try:
        body = r.json()
        block = body[0] if isinstance(body, list) and body else body
        if isinstance(block, dict):
            msg = str(block.get("status") or block.get("clientLogin") or "")
    except ValueError:
        text = re.sub(r"<[^>]+>", " ", r.text or "")
        msg = " ".join(text.split())[:200]
    hint = ""
    if r.status_code == 429:
        hint = (" WikiTree is rate-limiting this computer (too many requests or login "
                "attempts). Wait 15-30 minutes before trying again; each retry can "
                "extend the block.")
    return f"HTTP {r.status_code}{': ' + msg if msg else ''}.{hint}"


class WikiTreeClient:
    def __init__(self, pause: float = 0.5):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = f"{APP_ID} (personal family-tree helper)"
        self.pause = pause  # be polite between paged requests
        self._user_id: str | None = None
        self._user_name: str | None = None

    # ---------- session handling ----------

    def _cookie(self, suffix: str) -> str | None:
        # WikiTree has used both "wikidb_wtb_" and "wikitree_wtb_" cookie prefixes.
        for c in self.s.cookies:
            if c.name.endswith(suffix) and c.value and c.value != "deleted":
                return c.value
        return None

    @property
    def user_name(self) -> str | None:
        v = self._user_name or self._cookie("_wtb_UserName")
        return urllib.parse.unquote(v) if v else None

    @property
    def user_id(self) -> str | None:
        v = self._user_id or self._cookie("_wtb_UserID")
        return str(v) if v else None

    def load_session(self) -> bool:
        """Restore the saved session and confirm it is still valid."""
        if not SESSION_FILE.exists():
            return False
        try:
            saved = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        cookies = saved.get("cookies", saved)  # older files were a bare cookie dict
        self._user_id = saved.get("user_id")
        self._user_name = saved.get("user_name")
        for name, value in cookies.items():
            if isinstance(value, str):
                self.s.cookies.set(name, value, domain="api.wikitree.com")
        return self.check_login()

    def save_session(self) -> None:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        cookies = {c.name: c.value for c in self.s.cookies if c.value and c.value != "deleted"}
        SESSION_FILE.write_text(json.dumps({
            "cookies": cookies, "user_id": self._user_id, "user_name": self._user_name,
        }), encoding="utf-8")

    def check_login(self) -> bool:
        if not self.user_id:
            return False
        r = self.s.get(API_URL, params={"action": "clientLogin", "appId": APP_ID, "checkLogin": self.user_id})
        try:
            return r.json().get("clientLogin", {}).get("result") == "ok"
        except (ValueError, AttributeError):
            return False

    def _confirm_authcode(self, authcode: str) -> None:
        r = self.s.post(API_URL, data={"action": "clientLogin", "appId": APP_ID, "authcode": authcode},
                        allow_redirects=False)
        if r.status_code >= 400:
            raise WikiTreeError(f"Login failed while confirming the authcode: {describe(r)}")
        # WikiTree now returns the user in the JSON body and only sets a session
        # cookie (no UserID/UserName cookies), so take the identity from the body.
        try:
            body = r.json()
            info = body.get("clientLogin", body) if isinstance(body, dict) else {}
        except ValueError:
            info = {}
        if str(info.get("result", "")).lower() != "success":
            raise WikiTreeError(f"Login failed while confirming the authcode: {describe(r)}")
        self._user_id = info.get("userid") or info.get("user_id") or self._cookie("_wtb_UserID")
        self._user_name = info.get("username") or info.get("user_name") or self._cookie("_wtb_UserName")
        if not self._cookie("_wtb__session"):
            names = sorted(c.name for c in self.s.cookies)
            raise WikiTreeError(f"Login failed: no session cookie after confirming the "
                                f"authcode (cookies seen: {names}).")
        self.save_session()

    def login_password(self) -> None:
        email = os.environ.get("WIKITREE_EMAIL") or input("WikiTree email: ").strip()
        password = getpass.getpass("WikiTree password (not shown, not saved): ")
        r = self.s.post(
            API_URL,
            data={"action": "clientLogin", "appId": APP_ID, "doLogin": 1, "wpEmail": email, "wpPassword": password},
            allow_redirects=False,
        )
        del password
        location = r.headers.get("Location", "")
        m = re.search(r"authcode=([^&]+)", location)
        if not m:
            where = f" Redirected to {location.split('?')[0]}." if location else ""
            raise WikiTreeError(f"Login failed: no authcode returned. {describe(r)}{where}")
        self._confirm_authcode(urllib.parse.unquote(m.group(1)))

    def login_browser(self, timeout: int = 300) -> None:
        result: dict[str, str] = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if "authcode" in q:
                    result["authcode"] = q["authcode"][0]
                    body = "Logged in to WikiTree. You can close this tab and go back to the terminal."
                else:
                    body = "No authcode received. Go back to the terminal."
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *a):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        server.timeout = 1
        port = server.server_address[1]
        return_url = f"http://127.0.0.1:{port}/callback"
        login_url = f"{API_URL}?action=clientLogin&appId={APP_ID}&returnURL={urllib.parse.quote(return_url, safe='')}"
        print("Opening WikiTree's login page in your browser. If it doesn't open, visit:")
        print(f"  {login_url}")
        webbrowser.open(login_url)
        print(f"Waiting up to {timeout // 60} minutes for you to sign in...")
        deadline = time.time() + timeout
        try:
            while "authcode" not in result and time.time() < deadline:
                server.handle_request()
        finally:
            server.server_close()
        if "authcode" not in result:
            raise WikiTreeError("Login timed out: WikiTree never redirected back with an authcode. "
                                "If the page said 'Limit exceeded', wait 15-30 minutes. "
                                "Otherwise try --password-login.")
        self._confirm_authcode(result["authcode"])

    def ensure_login(self, allow_prompt: bool, method: str = "browser") -> bool:
        if self.load_session():
            return True
        if not allow_prompt:
            return False
        if method == "password":
            self.login_password()
        else:
            self.login_browser()
        return True

    def logout(self) -> None:
        self.s.get(API_URL, params={"action": "clientLogin", "appId": APP_ID, "doLogout": 1})
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()

    # ---------- API calls ----------

    def call(self, **params) -> list | dict:
        params = {"appId": APP_ID, **params}
        for wait in (30, 90, None):
            r = self.s.post(API_URL, data=params, timeout=60)
            if r.status_code == 429 and wait:
                print(f"  rate-limited by WikiTree; waiting {wait}s before retrying...")
                time.sleep(wait)
                continue
            if r.status_code >= 400:
                raise WikiTreeError(f"API request failed: {describe(r)}")
            return r.json()
        raise WikiTreeError("unreachable")

    def get_people(self, keys: str, fields: list[str], *, ancestors: int = 0,
                   descendants: int = 0, page_size: int = 1000, **extra) -> dict:
        """getPeople with paging. Returns {id: person}.

        `start` is a record offset. When more profiles remain, the API sets
        status to "Maximum number of profiles (...) reached." -- that is a
        "there's another page" signal, not a failure.
        """
        people: dict[str, dict] = {}
        start = 0
        while True:
            resp = self.call(action="getPeople", keys=keys, fields=",".join(fields),
                             ancestors=ancestors, descendants=descendants,
                             limit=page_size, start=start, **extra)
            block = resp[0] if isinstance(resp, list) else resp
            status = block.get("status") or ""
            more = status.startswith("Maximum number of profiles")
            if status and not more:
                raise WikiTreeError(f"getPeople error: {status}")
            if start == 0:
                for key, res in (block.get("resultByKey") or {}).items():
                    if res.get("status"):
                        print(f"  note: {key}: {res['status']}")
            batch = block.get("people") or {}
            new = {k: v for k, v in batch.items() if k not in people}
            people.update(batch)
            if not more or not new:
                break
            start += len(batch)
            print(f"  ...{len(people)} profiles so far")
            time.sleep(self.pause)
        return people
