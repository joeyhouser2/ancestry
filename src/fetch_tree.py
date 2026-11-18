"""Pull the Houser tree from WikiTree (read-only) and cache it to data/tree.json.

Usage (from the repo root):
    python src/fetch_tree.py                 # ancestors of Houser-1616, 25 generations (the API max)
    python src/fetch_tree.py --ancestors 12 --descendants 2
    python src/fetch_tree.py --key Windsor-1 --no-login   # public test, no login
    python src/fetch_tree.py --logout        # forget the saved session

Houser-1616 is a Private profile, so a logged-in session is needed to see it.
The first run opens WikiTree's own login page in your browser; sign in there and
the script picks up the session. Use --password-login to type your email and
password in the terminal instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikitree_api import ROOT, WikiTreeClient, WikiTreeError  # noqa: E402

FIELDS = [
    "Id", "Name", "FirstName", "MiddleName", "LastNameAtBirth", "LastNameCurrent",
    "Gender", "BirthDate", "DeathDate", "BirthLocation", "DeathLocation",
    "BirthDateDecade", "DeathDateDecade", "IsLiving", "Privacy",
    "Father", "Mother", "DataStatus", "ResearchStatus", "Manager",
    "Bio", "Templates", "Categories", "Meta",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", default="Houser-1616", help="starting WikiTree ID")
    ap.add_argument("--ancestors", type=int, default=25, help="generations up (max 25)")
    ap.add_argument("--descendants", type=int, default=0, help="generations down (max 10)")
    ap.add_argument("--no-login", action="store_true", help="anonymous; public data only")
    ap.add_argument("--password-login", action="store_true",
                    help="type email/password in this terminal instead of the browser login")
    ap.add_argument("--logout", action="store_true", help="log out and delete saved session")
    ap.add_argument("--out", default=str(ROOT / "data" / "tree.json"))
    args = ap.parse_args()

    client = WikiTreeClient()

    if args.logout:
        client.load_session()
        client.logout()
        print("Logged out; saved session removed.")
        return 0

    if args.no_login:
        print("Running anonymously: private profiles will be hidden.")
    else:
        try:
            client.ensure_login(allow_prompt=True,
                                method="password" if args.password_login else "browser")
        except WikiTreeError as e:
            print(e)
            return 1
        print(f"Logged in as {client.user_name}.")

    print(f"Fetching {args.key}: {args.ancestors} generations up, {args.descendants} down...")
    try:
        people = client.get_people(args.key, FIELDS, ancestors=args.ancestors,
                                   descendants=args.descendants, bioFormat="wiki")
    except WikiTreeError as e:
        print(e)
        return 1

    visible = [p for p in people.values() if p.get("Name")]
    hidden = len(people) - len(visible)
    root = next((p for p in people.values() if (p.get("Meta") or {}).get("Degrees") == 0), None)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "root": args.key,
        "root_id": root.get("Id") if root else None,
        "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "logged_in_as": client.user_name if not args.no_login else None,
        "ancestors": args.ancestors,
        "descendants": args.descendants,
        "people": people,
    }, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"Saved {len(people)} profiles to {out} ({hidden} hidden from this login).")
    if root is None or not root.get("Name"):
        print("Warning: the starting profile itself is hidden. Log in as a manager "
              "or someone on its Trusted List.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
