"""Build a self-contained, local HTML viewer of the tree, gaps and research leads.

Usage (from the repo root, after fetch_tree.py):
    python src/build_viewer.py            # writes data/tree.html
    start data/tree.html                  # open it (Windows)

The page is a single file with the data embedded. It stays in data/
(gitignored) because it includes living relatives. Don't publish it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from find_gaps import GAPS, analyse, display_name, years  # noqa: E402
from research import extract_sources, links, region, suggestions, year  # noqa: E402
from wikitree_api import ROOT  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent / "viewer_template.html"


def relation(gen: int, side: str, gender: str) -> str:
    if gen == 0:
        return "You"
    who = {"Male": "father", "Female": "mother"}.get(gender, "parent")
    if gen == 1:
        base = who
    elif gen == 2:
        base = f"grand{who}"
    elif gen == 3:
        base = f"great-grand{who}"
    else:
        base = f"{gen - 2}× great-grand{who}"
    return f"{base} ({side} side)" if side else base


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", default=str(ROOT / "data" / "tree.json"))
    ap.add_argument("--notes", default=str(ROOT / "data" / "research_notes.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "tree.html"))
    args = ap.parse_args()

    tree = json.loads(Path(args.tree).read_text(encoding="utf-8"))
    people: dict = tree["people"]
    notes_path = Path(args.notes)
    notes = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.exists() else {}

    root = next((p for p in people.values() if (p.get("Meta") or {}).get("Degrees") == 0), None)
    if not root:
        print("Root profile not found in tree.json")
        return 1

    # Walk up from the root to label each ancestor's side (first path found wins).
    side: dict[str, str] = {str(root["Id"]): ""}
    stack = [(str(root["Id"]), "")]
    while stack:
        pid, s = stack.pop()
        p = people.get(pid)
        if not p:
            continue
        for key, label in (("Father", "father's"), ("Mother", "mother's")):
            par = p.get(key) or 0
            if par > 0 and str(par) in people and str(par) not in side:
                side[str(par)] = s or label
                stack.append((str(par), s or label))

    # Anyone with a child born or died in the US probably lived there too.
    # Passes up through children whose own birthplace is blank (and so unknown).
    us_parent: set[str] = set()
    changed = True
    while changed:
        changed = False
        for cid, c in people.items():
            here = "us" in (region(c.get("BirthLocation")), region(c.get("DeathLocation")))
            inherited = cid in us_parent and not (c.get("BirthLocation") or "").strip()
            if here or inherited:
                for k in ("Father", "Mother"):
                    par = str(c.get(k) or 0)
                    if par != "0" and not par.startswith("-") and par not in us_parent:
                        us_parent.add(par)
                        changed = True

    out = {}
    for pid, p in people.items():
        if not p.get("Name"):
            continue
        gaps = analyse(p, tree.get("ancestors"))
        gen = (p.get("Meta") or {}).get("Degrees") or 0
        n = notes.get(p["Name"], {})
        out[pid] = {
            "id": pid,
            "w": p["Name"],
            "n": display_name(p),
            "y": years(p),
            "g": p.get("Gender") or "",
            "b": p.get("BirthDate") or "",
            "bp": p.get("BirthLocation") or "",
            "d": p.get("DeathDate") or "",
            "dp": p.get("DeathLocation") or "",
            "by": year(p.get("BirthDate")),
            "f": str(p["Father"]) if (p.get("Father") or 0) > 0 and str(p["Father"]) in people else None,
            "m": str(p["Mother"]) if (p.get("Mother") or 0) > 0 and str(p["Mother"]) in people else None,
            "fx": (p.get("Father") or 0) > 0,  # linked on WikiTree (maybe beyond the fetched depth)
            "mx": (p.get("Mother") or 0) > 0,
            "gen": gen,
            "side": side.get(pid, ""),
            "rel": relation(gen, side.get(pid, ""), p.get("Gender") or ""),
            "liv": bool(p.get("IsLiving")),
            "gaps": gaps,
            "score": sum(GAPS[x][0] for x in gaps),
            "src": extract_sources(p.get("bio") or ""),
            "sug": suggestions(p, gaps, us_hint=pid in us_parent),
            "links": links(p),
            "flag": n.get("flag"),
            "leads": n.get("leads", []),
            "fam": n.get("family", []),
            "found": n.get("found", []),
        }

    payload = {
        "root": str(root["Id"]),
        "fetched": tree.get("fetched"),
        "gapLabels": {k: v[1] for k, v in GAPS.items()},
        "people": out,
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", data)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"Wrote {args.out} ({len(out)} people, {len(html) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
