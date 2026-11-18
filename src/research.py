"""Rule-based research suggestions and search links for one profile.

Suggestions are starting points chosen from the person's era and places,
not facts. Every lead still has to be checked against the record itself.
"""

from __future__ import annotations

import re
import urllib.parse

US_HINTS = re.compile(
    r"united states|\busa\b|\b(pa|ny|nj|ma|oh|ct|fl|il|mi|in|wi|mn|md|va|ca)\b|pennsylvania|new york|"
    r"new jersey|massachusetts|ohio|connecticut|illinois|michigan|indiana|virginia|maryland|"
    r"colony of|province of|new netherland|east jersey|west jersey", re.I)


def year(d: str | None) -> int | None:
    if d and d[:4].isdigit() and d[:4] != "0000":
        return int(d[:4])
    return None


def region(place: str | None) -> str:
    p = (place or "").lower()
    if not p:
        return ""
    if re.search(r"colony|province of|new netherland|east jersey|west jersey", p):
        return "colonial"
    if US_HINTS.search(p):
        return "us"
    for key, names in {
        "ireland": ["ireland", "antrim", "ulster", "cork", "kerry", "galway", "mayo", "dublin", "tipperary"],
        "scotland": ["scotland", "ayrshire", "wigtown", "kirkcudbright", "midlothian", "aberdeen"],
        "england": ["england", "london", "yorkshire", "kent", "essex", "hereford"],
        "germany": ["germany", "deutschland", "palatin", "pfalz", "kaiserslautern", "bavaria", "prussia",
                    "hessen", "baden", "württemberg", "heiliges römisches", "holy roman"],
        "switzerland": ["switzerland", "schweiz", "bern"],
        "poland": ["poland", "polska", "galicia", "krosno", "rzeszów", "rzeszow", "posen", "poznan", "dukla"],
        "hungary": ["hungary", "slovakia", "magyar"],
        "netherlands": ["netherlands", "holland", "liège", "liege", "belgium"],
        "france": ["france", "la rochelle"],
        "denmark": ["denmark", "danmark"],
    }.items():
        if any(n in p for n in names):
            return key
    return "other"


def suggestions(p: dict, gaps: list[str], us_hint: bool = False) -> list[str]:
    """us_hint: a child was born or died in the US, so this person probably lived there."""
    b, d = year(p.get("BirthDate")), year(p.get("DeathDate"))
    living = bool(p.get("IsLiving"))
    male = p.get("Gender") == "Male"
    br, dr = region(p.get("BirthLocation")), region(p.get("DeathLocation"))
    out: list[str] = []
    need_parents = any(g in gaps for g in ("no_parents", "no_father", "no_mother"))
    in_us = "us" in (br, dr) or (us_hint and dr in ("", "us"))
    immigrant = br not in ("", "us", "colonial") and (dr == "us" or (us_hint and not dr))

    if living:
        return ["Living person: don't research or publish details beyond what the family agrees to."]

    if in_us and (d or 0) >= 1880:
        out.append(f"Death certificate ({d or 'death year unknown'}). From about 1900 most US state "
                   "certificates name both parents, including the mother's maiden name.")
        out.append("Obituary in a local newspaper (Newspapers.com, GenealogyBank, Chronicling America "
                   "for pre-1964). Obituaries often name parents, siblings and the home town abroad.")
    if in_us and b and b >= 1865 and (d is None or d >= 1937):
        out.append("Social Security Applications and Claims Index (Ancestry). The SS-5 application "
                   "lists both parents' names.")
    if in_us and need_parents and b and b <= 1945:
        out.append("Marriage record. US marriage registers and licenses often name both sets of "
                   "parents (strong in MA, CT, NJ, OH).")
    if in_us and b:
        alive = [y for y in (1850, 1860, 1870, 1880, 1900, 1910, 1920, 1930, 1940, 1950)
                 if y >= b and (d is None or y <= d)]
        child = [y for y in alive if y - b <= 18] if br in ("us", "") else []
        if br not in ("us", "") and alive:
            alive = [y for y in alive if y - b >= 10] or alive  # immigrants: adult censuses after arrival
        if child:
            out.append(f"Census as a child ({', '.join(map(str, child))}): find them in their parents' "
                       "household. 1880 onward gives relationships to the head of household.")
        elif alive:
            out.append(f"US censuses ({', '.join(map(str, alive[:6]))}): residence, household, "
                       "immigration year, and parents' birthplaces (1880 onward).")
    if male and in_us and b and 1872 <= b <= 1900:
        out.append("WWI draft registration (1917–18): exact birth date and place, address, nearest relative.")
    if male and in_us and b and 1877 <= b <= 1897 and (d is None or d >= 1942):
        out.append("WWII 'Old Man's Draft' registration (1942): exact birth date and place.")
    if immigrant or (br not in ("", "us", "colonial") and b and b >= 1820):
        out.append("Passenger lists and naturalization papers. Arrivals after 1906 usually give the "
                   "home town and a relative left behind; naturalizations after 1906 list birth "
                   "date and place.")
    if br == "ireland":
        out.append("Irish records: civil registration from 1864 (irishgenealogy.ie), Catholic parish "
                   "registers (registers.nli.ie), Griffith's Valuation (askaboutireland.ie). "
                   "You need the parish or townland, usually from US records first.")
    if br == "germany":
        out.append("German church books: Archion (Protestant), Matricula (Catholic), FamilySearch "
                   "catalog by town. Palatinate emigrants are often in the Palatines to America indexes.")
    if br == "poland":
        out.append("Polish/Galician parish records: Geneteka (geneteka.genealodzy.pl) index, "
                   "metryki.genealodzy.pl scans, and the FamilySearch catalog for the parish.")
    if br == "hungary":
        out.append("'Hungary' before 1918 often means today's Slovakia, Carpathian Ruthenia or "
                   "Burgenland. Slovakia church books (1592–1935) are free on FamilySearch once the "
                   "village is known (check passenger lists and naturalization).")
    if br == "switzerland":
        out.append("Swiss church books: Staatsarchiv Bern holds digitized Kirchenbücher; "
                   "FamilySearch has films by parish.")
    if br == "scotland":
        out.append("ScotlandsPeople: Old Parish Registers before 1855, statutory records after. "
                   "Gentry lines: check published sources (Scots Peerage), not online trees.")
    if br in ("colonial", "netherlands", "france", "denmark"):
        out.append("Colonial / New Netherland: Dutch Reformed church records, NY & NJ wills and land "
                   "records, and the NYG&B Record. WikiTree's New Netherland Settlers project "
                   "may already cover this family.")
    if b and b < 1500:
        out.append("Medieval profile: rely on scholarly sources (e.g. Complete Peerage, Scots Peerage, "
                   "Royal Ancestry). Ask the relevant WikiTree project before changing anything.")
    if "unsourced" in gaps:
        out.append("No sources yet. Even one solid record (census, grave, death record) cited "
                   "inline makes the profile much more trustworthy.")
    if "place_format" in gaps or "vague_place" in gaps:
        out.append("Expand places to WikiTree's format: Town, County, State, Country, "
                   "as named at the time of the event.")
    return out


def links(p: dict) -> list[tuple[str, str]]:
    first = (p.get("FirstName") or "").strip()
    last = (p.get("LastNameAtBirth") or "").strip()
    cur = (p.get("LastNameCurrent") or "").strip()
    b, d = year(p.get("BirthDate")), year(p.get("DeathDate"))
    q = urllib.parse.urlencode
    out = [("WikiTree profile", f"https://www.wikitree.com/wiki/{p['Name']}")]
    if p.get("IsLiving"):
        return out
    anc = {"name": f"{first}_{last}"}
    if b:
        anc["birth"] = str(b)
    if d:
        anc["death"] = str(d)
    out.append(("Ancestry search", "https://www.ancestry.com/search/?" + q(anc)))
    fs = {"q.givenName": first, "q.surname": last}
    if b:
        fs |= {"q.birthLikeDate.from": b - 2, "q.birthLikeDate.to": b + 2}
    if d:
        fs |= {"q.deathLikeDate.from": d - 2, "q.deathLikeDate.to": d + 2}
    out.append(("FamilySearch records", "https://www.familysearch.org/search/record/results?" + q(fs)))
    fg = {"firstname": first, "lastname": cur or last}
    if b:
        fg["birthyear"], fg["birthyearfilter"] = b, 2
    if d:
        fg["deathyear"], fg["deathyearfilter"] = d, 2
    out.append(("Find a Grave", "https://www.findagrave.com/memorial/search?" + q(fg)))
    if b and b >= 1850 and region(p.get("DeathLocation")) == "us" and d:
        out.append(("Newspapers.com", "https://www.newspapers.com/search/?" +
                    q({"query": f'"{first} {cur or last}"', "dr_year": f"{d}-{d + 1}"})))
    if region(p.get("BirthLocation")) == "poland":
        out.append(("Geneteka", "https://geneteka.genealodzy.pl/index.php?" +
                    q({"op": "se", "lang": "eng", "search_lastname": last})))
    if region(p.get("BirthLocation")) == "ireland":
        out.append(("IrishGenealogy.ie", "https://civilrecords.irishgenealogy.ie/churchrecords/search.jsp?" +
                    q({"firstname": first, "surname": last})))
    return out


def extract_sources(bio: str, limit: int = 8) -> list[str]:
    """Pull citation text out of a WikiTree biography."""
    if not bio:
        return []
    items = re.findall(r"<ref[^>/]*>(.*?)</ref>", bio, re.I | re.S)
    m = re.search(r"==\s*Sources\s*==(.*)", bio, re.I | re.S)
    if m:
        tail = re.split(r"==\s*Acknowledg", m.group(1), flags=re.I)[0]
        items += [ln for ln in re.split(r"\n\s*[*#]+", "\n" + tail)]
    out = []
    for it in items:
        t = re.sub(r"<references\s*/?>|<[^>]+>|\[\[Category:[^\]]*\]\]", " ", it)
        t = re.sub(r"\[(https?://\S+)\s+([^\]]+)\]", r"\2", t)
        t = re.sub(r"\[\[[^|\]]*\|([^\]]+)\]\]", r"\1", t)
        t = re.sub(r"'''?|\[\[|\]\]|\{\{[^}]*\}\}", "", t)
        t = " ".join(t.split()).strip(" *:")
        if len(t) > 8 and t not in out:
            out.append(t[:400])
    return out[:limit]
