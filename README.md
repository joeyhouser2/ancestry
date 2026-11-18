# wikitree

Tools for filling out the Houser family tree on WikiTree, starting from
[Houser-1616](https://www.wikitree.com/wiki/Houser-1616).

The goal is to read the tree as it stands, find the gaps, research them, and use a
**local LLM agent** to prepare new and updated profiles. A human reviews and saves
every edit.

---

## 1. What WikiTree allows

| Capability | How | Notes |
|---|---|---|
| Read profiles, ancestors, descendants, relatives, search | Official API: `https://api.wikitree.com/api.php` | The API is **read-only**. Results are limited to what the logged-in user can see, based on the Trusted List and privacy levels. Docs: https://github.com/wikitree/wikitree-api |
| Create or edit profiles | Website edit forms only | There is no write endpoint. WikiTree says apps should send users through the site's own edit functions. |
| Bulk add | GEDCOM upload (GEDCOMpare) | The sanctioned bulk route. It matches people against existing profiles to avoid duplicates. |
| Fully automated edits (a "bot") | Only with a separate bot account approved by the WikiTree Team | **Running a bot from your personal account violates WikiTree's Terms of Service.** Contact the team before testing any automated changes. See https://www.wikitree.com/wiki/Help:Bots |

**So the design here is assisted editing:** the agent reads, researches, drafts and
pre-fills forms. Joey checks each pre-filled form and clicks **Save**. The agent
never clicks Save itself while it runs under the personal account.

---

## 2. Architecture

```
┌────────────┐   read-only    ┌─────────────────┐
│ WikiTree   │◄───────────────│ fetch_tree.py   │  getAncestors / getRelatives
│ API        │                │                 │  → data/tree.json
└────────────┘                └────────┬────────┘
                                       ▼
                              ┌─────────────────┐
                              │ find_gaps.py    │  missing parents, dates,
                              │                 │  places, sources
                              └────────┬────────┘  → data/gaps.json
                                       ▼
 records/ (scans, notes,      ┌─────────────────┐
 census, obits, GEDCOM) ─────►│ local LLM agent │  Ollama (e.g. qwen / llama)
                              │ draft_profiles  │  extracts facts + citations
                              └────────┬────────┘  → drafts/<id>.json
                                       ▼
                              ┌─────────────────┐
                              │ dedupe check    │  API searchPerson against
                              │                 │  existing WikiTree profiles
                              └────────┬────────┘
                                       ▼
                              ┌─────────────────┐
                              │ fill_form.py    │  Playwright, persistent
                              │ (Playwright)    │  logged-in browser profile;
                              │                 │  fills the Add/Edit form,
                              └────────┬────────┘  then STOPS
                                       ▼
                                Joey reviews → clicks Save
```

### Components

- **`fetch_tree.py`**: calls `getAncestors` / `getDescendants` / `getRelatives` for
  `Houser-1616` and caches the results to `data/tree.json`. Use an `appId`
  parameter (e.g. `appId=HouserTree`) as WikiTree asks. Private profiles need an
  authenticated API session (`clientLogin`); see the API docs.
- **`find_gaps.py`**: walks the tree and lists people with no parents, no birth or
  death date or place, or no sources. Output is a prioritized to-do list.
- **`draft_profiles.py`**: the local LLM step. It reads documents in `records/`
  and emits structured drafts that match `schema/profile_draft.json`. **Every fact
  must carry a citation**, because WikiTree requires sources. The model must not
  invent dates or places. A missing value stays null.
- **`dedupe.py`**: runs `searchPerson` on name and dates before anything is added,
  because WikiTree is a single shared tree and duplicates get merged by others.
- **`fill_form.py`**: Playwright with a **persistent browser profile** (log in to
  WikiTree once by hand). It opens the right "Add Father / Mother / Spouse /
  Child" or Edit page from the parent profile (these are the `Special:EditFamily`
  pages; check the exact URL parameters in the browser), fills the fields and the
  biography with its `== Sources ==` section, then **pauses**. Nothing is
  submitted automatically.

### Local model notes

- Ollama is already installed (`~/.ollama`). A mid-size instruct model with JSON
  mode or structured output is enough for record extraction.
- Ask for JSON that matches the schema, validate it with `pydantic`, and reject
  drafts that have uncited facts.
- Keep the LLM out of the browser-control loop. Playwright should run
  deterministic code against the validated draft, not free-form agent actions.

---

## 3. Proposed layout

```
wikitree/
├── README.md
├── requirements.txt        # requests now; pydantic, playwright, ollama later
├── schema/
│   └── profile_draft.json  # fields for a new or updated profile + citations
├── records/                # source documents (gitignored if private)
├── data/                   # API caches: tree.json, gaps.json
├── drafts/                 # LLM-produced drafts awaiting review
├── src/
│   ├── wikitree_api.py     # read-only API client + login/session cache
│   ├── fetch_tree.py
│   ├── find_gaps.py
│   ├── draft_profiles.py
│   ├── dedupe.py
│   └── fill_form.py
└── .browser-profile/       # Playwright persistent login (gitignored)
```

**Privacy:** living people's data and the browser profile must never be committed.
Add `records/`, `data/`, `drafts/` and `.browser-profile/` to `.gitignore` if this
repo is ever pushed.

---

## 4. Getting started (first session)

Steps 1–4 are built. Run them from the repo root:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python src/fetch_tree.py            # asks for WikiTree email + password the first time
python src/find_gaps.py             # writes data/gaps.md and data/gaps.json
```

- Houser-1616 is **Private**, so `fetch_tree.py` logs in through the API's
  `clientLogin` flow. By default it opens WikiTree's own login page in your
  browser and catches the redirect on a one-shot `127.0.0.1` server, so the
  script never sees your password. `--password-login` types the email and password
  in the terminal instead. Only the session cookies are cached, in
  `data/.session.json`, until they expire. `python src/fetch_tree.py --logout` clears them.
- **Every request must include `appId`, including the `clientLogin` ones.**
  WikiTree answers login requests without it with HTTP 429 `"Limit exceeded."`
  (seen 2026-11-16). The same request with `appId=HouserTree` works.
- Options: `--ancestors N` (default 25, the max), `--descendants N` (max 10),
  `--key Other-123`, `--no-login` (public data only).
- `getAncestors` is deprecated. The fetcher uses `getPeople&ancestors=N` and pages
  through results with `start` as a record offset.
- `find_gaps.py` scores each person. End-of-line ancestors and unsourced profiles
  rank highest, then missing birth/death dates and places, then partial or
  uncertain dates and vague places. Each row gives the Ahnentafel relation
  (for example "great-grandmother (mother's side)") and a link.

### Tree viewer

```
python src/fetch_tree.py --ancestors 25
python src/build_viewer.py          # writes data/tree.html
```

Open `data/tree.html` in a browser, or serve it with the `tree-viewer` entry in
`.claude/launch.json` (http://localhost:8737/tree.html, bound to 127.0.0.1). It
shows a clickable pedigree color-coded by gaps, a filterable to-do list, and per-person:
- facts and gaps;
- notes from `data/research_notes.json` (conflict flags, leads, family letters);
- records to look for, chosen by era and place (`src/research.py`);
- search links (Ancestry, FamilySearch, Find a Grave, Newspapers.com, Geneteka, IrishGenealogy);
- the sources already cited on WikiTree.

It embeds living relatives' data, so it stays in `data/` and is never published.

Next:

5. Put the first batch of source documents in `records/`. The first one is
   Donald Bigg's 2022 letter (`records/2022-09-28_donald-bigg_ancestors-letter.*`).
6. Build `draft_profiles.py` against Ollama and test it on one record.
7. Build `fill_form.py` and run it on **one** draft. Confirm the pre-filled form
   looks right before saving by hand.

### Alternative for big batches

If many people come from one source, such as an Ancestry or FamilySearch tree,
export a GEDCOM and use WikiTree's GEDCOMpare instead of adding them one at a time.

### If full automation is ever wanted

Request a bot account from the WikiTree Team first. Its Last Name at Birth must be
"WikiTree", and it needs community approval. Until then, keep the human Save step.
