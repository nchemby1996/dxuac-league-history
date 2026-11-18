# DJUAC League History — Official League Archives

A public, evidence-backed history of the D.J.U.A.C. ESPN fantasy football league, 2007–2025,
published as a static website on GitHub Pages.

## Structure

```
data/            Sanitized JSON bundle exported from the private data repository (committed)
content/         Optional narrative markdown + team-name redactions (empty for now; see content/README.md)
site/build.py    Static site generator: Python standard library only, no dependencies
site/tokens.py   Design tokens (shadcn/ui variable names); core values from site/shared-design-tokens.json
site/assets/     style.css (one shared stylesheet) and app.js (small vanilla JS)
site/check_site.py  Link checker + privacy guards (run in CI)
.github/workflows/pages.yml  Builds, checks and deploys _site/ to GitHub Pages
_site/           Build output (git-ignored)
```

Pages: Home, Champions, Seasons (index + one per season: standings, playoffs, weekly results,
top performances, draft board, trades from 2018), Owners (index + one per owner: career stats,
seasons, head-to-head, draft, records held, trades), Record Book, Head-to-Head matrix,
Search (also Ctrl/⌘-K on every page), About/Methodology.

## Rebuilding

1. In the private data repo (`dxuac-league-history-data`), regenerate analytics if needed, then export:
   ```bash
   PYTHONPATH=src python -m djuac_history.public_export --out public_data
   ```
   The exporter refuses to write if it finds GUIDs, identity fields, raw payloads, paths, or any
   season after its `MAX_PUBLIC_SEASON`.
2. Replace this repo's `data/` with the bundle: `rm data/*.json && cp ../dxuac-league-history-data/public_data/*.json data/`
3. Build and check locally:
   ```bash
   python site/build.py         # writes _site/
   python site/check_site.py    # every link resolves; no GUIDs or in-progress-season content
   python -m http.server -d _site 8000   # preview at http://localhost:8000
   ```
4. Commit `data/` (and any `content/` changes) and open a PR. Merging to `main` deploys.

Adding a season after it ends: raise `MAX_PUBLIC_SEASON` in the data repo's exporter (after the
commissioner approves the final snapshot), re-export, copy, build. Nothing is hardcoded per season.

Design tokens: `site/shared-design-tokens.json` is a verbatim copy of the data repo's
`publications/newsletter_data/design_tokens.json`, so the site and newsletter match. Update it there
first, then copy it here. The build also publishes `assets/design-tokens.json`.

## GitHub Pages setup (one time, repository owner)

Settings → Pages → Build and deployment → Source: **GitHub Actions**.
The workflow does not (and cannot) enable Pages itself. After that, every push to `main` deploys to
`https://nchemby1996.github.io/dxuac-league-history/`.

## Public / private boundary

This repository is world-readable. It contains only league facts: results, standings, drafts,
trades, records, and owners' displayed names with permanent owner IDs.

It must never contain:
- ESPN account identifiers (member GUIDs, SWID, cookies, tokens) or raw ESPN responses
- anything from the private data repo's `identity/`, `raw/` or `manifests/` folders
- the commissioner's private owner intelligence dossier, predictions, or strategic analysis
- data from a season that is not yet final

The exporter's validator and `site/check_site.py` both enforce this; CI fails if a guard trips.
