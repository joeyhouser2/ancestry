"""Find gaps in the cached tree and write a prioritized to-do list.

Usage (from the repo root, after fetch_tree.py):
    python src/find_gaps.py
    python src/find_gaps.py --tree data/tree.json --top 50

Writes:
    data/gaps.json   one entry per person with their gaps and a priority score
    data/gaps.md     readable to-do list, highest priority first
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikitree_api import ROOT  # noqa: E402

# (code, weight, description). Higher weight = more valuable to fix.
GAPS = {
    "no_parents":       (10, "No parents linked (end of line)"),
    "no_father":        (7,  "No father linked"),
    "no_mother":        (7,  "No mother linked"),
    "unsourced":        (6,  "No sources cited"),
    "weak_sources":     (3,  "Only personal-knowledge style sources"),
    "no_birth_date":    (5,  "Birth date missing"),
    "no_birth_place":   (4,  "Birth place missing"),
    "no_death_date":    (3,  "Death date missing"),
    "no_death_place":   (2,  "Death place missing"),
    "partial_birth":    (1,  "Birth date is year/month only"),
    "partial_death":    (1,  "Death date is year/month only"),
    "uncertain_dates":  (1,  "Date marked uncertain/before/after"),
    "vague_place":      (2,  "Place is only a country/state"),
    "place_format":     (1,  "Place not in standard format (e.g. 'Meadville PA')"),
    "hidden_parent":    (0,  "A parent exists but is hidden from your login"),
}

# {{Citation Needed}} is an inline tag on one claim, so it doesn't mean the whole profile is unsourced.
UNSOURCED_TEMPLATES = {"unsourced", "needs sources"}
US_STATES = {
    "alabama","alaska","arizona","arkansas","california","colorado","connecticut","delaware",
    "florida","georgia","hawaii","idaho","illinois","indiana","iowa","kansas","kentucky",
    "louisiana","maine","maryland","massachusetts","michigan","minnesota","mississippi",
    "missouri","montana","nebraska","nevada","new hampshire","new jersey","new mexico",
    "new york","north carolina","north dakota","ohio","oklahoma","oregon","pennsylvania",
    "rhode island","south carolina","south dakota","tennessee","texas","utah","vermont",
    "virginia","washington","west virginia","wisconsin","wyoming",
}
US_ABBR = {
    "al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il","in","ia","ks","ky","la",
    "me","md","ma","mi","mn","ms","mo","mt","ne","nv","nh","nj","nm","ny","nc","nd","oh","ok",
    "or","pa","ri","sc","sd","tn","tx","ut","vt","va","wa","wv","wi","wy",
}
COUNTRIES = {
    "ireland","germany","poland","hungary","england","scotland","wales","france","italy",
    "austria","switzerland","netherlands","holland","prussia","bavaria","canada","usa",
    "united states","united states of america","united kingdom","uk","slovakia","czechia",
    "czech republic","russia","ukraine","sweden","norway","denmark","belgium","spain","mexico",
}


def place_state(pl: str) -> str:
    """'vague' (country/state only), 'format' (no commas, e.g. 'Meadville PA'), or 'ok'."""
    s = " ".join(pl.replace(".", "").split()).lower()
    if s in US_STATES or s in US_ABBR or s in COUNTRIES:
        return "vague"
    if "," not in pl:
        return "format"
    return "ok"


WEAK_SOURCE_RE = re.compile(r"(personal|firsthand|first-hand) (knowledge|recollection)|family (records|knowledge)", re.I)


def date_state(d: str | None) -> str:
    """'missing', 'partial', or 'full' for a WikiTree YYYY-MM-DD date."""
    if not d or d.startswith("0000"):
        return "missing"
    if d.endswith("-00"):
        return "partial"
    return "full"


def sources_state(p: dict) -> str:
    """'none', 'weak', or 'ok' based on the biography's citations."""
    templates = {(t.get("name") or "").lower() for t in (p.get("Templates") or []) if isinstance(t, dict)}
    if templates & UNSOURCED_TEMPLATES:
        return "none"
    bio = p.get("bio") or p.get("Bio") or ""
    refs = len(re.findall(r"<ref[\s>/]", bio, re.I))
    m = re.search(r"==\s*Sources\s*==(.*)", bio, re.I | re.S)
    tail = m.group(1) if m else ""
    tail = re.sub(r"<references\s*/?>|\[\[Category:[^\]]*\]\]|\{\{[^}]*\}\}|^\s*[*#:]\s*$", "", tail, flags=re.I | re.M)
    tail = re.sub(r"==\s*Acknowledg\w*\s*==.*", "", tail, flags=re.I | re.S).strip()
    # Source-type templates (FindAGrave, FamilySearch, Census...) count as citations.
    has_source_templates = any(t in templates for t in ("findagrave", "familysearch", "familysearch record", "census"))
    if not refs and not tail and not has_source_templates:
        return "none"
    text = " ".join(re.findall(r"<ref[^>]*>(.*?)</ref>", bio, re.I | re.S)) + " " + tail
    if WEAK_SOURCE_RE.search(text) and refs <= 1 and len(tail) < 200:
        return "weak"
    return "ok"


def ahnentafel(people: dict, root_id: str | None) -> dict[str, int]:
    """Map person Id -> Ahnentafel number (root=1, father=2n, mother=2n+1)."""
    nums: dict[str, int] = {}
    if not root_id:
        return nums
    queue = [(str(root_id), 1)]
    while queue:
        pid, n = queue.pop()
        if pid in nums or pid not in people:
            continue
        nums[pid] = n
        p = people[pid]
        if (p.get("Father") or 0) > 0:
            queue.append((str(p["Father"]), 2 * n))
        if (p.get("Mother") or 0) > 0:
            queue.append((str(p["Mother"]), 2 * n + 1))
    return nums


def relation(n: int | None) -> str:
    if not n:
        return ""
    if n == 1:
        return "self"
    gen = n.bit_length() - 1
    side = "father's side" if bin(n)[3] == "0" else "mother's side"
    who = "father" if n % 2 == 0 else "mother"
    if gen == 1:
        return who
    prefix = "grand" if gen == 2 else ("great-" * (gen - 2)) + "grand"
    return f"{prefix}{who} ({side})"


def analyse(p: dict, max_gen: int | None) -> list[str]:
    gaps: list[str] = []
    living = bool(p.get("IsLiving"))
    gen = (p.get("Meta") or {}).get("Degrees")
    ds = p.get("DataStatus") or {}

    father, mother = p.get("Father") or 0, p.get("Mother") or 0
    if father < 0 or mother < 0:
        gaps.append("hidden_parent")
    if father == 0 and mother == 0:
        gaps.append("no_parents")
    elif father == 0:
        gaps.append("no_father")
    elif mother == 0:
        gaps.append("no_mother")

    src = sources_state(p)
    if src == "none":
        gaps.append("unsourced")
    elif src == "weak":
        gaps.append("weak_sources")

    b = date_state(p.get("BirthDate"))
    if b == "missing":
        gaps.append("no_birth_date")
    elif b == "partial":
        gaps.append("partial_birth")
    if not (p.get("BirthLocation") or "").strip():
        gaps.append("no_birth_place")

    if not living:
        d = date_state(p.get("DeathDate"))
        if d == "missing":
            gaps.append("no_death_date")
        elif d == "partial":
            gaps.append("partial_death")
        if not (p.get("DeathLocation") or "").strip():
            gaps.append("no_death_place")

    if any(ds.get(k) in ("guess", "before", "after") for k in ("BirthDate", "DeathDate")):
        gaps.append("uncertain_dates")
    places = [pl for pl in (p.get("BirthLocation"), None if living else p.get("DeathLocation")) if pl]
    states = {place_state(pl) for pl in places}
    if "vague" in states:
        gaps.append("vague_place")
    if "format" in states:
        gaps.append("place_format")
    return gaps


def display_name(p: dict) -> str:
    parts = [p.get("FirstName"), p.get("MiddleName"), p.get("LastNameAtBirth")]
    name = " ".join(x for x in parts if x)
    cur = p.get("LastNameCurrent")
    if cur and cur != p.get("LastNameAtBirth"):
        name += f" ({cur})"
    return name or p.get("Name") or "?"


def years(p: dict) -> str:
    b = (p.get("BirthDate") or "")[:4]
    d = (p.get("DeathDate") or "")[:4]
    b = "" if b in ("", "0000") else b
    d = "" if d in ("", "0000") else d
    if p.get("IsLiving"):
        return f"b. {b}" if b else "living"
    return f"{b or '?'}–{d or '?'}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", default=str(ROOT / "data" / "tree.json"))
    ap.add_argument("--out-dir", default=None, help="defaults to the tree file's folder")
    ap.add_argument("--top", type=int, default=0, help="limit the markdown list (0 = all)")
    args = ap.parse_args()

    tree_path = Path(args.tree)
    if not tree_path.exists():
        print(f"{tree_path} not found. Run src/fetch_tree.py first.")
        return 1
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    people: dict = tree["people"]
    out_dir = Path(args.out_dir) if args.out_dir else tree_path.parent

    ahn = ahnentafel(people, tree.get("root_id"))
    hidden = [p for p in people.values() if not p.get("Name")]
    rows = []
    for pid, p in people.items():
        if not p.get("Name"):
            continue
        gaps = analyse(p, tree.get("ancestors"))
        if not gaps:
            continue
        score = sum(GAPS[g][0] for g in gaps)
        rows.append({
            "id": p.get("Id"),
            "wikitree_id": p["Name"],
            "name": display_name(p),
            "years": years(p),
            "generation": (p.get("Meta") or {}).get("Degrees"),
            "ahnentafel": ahn.get(pid),
            "relation": relation(ahn.get(pid)),
            "living": bool(p.get("IsLiving")),
            "privacy": p.get("Privacy"),
            "score": score,
            "gaps": gaps,
            "url": f"https://www.wikitree.com/wiki/{p['Name']}",
        })
    rows.sort(key=lambda r: (-r["score"], r["generation"] if r["generation"] is not None else 99))

    visible = len(people) - len(hidden)
    counts = Counter(g for r in rows for g in r["gaps"])
    (out_dir / "gaps.json").write_text(json.dumps({
        "root": tree.get("root"), "fetched": tree.get("fetched"),
        "profiles_visible": visible, "profiles_hidden": len(hidden),
        "gap_counts": counts, "people": rows,
    }, indent=1, ensure_ascii=False), encoding="utf-8")

    lines = [
        f"# Gap report for {tree.get('root')}",
        "",
        f"Tree fetched {tree.get('fetched')} — {visible} visible profiles, "
        f"{len(hidden)} hidden from this login, {len(rows)} with gaps.",
        "",
        "## Summary",
        "",
        "| Gap | People |",
        "|---|---|",
    ]
    for code, (w, desc) in sorted(GAPS.items(), key=lambda kv: -kv[1][0]):
        if counts.get(code):
            lines.append(f"| {desc} | {counts[code]} |")
    lines += ["", "## To-do (highest priority first)", "",
              "| # | Person | Years | Relation | Gaps | Score |", "|---|---|---|---|---|---|"]
    shown = rows[: args.top] if args.top else rows
    for i, r in enumerate(shown, 1):
        gap_text = "; ".join(GAPS[g][1] for g in r["gaps"])
        who = f"[{r['name']}]({r['url']}) `{r['wikitree_id']}`"
        lines.append(f"| {i} | {who} | {r['years']} | {r['relation']} | {gap_text} | {r['score']} |")
    if hidden:
        lines += ["", f"_{len(hidden)} profiles are hidden. Ask their managers to add you "
                  "to the Trusted List, or log in as a manager, to include them._"]
    (out_dir / "gaps.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"{len(rows)} of {visible} visible profiles have gaps; {len(hidden)} hidden.")
    for code, n in counts.most_common():
        print(f"  {GAPS[code][1]}: {n}")
    print(f"Wrote {out_dir / 'gaps.md'} and {out_dir / 'gaps.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
