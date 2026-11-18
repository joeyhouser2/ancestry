"""Turn a draft (drafts/<key>.json) into a fill spec for WikiTree's Edit Profile form.

Prints JSON: {"fields": {element_id: value}, "radios": [radio_id, ...], "bio": str, "summary": str}
Only plain profile fields are mapped; relationship changes (Father/Mother/Spouse) are done by hand.
"""
import json
import sys
from pathlib import Path

FIELD_IDS = {
    "FirstName": "mFirstName", "MiddleName": "mMiddleName", "Nicknames": "mNicknames",
    "LastNameCurrent": "mLastNameCurrent", "LastNameOther": "mLastNameOther",
    "BirthDate": "mBirthDate", "BirthLocation": "mBirthLocation",
    "DeathDate": "mDeathDate", "DeathLocation": "mDeathLocation",
}
DATE_STATUS = {"about": "guess", "guess": "guess", "certain": "certain", "before": "before", "after": "after"}
NAME_STATUS = {"guess": "1", "about": "1", "certain": "2"}


def spec(draft: dict) -> dict:
    fields, radios, manual = {}, [], []
    for c in draft.get("changes", []):
        f = c["field"]
        if f == "Biography":
            continue
        if f in FIELD_IDS:
            fields[FIELD_IDS[f]] = c["to"]
            st = c.get("status") or ""
            if st:
                if f in ("BirthDate", "DeathDate", "BirthLocation", "DeathLocation"):
                    s = DATE_STATUS.get(st)
                    if f.endswith("Location") and s in ("before", "after"):
                        s = None
                    if s:
                        radios.append(f"mStatus_{f}_{s}")
                elif st in NAME_STATUS:
                    radios.append(f"mStatus_{f}{NAME_STATUS[st]}")
        else:
            manual.append(f"{f}: {c['to']}")
    return {"fields": fields, "radios": radios, "bio": draft.get("biography", ""),
            "summary": draft.get("edit_summary", ""), "manual": manual}


JS = """const S=%s;
const set=(id,v)=>{const e=document.getElementById(id); if(!e) return id+':MISSING'; e.focus(); e.value=v; e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true})); e.blur(); return id+'='+e.value;};
const out=[]; for(const [id,v] of Object.entries(S.fields)) out.push(set(id,v));
for(const id of S.radios){const r=document.getElementById(id); if(r){r.checked=true; r.dispatchEvent(new Event('change',{bubbles:true})); out.push(id+'=checked');} else out.push(id+':MISSING');}
if(S.bio) out.push('bio chars: '+set('wpTextbox1',S.bio).length); out.push('summary chars: '+set('wpSummary',S.summary).length); if(S.manual.length) out.push('DO BY HAND: '+S.manual.join('; ')); out"""


if __name__ == "__main__":
    # python src/fill_spec.py drafts/X.json [--js]   (--js prints a script to paste into the edit page)
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    sys.stdout.reconfigure(encoding="utf-8")
    s = spec(d)
    print(JS % json.dumps(s, ensure_ascii=False) if "--js" in sys.argv else json.dumps(s, ensure_ascii=False))
