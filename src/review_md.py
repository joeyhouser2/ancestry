"""Regenerate drafts/REVIEW.md from every drafts/*.json, in dependency order.

Usage: python src/review_md.py
Edit ORDER when drafts are added; any draft not listed is appended under "Other".
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "drafts"

ORDER = [
    ("Mother's father's side: Bigg / Hoene / McGlynn / Sopko", [
        "Bigg-110", "Bigg-111", "NEW-Bigg-AlfredSr", "NEW-Avery-Hattie", "NEW-Bigg-FrederickRichard", "NEW-Markwell-MaryAnn", "NEW-Markwell-Benjamin-Elizabeth", "NEW-Bigg-Richard1801", "NEW-Shore-Elizabeth", "HOLD-Shore-Thomas-MaryEkins", "NEW-Bigg-RichardSr-MaryMantle", "NEW-Bigg-Edward-MaryCouchman", "NEW-Bigg-John1745", "HOLD-Mantle-John-AnnShrubsole", "NEW-Avery-William", "NEW-Carter-Emily", "Hoene-18", "Hoene-55", "NEW-Schmidt-Margaretha", "NEW-Hohn-Adam",
        "McGlynn-103", "McGlynn-104", "McGlynn-468", "NEW-McGlynn-Ellen", "Sopko-5", "NEW-Sopko-John", "NEW-Sopko-Mary"]),
    ("Mother's mother's side: McElligott / Carroll / O'Donnell / Currier", [
        "McElligott-60", "McElligott-60-father", "NEW-McElligott-JamesThomas", "NEW-McElligott-Thomas", "NEW-Sullivan-Mary", "Carroll-4441", "Carroll-4441-parents",
        "NEW-ODonnell-James", "NEW-Mullen-Susan", "NEW-ODonnell-Jeremiah", "NEW-OHea-Eliza", "NEW-Mullen-James", "NEW-McElaney-Catherine", "Currier-800", "NEW-Currier-Lawson", "NEW-Murphy-Hannah", "NEW-Murphy-parents",
        "NEW-Currier-Benjamin", "NEW-Wright-Elizabeth", "Currier-1180", "Cilley-175"]),
    ("Father's side: Drost / Bąk / Chłap / Bunce / Moore / Bauer", [
        "Drost-122", "NEW-Bak-Szymon-JadwigaMozdzan", "NEW-Chlap-Antoni-ReginaJakiela", "Bunce-393", "Conlan-245",
        "Moore-35142", "Unknown-381847", "Bauer-2326", "NEW-Bower-Frederick"]),
]


def heading(k, v):
    if v.get("wikitree_id") and v["action"] == "edit":
        return v["wikitree_id"] + (" — father link" if k.endswith("-father") else "")
    fn = next((c["to"] for c in v["changes"] if c["field"] == "FirstName"), None)
    ln = next((c["to"] for c in v["changes"] if c["field"] == "LastNameAtBirth"), "")
    rel = v.get("relation", {})
    return f"NEW: {fn} {ln} ({rel.get('as')} of {rel.get('to')})" if fn else f"NEW: {rel.get('as')} of {rel.get('to')}"


def main():
    files = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(OUT.glob("*.json"))}
    listed = [k for _, ks in ORDER for k in ks]
    sections = [(t, [k for k in ks if k in files]) for t, ks in ORDER]
    other = [k for k in files if k not in listed]
    if other:
        sections.append(("Other", other))
    ready = sum(1 for v in files.values() if v.get("status") == "ready")
    L = ["# WikiTree edit drafts — review before saving", "",
         f"{len(files)} drafts ({ready} ready). **Nothing is saved on WikiTree until you click Save on each page.**", "",
         "**Before you start:** most of these profiles are managed by your dad, Steven Houser (Houser-1612). Let him know what you're changing. "
         "Bigg-110, McGlynn-103 and McElligott-60 are Private-level (30) and need you on their Trusted List.", "",
         "Work top to bottom: each section is in the order the links depend on. A NEW profile is created from the Add Father / Add Mother link on the profile it attaches to.", ""]
    for title, keys in sections:
        L += [f"## {title}", ""]
        for k in keys:
            v = files[k]
            L += [f"### {heading(k, v)}" + ("" if v.get("status") == "ready" else "  _(on hold)_"), "", v["summary"], ""]
            if v.get("hold_reason"):
                L += [f"**On hold:** {v['hold_reason']}", ""]
            if v.get("manager_note"):
                L += [f"_{v['manager_note']}_", ""]
            if v.get("edit_url"):
                L += [f"Open: {v['edit_url']}", ""]
            if v.get("changes"):
                L += ["| Field | Now | Change to | Status |", "|---|---|---|---|"]
                for c in v["changes"]:
                    if c["field"] != "Biography":
                        L.append(f"| {c['field']} | {c.get('from', '') or '—'} | **{c['to']}** | {c.get('status', '') or ''} |")
            if v.get("biography"):
                L += ["", "Biography (replace the whole box):", "", "```", v["biography"].rstrip(), "```"]
            if v.get("edit_summary"):
                L += ["", f"Edit summary: `{v['edit_summary']}`"]
            L.append("")
    (OUT / "REVIEW.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"REVIEW.md: {len(files)} drafts")


if __name__ == "__main__":
    sys.exit(main())
