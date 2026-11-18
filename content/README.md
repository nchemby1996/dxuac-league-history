# content/ — optional narrative

Empty on purpose. Narrative writing waits until the 2026 season is complete.
Until a file exists, each page shows a "Coming after the 2026 season" placeholder.

| File | Appears on |
|---|---|
| `home.md` | Home page, "The story so far" |
| `seasons/<YEAR>.md` (e.g. `seasons/2014.md`) | That season's page, above the tabs |
| `owners/<OWNER_ID>.md` (e.g. `owners/OWNER_006.md`) | That owner's page, above the tabs |
| `redactions.json` | Optional team-name masking (see below) |

Markdown supported: `#` headings, paragraphs, `-` lists, `**bold**`, `*italic*`, `[links](url)`.
Narratives are facts-first: no predictions or private owner analysis belong here.

## Team-name redactions

```json
{
  "team_names_by_name": { "Exact ESPN team name": "Replacement" },
  "team_names_by_season_owner": { "2015:OWNER_002": "Replacement" }
}
```

Applied at build time everywhere a team name appears (standings, results, drafts, search).
The data bundle in `data/` is never edited.
