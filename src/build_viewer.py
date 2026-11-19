"""Build a self-contained, local HTML viewer of the tree, gaps and research leads.

Usage (from the repo root, after fetch_tree.py):
    python src/build_viewer.py            # writes data/tree.html
    start data/tree.html                  # open it (Windows)

The page is a single file with the data embedded. It stays in data/
(gitignored) because it includes living relatives. Don't publish it.

Optional overlay (data/overlay.json, also gitignored) shows researched people
who are not on WikiTree yet:
    {"extra_trees": ["data/tree_extra_x.json"],          # more fetch_tree.py output
     "edits":  {"Bigg-111": {"draft": "Bigg-111", "Father": "alfred", "Mother": "hattie"}},
     "people": {"alfred": {"draft": "NEW-Bigg-AlfredSr", "Father": "fred", "Mother": "maryann"},
                "bart":   {"tier": "lead", "FirstName": "Bartholomew", "BirthDate": "about 1774", ...}}}
A person's fields come from the named draft's changes (drafts/<draft>.json; skipped
with "use_changes": false, e.g. for one half of a couple draft), then from the entry. Father/Mother may name another overlay key or a WikiTree ID.
Tier is "draft" (ready draft), "hold" (draft on hold) or "lead" (research notes only).
"""

from __future__ import annotations

import argparse
import json
import re
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


MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
SIMPLE = ("FirstName", "MiddleName", "LastNameAtBirth", "LastNameCurrent", "Nicknames", "Gender",
          "BirthDate", "BirthLocation", "DeathDate", "DeathLocation")
SYNTH = 900_000_000  # synthetic ids for people not on WikiTree


def wt_date(text: str | None) -> str:
    """'24 Aug 1857' / 'Aug 1857' / 'about 1833' / '30 Jan 1747/48' -> WikiTree YYYY-MM-DD."""
    t = (text or "").lower()
    y = re.search(r"\b(1[0-9]{3})\b", t)
    if not y:
        return ""
    head = t[: y.start()]
    m = next((MONTHS[w[:3]] for w in re.findall(r"[a-z]+", head) if w[:3] in MONTHS), 0)
    d = re.search(r"\b([0-3]?[0-9])\b", head)
    return f"{y.group(1)}-{m:02d}-{int(d.group(1)) if d and m else 0:02d}"


def apply_overlay(tree: dict, path: Path, drafts_dir: Path) -> dict[str, dict]:
    """Merge extra trees and draft/lead people into tree["people"]. Returns {id: overlay info}."""
    people: dict = tree["people"]
    ov = json.loads(path.read_text(encoding="utf-8"))
    for extra in ov.get("extra_trees", []):
        f = ROOT / extra
        if f.exists():
            for k, v in json.loads(f.read_text(encoding="utf-8"))["people"].items():
                people.setdefault(k, v)
    by_name = {p["Name"]: k for k, p in people.items() if p.get("Name")}
    keys = {k: str(SYNTH + i) for i, k in enumerate(ov.get("people", {}))}
    info: dict[str, dict] = {}

    def draft(name):
        f = drafts_dir / f"{name}.json"
        return json.loads(f.read_text(encoding="utf-8")) if name and f.exists() else None

    def fill(p, entry):
        d = draft(entry.get("draft"))
        if d and entry.get("use_changes", True):  # False for one person of a couple draft
            for c in d.get("changes", []):
                if c.get("field") in SIMPLE and (c.get("to") or c.get("from")):
                    p[c["field"]] = c.get("to") or ""  # an empty "to" clears the field
        p.update({k: v for k, v in entry.items() if k in SIMPLE})
        for k in ("BirthDate", "DeathDate"):
            if p.get(k) and not re.fullmatch(r"\d{4}-\d\d-\d\d", p[k]):
                p[k] = wt_date(p[k])
        for k in ("Father", "Mother"):
            ref = entry.get(k)
            if ref:
                p[k] = int(keys.get(ref) or by_name.get(ref) or 0)
        return d

    for key, entry in ov.get("people", {}).items():
        pid = keys[key]
        p = people[pid] = {"Id": int(pid), "Name": entry.get("draft") or key, "Father": 0, "Mother": 0}
        d = fill(p, entry)
        p["bio"] = (d or {}).get("biography", "")
        tier = entry.get("tier") or ("hold" if (d or {}).get("status") == "hold" else "draft")
        info[pid] = {"tier": tier, "draft": entry.get("draft") if d else None,
                     "dsrc": list((d or {}).get("sources", {}).values()),
                     "note": entry.get("note") or (d or {}).get("hold_reason") or ""}
    for name, entry in ov.get("edits", {}).items():
        pid = by_name.get(name)
        if not pid:
            print(f"  overlay: {name} not in tree, skipped")
            continue
        d = fill(people[pid], entry)
        info[pid] = {"tier": "edited", "draft": entry.get("draft") if d else None,
                     "dsrc": list((d or {}).get("sources", {}).values()), "note": entry.get("note", "")}
    return info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", default=str(ROOT / "data" / "tree.json"))
    ap.add_argument("--notes", default=str(ROOT / "data" / "research_notes.json"))
    ap.add_argument("--overlay", default=str(ROOT / "data" / "overlay.json"))
    ap.add_argument("--drafts", default=str(ROOT / "drafts"))
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
    info: dict[str, dict] = {}
    if Path(args.overlay).exists():
        info = apply_overlay(tree, Path(args.overlay), Path(args.drafts))
        # Recount generations from the root, since parents were added or changed.
        gens = {str(root["Id"]): 0}
        queue = [str(root["Id"])]
        while queue:
            c = queue.pop(0)
            for k in ("Father", "Mother"):
                par = str(people[c].get(k) or 0)
                if par in people and par not in gens:
                    gens[par] = gens[c] + 1
                    queue.append(par)
        for pid, g in gens.items():
            people[pid].setdefault("Meta", {})["Degrees"] = g
        people = {k: v for k, v in people.items() if k in gens}  # drops branches cut by an edit

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
        ov = info.get(pid, {})
        lk = links(p)
        if ov.get("tier") in ("draft", "hold", "lead"):
            lk = lk[1:]  # no WikiTree profile yet
        if ov.get("draft"):
            lk.insert(0, ("Draft file", f"../drafts/{ov['draft']}.json"))
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
            "links": lk,
            "tier": ov.get("tier"),
            "dsrc": ov.get("dsrc", []),
            "onote": ov.get("note", ""),
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
