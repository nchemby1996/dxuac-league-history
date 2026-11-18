#!/usr/bin/env python3
"""Build the D.J.U.A.C. Official League Archives static site.

    python site/build.py            # data/ + content/ -> _site/

Standard library only. All statistics come from the JSON bundle in data/ (exported from the
private data repository); optional narrative markdown comes from content/. Nothing is hardcoded
per season or per owner, so a new season is: export -> copy into data/ -> build.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tokens  # noqa: E402

REPO = HERE.parent
PLACEHOLDER = "Coming after the 2026 season"

NAV = [("Home", "index.html"), ("Champions", "champions/index.html"), ("Seasons", "seasons/index.html"),
       ("Owners", "owners/index.html"), ("Record Book", "records/index.html"),
       ("Head-to-Head", "head-to-head/index.html"), ("Storylines", "storylines/index.html"), ("About", "about/index.html")]


def e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ---------------------------------------------------------------------------- formatting

def fmt_pts(v) -> str:
    if v is None:
        return "–"
    v = float(v)
    return f"{v:,.0f}" if v.is_integer() else f"{v:,.2f}".rstrip("0").rstrip(".")


def fmt_pct(v) -> str:
    """Sports-style win percentage: .585"""
    if v is None:
        return "–"
    s = f"{float(v):.3f}"
    return s[1:] if s.startswith("0") else s


def fmt_num(v, digits=2) -> str:
    if v is None:
        return "–"
    if isinstance(v, int) or float(v).is_integer():
        return f"{int(float(v)):,}"
    return f"{float(v):,.{digits}f}"


def fmt_signed(v, digits=1) -> str:
    if v is None:
        return "–"
    return f"{float(v):+.{digits}f}"


def record_str(w, l, t=0) -> str:
    return f"{w}–{l}" + (f"–{t}" if t else "")


def ordinal(n) -> str:
    if n is None:
        return "–"
    n = int(n)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


# ---------------------------------------------------------------------------- tiny markdown

def markdown(text: str) -> str:
    """Headings, paragraphs, lists, **bold**, *italic*, [links](url). Enough for narrative content."""
    def inline(s):
        s = e(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*", r"<em>\1</em>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', s)
        return s
    out, para, items = [], [], []
    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>"); para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>"); items.clear()
    for line in text.splitlines():
        s = line.strip()
        if not s:
            flush(); continue
        m = re.match(r"(#{1,4})\s+(.*)", s)
        if m:
            flush(); lvl = min(len(m.group(1)) + 1, 4); out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>"); continue
        if re.match(r"[-*]\s+", s):
            if para:
                flush()
            items.append(re.sub(r"^[-*]\s+", "", s)); continue
        if items:
            flush()
        para.append(s)
    flush()
    return "\n".join(out)


# ---------------------------------------------------------------------------- data

class Data:
    def __init__(self, data_dir: Path, content_dir: Path):
        load = lambda n: json.loads((data_dir / n).read_text(encoding="utf-8"))
        self.meta = load("meta.json")
        self.owners = load("owners.json")
        self.seasons = load("seasons.json")
        self.matchups = load("matchups.json")
        self.career = {c["owner_id"]: c for c in load("career_stats.json")}
        self.team_seasons = load("team_seasons.json")
        self.h2h = load("head_to_head.json")
        self.records = load("records.json")
        self.draft = load("draft_picks.json")
        self.classes = load("draft_classes.json")
        self.trades = load("trades.json")
        self.coverage = load("coverage.json")
        self.storylines = load("storylines.json") if (data_dir / "storylines.json").exists() else []
        self.content_dir = content_dir
        self.owner = {o["owner_id"]: o for o in self.owners}
        self.season = {s["season"]: s for s in self.seasons}
        self._apply_redactions()

    def _apply_redactions(self):
        path = self.content_dir / "redactions.json"
        cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        by_name = {k: v for k, v in (cfg.get("team_names_by_name") or {}).items()}
        by_key = {k: v for k, v in (cfg.get("team_names_by_season_owner") or {}).items()}
        self.redacted = 0
        if not by_name and not by_key:
            return

        def fix(season, owner_id, name):
            new = by_key.get(f"{season}:{owner_id}") or by_name.get(name)
            if new is not None:
                self.redacted += 1
                return new
            return name

        for s in self.seasons:
            for row in s["standings"]:
                row["team_name"] = fix(s["season"], row["owner_id"], row["team_name"])
            for k in ("champion", "runner_up", "top_seed", "most_points"):
                if s.get(k):
                    s[k]["team_name"] = fix(s["season"], s[k]["owner_id"], s[k]["team_name"])
        for yr, games in self.matchups.items():
            for g in games:
                for side in (g["home"], g["away"]):
                    side["team_name"] = fix(int(yr), side["owner_id"], side["team_name"])
        for yr, picks in self.draft.items():
            for p in picks:
                p["team_name"] = fix(int(yr), p["owner_id"], p["team_name"])
        for t in self.team_seasons:
            t["team_name"] = fix(t["season"], t["owner_id"], t["team_name"])

    def name(self, owner_id) -> str:
        o = self.owner.get(owner_id)
        return o["name"] if o else (owner_id or "Unknown")

    def content(self, *parts) -> str | None:
        path = self.content_dir.joinpath(*parts)
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return markdown(path.read_text(encoding="utf-8"))
        return None


def owner_slug(d: Data, owner_id: str) -> str:
    return slug(d.name(owner_id))


# ---------------------------------------------------------------------------- page shell

ICON_SEARCH = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>'
ICON_SUN = '<svg class="theme-icon-light" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'
ICON_MOON = '<svg class="theme-icon-dark" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>'
ICON_TROPHY = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4zM17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3"/></svg>'


class Site:
    def __init__(self, d: Data, out: Path):
        self.d, self.out, self.pages = d, out, []

    def write(self, rel_path: str, title: str, body: str, active: str | None = None,
              crumbs: list[tuple[str, str | None]] | None = None, description: str = ""):
        depth = rel_path.count("/")
        root = "../" * depth
        nav = "".join(
            f'<li><a href="{root}{href}"{" aria-current=\"page\"" if label == active else ""}>{e(label)}</a></li>'
            for label, href in NAV)
        crumb_html = ""
        if crumbs:
            parts = [f'<li><a href="{root}index.html">Home</a></li>']
            for label, href in crumbs:
                parts.append(f'<li><a href="{root}{href}">{e(label)}</a></li>' if href
                             else f'<li><span aria-current="page">{e(label)}</span></li>')
            crumb_html = f'<nav class="breadcrumb" aria-label="Breadcrumb"><ol>{"".join(parts)}</ol></nav>'
        last = self.d.meta["last_season"]
        doc = f"""<!DOCTYPE html>
<html lang="en" data-root="{root}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · D.J.U.A.C. League Archives</title>
<meta name="description" content="{e(description or 'The Official League Archives of the D.J.U.A.C. fantasy football league, ' + str(self.d.meta['first_season']) + '–' + str(last) + '.')}">
<meta name="color-scheme" content="light dark">
<script>(function(){{var d=document.documentElement;d.classList.add("js");try{{var t=localStorage.getItem("djuac-theme");if(t)d.setAttribute("data-theme",t);}}catch(e){{}}}})();</script>
<link rel="stylesheet" href="{root}assets/style.css">
<link rel="icon" href="{root}assets/favicon.svg" type="image/svg+xml">
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="masthead">
  <div class="container bar">
    <a class="brand" href="{root}index.html"><span class="brand-mark">D.J.U.A.C.</span><span class="brand-sub">Official League Archives</span></a>
    <a class="search-btn" href="{root}search/index.html" data-open-search>{ICON_SEARCH}<span class="label">Search</span><kbd>Ctrl K</kbd></a>
    <button class="icon-btn" id="theme-toggle" type="button" aria-label="Toggle theme">{ICON_SUN}{ICON_MOON}</button>
  </div>
  <nav class="nav" aria-label="Main"><div class="container"><ul>{nav}</ul></div></nav>
</header>
<main id="main" tabindex="-1"><div class="container">
{crumb_html}
{body}
</div></main>
<footer class="site-footer"><div class="container">
  <p>D.J.U.A.C. · ESPN league history {self.d.meta['first_season']}–{last} · Data through the {last} season.
  Results are ESPN official scores. <a href="{root}about/index.html">Methodology &amp; data coverage</a>.</p>
</div></footer>
<dialog class="cmdk" id="cmdk" aria-label="Search the archives">
  <div class="cmdk-head">{ICON_SEARCH}<input class="cmdk-input" id="cmdk-input" type="search" role="combobox" aria-expanded="true" aria-controls="cmdk-list" aria-autocomplete="list" placeholder="Search owners, teams, seasons, players…" autocomplete="off" spellcheck="false"></div>
  <ul class="cmdk-list" id="cmdk-list" role="listbox" aria-label="Results"></ul>
  <div class="cmdk-foot"><span><kbd>↑</kbd> <kbd>↓</kbd> navigate</span><span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span></div>
</dialog>
<script src="{root}assets/app.js" defer></script>
</body>
</html>
"""
        path = self.out / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(doc, encoding="utf-8")
        self.pages.append(rel_path)
        return root


# ---------------------------------------------------------------------------- components

def badge(text, kind="outline", title=None) -> str:
    t = f' title="{e(title)}"' if title else ""
    return f'<span class="badge badge-{kind}"{t}>{e(text)}</span>'


def quality_badge(q) -> str:
    if q == "ESPN_RESCORED":
        return badge("ESPN rescored", "rescored", "ESPN recomputed player points; values do not reconcile with team scores")
    return badge("Verified", "verified", "Player points reconcile with team scores")


def placeholder(what: str) -> str:
    return (f'<div class="placeholder" role="note">{badge(PLACEHOLDER, "secondary")}'
            f'<p>{e(what)} will be written once the 2026 season is complete. Everything else on this page is generated from the data.</p></div>')


def table(headers: list[tuple[str, str]], rows: list[str], caption: str = "", sortable=True, cls="") -> str:
    """headers: (label, kind) kind in {'text','num','none'}; rows: prebuilt <tr> strings."""
    ths = []
    for label, kind in headers:
        num = " class=\"num\"" if kind == "num" else ""
        sort = f' data-sort="{kind}"' if sortable and kind in ("text", "num") else ""
        ths.append(f'<th scope="col"{num}{sort}>{label}</th>')
    cap = f"<caption>{caption}</caption>" if caption else ""
    classes = " ".join(c for c in ("sortable" if sortable else "", cls) if c)
    return (f'<div class="table-wrap"><table class="{classes}">{cap}<thead><tr>{"".join(ths)}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def expandable(headers, rows: list[str], shown: int = 5, sortable=False) -> str:
    """A leaderboard table that shows `shown` rows and expands to all rows on click."""
    if len(rows) <= shown:
        return table(headers, rows, sortable=sortable)
    marked = [r if i < shown else r.replace("<tr>", '<tr class="row-more">', 1) for i, r in enumerate(rows)]
    btn = (f'<button type="button" class="expand-btn" data-expand aria-expanded="false" '
           f'data-more="Show top {len(rows)}" data-less="Show top {shown}">Show top {len(rows)}</button>')
    return f'<div class="expandable">{table(headers, marked, sortable=sortable)}{btn}</div>'


def tabs(prefix: str, panels: list[tuple[str, str, str]]) -> str:
    """panels: (id, label, html). Without JS every panel renders stacked with its heading."""
    tl = "".join(f'<button role="tab" type="button" id="tab-{pid}" aria-controls="{pid}" aria-selected="false">{e(label)}</button>'
                 for pid, label, _ in panels)
    body = "".join(f'<section class="tab-panel" role="tabpanel" id="{pid}" aria-labelledby="tab-{pid}" tabindex="0">'
                   f'<h2 class="sr-only-when-tabs">{e(label)}</h2>{content}</section>' for pid, label, content in panels)
    return f'<div data-tabs="{prefix}"><div class="tabs-list" role="tablist" aria-label="Sections">{tl}</div>{body}</div>'


def stat_card(label, value, sub="") -> str:
    return (f'<div class="card stat"><div class="label">{e(label)}</div><div class="value">{value}</div>'
            + (f'<div class="sub">{sub}</div>' if sub else "") + "</div>")


def card(title, content, desc="", flush=False, footer="") -> str:
    head = f'<div class="card-header"><h3 class="card-title">{title}</h3>' + (f'<p class="card-desc">{desc}</p>' if desc else "") + "</div>"
    foot = f'<div class="card-footer">{footer}</div>' if footer else ""
    return f'<div class="card">{head}<div class="card-content{" flush" if flush else ""}">{content}</div>{foot}</div>'


# ---------------------------------------------------------------------------- helpers over data

def owner_link(d: Data, root: str, owner_id, team_name=None) -> str:
    if not owner_id or owner_id not in d.owner:
        return e(d.name(owner_id))
    link = f'<a href="{root}owners/{owner_slug(d, owner_id)}/index.html">{e(d.name(owner_id))}</a>'
    if team_name:
        link += f'<span class="team-name">{e(team_name)}</span>'
    return link


def season_link(root: str, season, anchor="") -> str:
    return f'<a href="{root}seasons/{season}/index.html{anchor}">{season}</a>'


def round_names(weeks: list[int]) -> dict[int, str]:
    names = ["Championship", "Semifinals", "Quarterfinals", "Wild Card"]
    ordered = sorted(set(weeks), reverse=True)
    return {w: (names[i] if i < len(names) else f"Round of week {w}") for i, w in enumerate(ordered)}


def title_game(d: Data, season: int):
    games = [g for g in d.matchups.get(str(season), []) if g["tier"] == "WINNERS_BRACKET"]
    if not games:
        return None
    final_week = max(g["week"] for g in games)
    s = d.season[season]
    ids = {s["champion"]["owner_id"], s["runner_up"]["owner_id"]}
    for g in games:
        if g["week"] == final_week and {g["home"]["owner_id"], g["away"]["owner_id"]} == ids:
            return g
    return None


def game_line(d: Data, root: str, g: dict) -> str:
    sides = []
    for side in (g["away"], g["home"]):
        won = g["winner_owner_id"] == side["owner_id"] and not g["tie"]
        cls = "w" if won else ("" if g["tie"] else "l")
        adj = f' <span class="adj" title="Commissioner adjustment">({fmt_signed(side["adjustment"], 0)} adj.)</span>' if side["adjustment"] else ""
        sides.append(f'<div class="{cls}">{owner_link(d, root, side["owner_id"])} <span class="team-name">{e(side["team_name"])}</span></div>'
                     f'<div class="score {cls}">{fmt_pts(side["score"])}{adj}</div>')
    return f'<div class="game">{"".join(sides)}</div>'


# ---------------------------------------------------------------------------- pages

def page_home(site: Site):
    d = site.d
    last = d.meta["last_season"]
    latest = d.season[last]
    champ_id = latest["champion"]["owner_id"]
    champ_row = next(r for r in latest["standings"] if r["owner_id"] == champ_id)
    games = sum(len(v) for v in d.matchups.values())
    tg = title_game(d, last)
    tg_line = ""
    if tg:
        winner = tg["home"] if tg["home"]["owner_id"] == champ_id else tg["away"]
        loser = tg["away"] if winner is tg["home"] else tg["home"]
        tg_line = f'Beat {e(d.name(loser["owner_id"]))} {fmt_pts(winner["score"])}–{fmt_pts(loser["score"])} in the title game.'
    root = ""
    banner = "".join(
        f'<a href="seasons/{s["season"]}/index.html"><div class="yr">{s["season"]}</div>'
        f'<div class="who">{e(d.name(s["champion"]["owner_id"]))}</div><div class="team-name">{e(s["champion"]["team_name"])}</div></a>'
        for s in sorted(d.seasons, key=lambda s: -s["season"]))
    # quick records: rank-1 entries from a curated set of record names (only if present)
    wanted = ["Most championships", "Most first-round byes", "Best regular-season win %",
              "Highest single-week score (era-adjusted)", "Longest winning streak (regular season)", "Most trades"]
    recs = {r["record"]: r for r in d.records}
    quick = []
    for name in wanted:
        r = recs.get(name)
        if not r:
            continue
        top = r["entries"][0]
        val = fmt_pct(top["value"]) if "%" in name else fmt_num(top["value"], 1)
        quick.append(f'<a class="card stat" href="records/index.html#{slug(r["category"] + "-" + name)}">'
                     f'<div class="label">{e(name)}</div><div class="value">{val}</div>'
                     f'<div class="sub">{e(top["owner_name"])}{" · " + e(top["context"]) if top["context"] else ""}</div></a>')
    story = d.content("home.md")
    titles = sorted((c for c in d.career.values() if c["titles"]), key=lambda c: (-c["titles"], c["owner_name"]))
    featured_ids = ["SL-DYNASTY-OWNER_006", "SL-REPEATFINAL-OWNER_009"]
    active = [x for x in d.storylines if x["status"] == "Active"]
    featured = [x for x in d.storylines if x["storyline_id"] in featured_ids]
    featured += [x for x in active if x not in featured][: max(0, 3 - len(featured))]
    stories_html = "".join(story_card(d, root, x, compact=True) for x in featured[:3])
    body = f"""
<section class="hero" aria-labelledby="hero-title">
  <div class="hero-grid">
    <div>
      <div class="kicker">Est. {d.meta['first_season']} · ESPN League</div>
      <h1 id="hero-title">The Official League Archives</h1>
      <p class="lede">{len(d.seasons)} seasons, {len(d.owners)} owners and {games:,} games of D.J.U.A.C. history, {d.meta['first_season']}–{last}. Every result, standing, draft pick and record, rebuilt from ESPN's own data.</p>
    </div>
    <div class="hero-champ">
      <div class="kicker">{last} Champion</div>
      <div class="name"><a href="owners/{owner_slug(d, champ_id)}/index.html">{e(d.name(champ_id))}</a></div>
      <div>{e(latest['champion']['team_name'])}</div>
      <p class="small" style="margin:.5rem 0 0">{record_str(champ_row['wins'], champ_row['losses'], champ_row['ties'])} regular season · {ordinal(champ_row['seed'])} seed. {tg_line}</p>
    </div>
  </div>
</section>
<section class="stack" aria-labelledby="banner-title" style="margin-top:2rem">
  <div><div class="kicker">Banners</div><h2 id="banner-title">Champions, every season</h2></div>
  <nav class="banner" aria-label="Champions by season">{banner}</nav>
</section>
<section style="margin-top:2rem" aria-labelledby="quick-title">
  <div class="kicker">From the record book</div><h2 id="quick-title">Quick records</h2>
  <div class="grid sm-2 lg-3">{''.join(quick)}</div>
  <p class="small" style="margin-top:.75rem"><a href="records/index.html">See the full record book →</a></p>
</section>
<section style="margin-top:2rem" aria-labelledby="stories-title">
  <div class="kicker">Storyline registry</div><h2 id="stories-title">Storylines to know</h2>
  <div class="grid md-3">{stories_html}</div>
  <p class="small" style="margin-top:.75rem"><a href="storylines/index.html">All {len(d.storylines)} storylines →</a></p>
</section>
<section style="margin-top:2rem" class="grid md-3">
  <div style="grid-column: span 2">
    <div class="kicker">League history</div><h2>The story so far</h2>
    {('<div class="prose">' + story + '</div>') if story else placeholder('The league history narrative')}
  </div>
  {card('Title count', '<ol style="margin:0;padding-left:1.25rem">' + ''.join(f'<li>{owner_link(d, root, c["owner_id"])} <span class="muted tabular">· {c["titles"]}</span></li>' for c in titles) + '</ol>', footer='<a href="champions/index.html">All champions →</a>')}
</section>
"""
    site.write("index.html", "Home", body, active="Home")


def page_champions(site: Site):
    d = site.d
    root = "../"
    rows = []
    for s in sorted(d.seasons, key=lambda s: -s["season"]):
        c = s["champion"]
        row = next(r for r in s["standings"] if r["owner_id"] == c["owner_id"])
        tg = title_game(d, s["season"])
        score = ""
        if tg:
            w = tg["home"] if tg["home"]["owner_id"] == c["owner_id"] else tg["away"]
            l = tg["away"] if w is tg["home"] else tg["home"]
            score = f"{fmt_pts(w['score'])}–{fmt_pts(l['score'])}"
        rows.append(f'<tr class="is-champion"><td data-v="{s["season"]}">{season_link(root, s["season"])}</td>'
                    f'<td>{owner_link(d, root, c["owner_id"], c["team_name"])}</td>'
                    f'<td class="num">{record_str(row["wins"], row["losses"], row["ties"])}</td>'
                    f'<td class="num">{row["seed"] or "–"}</td>'
                    f'<td>{owner_link(d, root, s["runner_up"]["owner_id"], s["runner_up"]["team_name"])}</td>'
                    f'<td class="num">{score}</td></tr>')
    trows = []
    for c in sorted((c for c in d.career.values() if c["finals"]), key=lambda c: (-c["titles"], -c["finals"], c["owner_name"])):
        years = " ".join(badge(str(y), "champion") for y in c["title_years"])
        trows.append(f'<tr><th scope="row">{owner_link(d, root, c["owner_id"])}</th><td class="num">{c["titles"]}</td>'
                     f'<td class="num">{c["runner_ups"]}</td><td class="num">{c["finals"]}</td>'
                     f'<td class="num">{fmt_pct(c["title_conversion"]) if c["finals"] else "–"}</td>'
                     f'<td><div class="badges">{years or "<span class=muted>–</span>"}</div></td></tr>')
    body = f"""
<div class="page-head"><div class="kicker">Honor roll</div><h1>Champions</h1>
<p class="lede">Every D.J.U.A.C. champion and runner-up since {d.meta['first_season']}. The title-game score is ESPN's official result.</p></div>
<div class="stack">
{table([("Season", "num"), ("Champion", "text"), ("Reg. season", "num"), ("Seed", "num"), ("Runner-up", "text"), ("Title game", "num")], rows)}
<section><h2>Titles by owner</h2>
<p class="muted small">Owners who reached at least one championship game. Conversion = titles ÷ championship-game appearances.</p>
{table([("Owner", "text"), ("Titles", "num"), ("Runner-up", "num"), ("Finals", "num"), ("Conversion", "num"), ("Title years", "none")], trows)}
</section></div>"""
    site.write("champions/index.html", "Champions", body, active="Champions", crumbs=[("Champions", None)])


def page_seasons_index(site: Site):
    d = site.d
    root = "../"
    cards = []
    for s in sorted(d.seasons, key=lambda s: -s["season"]):
        st = s["settings"]
        ppr = "PPR" if st["points_per_reception"] == 1 else ("Half PPR" if st["points_per_reception"] == 0.5 else "Standard")
        cards.append(f'<a class="card" href="{s["season"]}/index.html"><div class="card-header"><div class="kicker">{st["teams"]} teams · {ppr}</div>'
                     f'<h3 class="card-title" style="font-size:1.5rem">{s["season"]}</h3></div>'
                     f'<div class="card-content"><div class="badges" style="margin-bottom:.5rem">{badge("Champion", "champion")} <strong>{e(d.name(s["champion"]["owner_id"]))}</strong></div>'
                     f'<div class="small muted">Runner-up: {e(d.name(s["runner_up"]["owner_id"]))}</div>'
                     f'<div class="small muted">Top seed: {e(d.name(s["top_seed"]["owner_id"]))}</div></div>'
                     f'<div class="card-footer badges">{quality_badge(s["player_points_quality"])}'
                     f'{badge("Trades", "outline") if s["trades_available"] else badge("No trade data", "unavailable")}</div></a>')
    body = f"""<div class="page-head"><div class="kicker">Archive</div><h1>Seasons</h1>
<p class="lede">{len(d.seasons)} completed seasons. Each page has final standings, the playoff bracket, every weekly result, top performances, the draft board and (from 2018) trades.</p></div>
<div class="grid sm-2 lg-3">{''.join(cards)}</div>"""
    site.write("seasons/index.html", "Seasons", body, active="Seasons", crumbs=[("Seasons", None)])


def page_season(site: Site, s: dict, prev_s, next_s):
    d = site.d
    yr = s["season"]
    root = "../../"
    st = s["settings"]
    games = d.matchups.get(str(yr), [])
    reg = [g for g in games if g["phase"] == "REGULAR_SEASON"]
    post = [g for g in games if g["phase"] != "REGULAR_SEASON"]

    # settings summary
    lineup = ", ".join(f'{x["count"]} {x["slot"]}' for x in st["lineup"] if x["slot"] not in ("Bench", "IR"))
    ppr = {1: "Full PPR", 0.5: "Half PPR", 0: "Non-PPR"}.get(st["points_per_reception"], f'{st["points_per_reception"]} PPR')
    settings = [f'{st["teams"]} teams', f'{st["regular_season_weeks"]}-week regular season', f'{st["playoff_teams"]} playoff teams',
                ppr, f'{st["divisions"]} division{"s" if st["divisions"] != 1 else ""}',
                f'{st["draft_type"].title()} draft', f'FAAB ${st["faab_budget"]}' if st["faab"] else "No FAAB"]
    settings_html = ('<div class="badges">' + "".join(badge(x, "secondary") for x in settings) + "</div>"
                     f'<p class="small muted" style="margin-top:.5rem">Starting lineup: {e(lineup)}. Bench: {st["bench"]}.</p>')

    # standings
    rows = []
    for r in s["standings"]:
        b = []
        if r["champion"]: b.append(badge("Champion", "champion"))
        if r["runner_up"]: b.append(badge("Runner-up", "runnerup"))
        if r["first_round_bye"]: b.append(badge("Bye", "bye", "First-round bye"))
        cls = ' class="is-champion"' if r["champion"] else ""
        rows.append(f'<tr{cls}><td class="num">{r["final_rank"]}</td><td>{owner_link(d, root, r["owner_id"], r["team_name"])}</td>'
                    f'<td class="num" data-v="{r["wins"] + 0.5 * (r["ties"] or 0)}">{record_str(r["wins"], r["losses"], r["ties"])}</td>'
                    f'<td class="num">{fmt_pts(r["points_for"])}</td><td class="num">{fmt_pts(r["points_against"])}</td>'
                    f'<td class="num">{fmt_num(r["scoring_index"], 1)}</td><td class="num">{fmt_pct(r["allplay_pct"])}</td>'
                    f'<td class="num">{fmt_signed(r["luck"])}</td><td class="num">{r["seed"] or "–"}</td>'
                    f'<td><div class="badges">{"".join(b)}</div></td></tr>')
    standings = table([("Final", "num"), ("Owner / team", "text"), ("W–L", "num"), ("PF", "num"), ("PA", "num"),
                       ("Index", "num"), ("All-play", "num"), ("Luck", "num"), ("Seed", "num"), ("", "none")], rows,
                      caption="Final = ESPN final rank. W–L, PF and PA are regular season only. Index = points per game vs league average (100). Luck = wins above all-play expectation.")

    # playoffs
    wb = [g for g in post if g["tier"] == "WINNERS_BRACKET"]
    names = round_names([g["week"] for g in wb])
    by_week = defaultdict(list)
    for g in wb:
        by_week[g["week"]].append(g)
    bracket = "".join(card(f'{names[w]} <span class="muted small">· week {w}</span>', "".join(game_line(d, root, g) for g in by_week[w]), flush=True)
                      for w in sorted(by_week))
    consol = [g for g in post if g["tier"] != "WINNERS_BRACKET"]
    cons_html = ""
    if consol:
        cw = defaultdict(list)
        for g in consol:
            cw[(g["tier"], g["week"])].append(g)
        label = {"WINNERS_CONSOLATION_LADDER": "Consolation", "LOSERS_CONSOLATION_LADDER": "Losers' bracket"}
        cons_html = ('<details style="margin-top:1rem"><summary>Consolation games</summary><div class="weeks" style="margin-top:1rem">'
                     + "".join(card(f'{label.get(t, t.title())} · week {w}', "".join(game_line(d, root, g) for g in gs), flush=True)
                               for (t, w), gs in sorted(cw.items(), key=lambda x: (x[0][1], x[0][0])))
                     + "</div></details>")
    byes = [r for r in s["standings"] if r["first_round_bye"]]
    playoffs = (f'<p class="muted small">Winners bracket only. First-round byes: '
                + (", ".join(e(d.name(r["owner_id"])) for r in byes) or "none") + ".</p>"
                + f'<div class="bracket">{bracket}</div>' + cons_html)

    # weekly results
    rw = defaultdict(list)
    for g in reg:
        rw[g["week"]].append(g)
    weekly = '<div class="weeks">' + "".join(card(f"Week {w}", "".join(game_line(d, root, g) for g in rw[w]), flush=True) for w in sorted(rw)) + "</div>"
    if any(side["adjustment"] for g in games for side in (g["home"], g["away"])):
        weekly = '<p class="muted small">Scores are ESPN official results; "adj." marks a commissioner adjustment.</p>' + weekly

    # top performances
    perf = []
    for g in reg:
        for side, opp in ((g["home"], g["away"]), (g["away"], g["home"])):
            perf.append((side, opp, g))
    def prow(side, opp, g, val):
        res = "W" if g["winner_owner_id"] == side["owner_id"] else ("T" if g["tie"] else "L")
        return (f'<tr><td>{owner_link(d, root, side["owner_id"], side["team_name"])}</td><td class="num">{g["week"]}</td>'
                f'<td class="num">{val}</td><td>{res} vs {e(d.name(opp["owner_id"]))}</td></tr>')
    raw = lambda x: x[0]["raw_points"] if x[0]["raw_points"] is not None else x[0]["score"]
    hi = sorted(perf, key=lambda x: -(raw(x) or 0))[:25]
    lo = sorted(perf, key=lambda x: (raw(x) or 0))[:25]
    margins = sorted(reg, key=lambda g: -(g["margin"] or 0))[:25]
    hdr = [("Owner / team", "none"), ("Week", "none"), ("Points", "none"), ("Result", "none")]
    margin_rows = []
    for g in margins:
        w = g["home"] if g["winner_owner_id"] == g["home"]["owner_id"] else g["away"]
        l = g["away"] if w is g["home"] else g["home"]
        margin_rows.append(f'<tr><td>{owner_link(d, root, w["owner_id"], w["team_name"])}</td><td class="num">{g["week"]}</td>'
                           f'<td class="num">{fmt_pts(g["margin"])}</td><td>{fmt_pts(w["score"])}–{fmt_pts(l["score"])} vs {e(d.name(l["owner_id"]))}</td></tr>')
    top = ('<div class="grid lg-3">'
           + card("Highest scores", expandable(hdr, [prow(*x, fmt_pts(raw(x))) for x in hi]), "Points actually scored, regular season", flush=True)
           + card("Lowest scores", expandable(hdr, [prow(*x, fmt_pts(raw(x))) for x in lo]), "Points actually scored, regular season", flush=True)
           + card("Biggest blowouts", expandable([("Winner", "none"), ("Week", "none"), ("Margin", "none"), ("Score", "none")], margin_rows), "Official margin, regular season", flush=True)
           + "</div>")

    # draft
    picks = d.draft.get(str(yr), [])
    q = s["player_points_quality"]
    drows = []
    for p in picks:
        k = " " + badge("Keeper", "outline") if p["keeper"] else ""
        drows.append(f'<tr><td class="num">{p["round"]}</td><td class="num">{p["overall"]}</td>'
                     f'<td>{owner_link(d, root, p["owner_id"])}</td><td>{e(p["player"])}{k}</td><td>{e(p["position"])}</td>'
                     f'<td class="num">{fmt_pts(p["season_points"])}</td><td class="num">{fmt_signed(p["vor"], 0)}</td>'
                     f'<td class="num">{p["value_rank"] or "–"}</td><td class="num">{fmt_signed(p["pick_surplus"], 0) if p["pick_surplus"] is not None else "–"}</td></tr>')
    draft_note = ("Player points for this season were recomputed by ESPN and don't reconcile with team scores, so values below are indicative only and this draft is excluded from draft records."
                  if q == "ESPN_RESCORED" else "Player points reconcile with team scores for this season.")
    draft = (f'<div class="badges" style="margin-bottom:.5rem">{quality_badge(q)}</div><p class="small muted">{draft_note} '
             'VOR = season points minus replacement level at the position. Surplus = overall pick − value rank (positive = outperformed the slot).</p>'
             + table([("Rd", "num"), ("Pick", "num"), ("Owner", "text"), ("Player", "text"), ("Pos", "text"), ("Pts", "num"),
                      ("VOR", "num"), ("Value rank", "num"), ("Surplus", "num")], drows))

    panels = [("standings", "Standings", standings), ("playoffs", "Playoffs", playoffs), ("results", "Weekly results", weekly),
              ("top", "Top performances", top), ("draft", "Draft board", draft)]
    trades = [t for t in d.trades if t["season"] == yr]
    if s["trades_available"]:
        trows = [f'<tr><td class="num">{t["week"]}</td><td>{owner_link(d, root, t["owner_a_id"])}</td><td>{owner_link(d, root, t["owner_b_id"])}</td>'
                 f'<td class="num">{t["players_moved"]}</td><td>{e(t["detail"])}</td></tr>' for t in sorted(trades, key=lambda t: t["week"])]
        trade_html = ('<p class="small muted">Trades are derived from week-to-week roster movement (a player moving directly between two teams with no waiver or free-agent add). Week = first week the players appear on their new rosters.</p>'
                      + (table([("Week", "num"), ("Team A", "text"), ("Team B", "text"), ("Players", "num"), ("Detail", "none")], trows)
                         if trows else '<p>No trades this season.</p>'))
        panels.append(("trades", f"Trades ({len(trades)})", trade_html))
    else:
        panels.append(("trades", "Trades", '<div class="placeholder">' + badge("Not available", "unavailable") +
                       '<p>ESPN does not serve trade or transaction history for seasons before 2018.</p></div>'))

    story = d.content("seasons", f"{yr}.md")
    champ = s["champion"]
    pager = ('<nav class="pager" aria-label="Season navigation">'
             + (f'<a href="../{prev_s}/index.html">← {prev_s}</a>' if prev_s else "<span></span>")
             + (f'<a href="../{next_s}/index.html">{next_s} →</a>' if next_s else "<span></span>") + "</nav>")
    body = f"""
<div class="page-head"><div class="kicker">Season archive</div><h1>The {yr} Season</h1>
<p class="lede">{badge('Champion', 'champion')} <strong>{owner_link(d, root, champ['owner_id'])}</strong> ({e(champ['team_name'])}) ·
Runner-up {owner_link(d, root, s['runner_up']['owner_id'])} · Most points {owner_link(d, root, s['most_points']['owner_id'])} ({fmt_pts(s['most_points']['points_for'])})</p>
{settings_html}</div>
<section style="margin-bottom:1.5rem" aria-label="Season story">{('<div class="prose">' + story + '</div>') if story else placeholder('The ' + str(yr) + ' season story')}</section>
{tabs('season', panels)}
{pager}"""
    site.write(f"seasons/{yr}/index.html", f"{yr} Season", body, active="Seasons",
               crumbs=[("Seasons", "seasons/index.html"), (str(yr), None)],
               description=f"D.J.U.A.C. {yr}: standings, playoffs, results and draft.")


def owners_sorted(d: Data):
    return sorted(d.owners, key=lambda o: (not o["active"], -(d.career.get(o["owner_id"], {}).get("titles") or 0),
                                           -o["seasons_played"], o["name"]))


def page_owners_index(site: Site):
    d = site.d
    root = "../"
    rows = []
    for o in owners_sorted(d):
        c = d.career.get(o["owner_id"], {})
        rows.append(f'<tr><th scope="row">{owner_link(d, root, o["owner_id"])} {badge("Active", "active") if o["active"] else ""}</th>'
                    f'<td class="num" data-v="{o["first_season"]}">{o["first_season"]}–{o["last_season"]}</td><td class="num">{o["seasons_played"]}</td>'
                    f'<td class="num" data-v="{c.get("wins", 0)}">{record_str(c.get("wins", 0), c.get("losses", 0), c.get("ties", 0))}</td>'
                    f'<td class="num">{fmt_pct(c.get("win_pct"))}</td><td class="num">{c.get("titles", 0)}</td><td class="num">{c.get("finals", 0)}</td>'
                    f'<td class="num">{c.get("byes", 0)}</td><td class="num">{fmt_num(c.get("avg_scoring_index"), 1)}</td>'
                    f'<td class="num">{fmt_num(c.get("avg_finish"), 1)}</td></tr>')
    body = f"""<div class="page-head"><div class="kicker">The membership</div><h1>Owners</h1>
<p class="lede">All {len(d.owners)} owners in league history, tracked by permanent owner ID regardless of team name. Active = played in {d.meta['last_season']}.</p></div>
{table([("Owner", "text"), ("Span", "num"), ("Seasons", "num"), ("Record", "num"), ("Win %", "num"), ("Titles", "num"), ("Finals", "num"),
        ("Byes", "num"), ("Avg index", "num"), ("Avg finish", "num")], rows,
       caption="Record and win % are regular season. Avg index = average scoring index (100 = league average). Byes = first-round playoff byes.")}"""
    site.write("owners/index.html", "Owners", body, active="Owners", crumbs=[("Owners", None)])


def page_owner(site: Site, o: dict):
    d = site.d
    oid = o["owner_id"]
    root = "../../"
    c = d.career.get(oid, {})
    seasons = sorted((t for t in d.team_seasons if t["owner_id"] == oid), key=lambda t: -t["season"])

    stats = "".join([
        stat_card("Regular season", record_str(c.get("wins", 0), c.get("losses", 0), c.get("ties", 0)), f'{fmt_pct(c.get("win_pct"))} win pct'),
        stat_card("Championships", str(c.get("titles", 0)), f'{c.get("finals", 0)} finals · {c.get("runner_ups", 0)} runner-up'),
        stat_card("First-round byes", str(c.get("byes", 0)), f'{c.get("semifinals", 0)} semifinals'),
        stat_card("Playoff record", record_str(c.get("wb_wins", 0), c.get("wb_losses", 0)), f'{c.get("playoff_appearances", 0)} winners-bracket entries'),
        stat_card("Scoring index", fmt_num(c.get("avg_scoring_index"), 1), "100 = league average"),
        stat_card("Luck", fmt_signed(c.get("luck")), "wins vs all-play expectation"),
    ])

    srows = []
    for t in seasons:
        b = []
        if t["champion"]: b.append(badge("Champion", "champion"))
        if t["runner_up"]: b.append(badge("Runner-up", "runnerup"))
        if t["first_round_bye"]: b.append(badge("Bye", "bye"))
        cls = ' class="is-champion"' if t["champion"] else ""
        srows.append(f'<tr{cls}><td class="num" data-v="{t["season"]}">{season_link(root, t["season"])}</td><td>{e(t["team_name"])}</td>'
                     f'<td class="num" data-v="{t["win_pct"]}">{record_str(t["wins"], t["losses"], t["ties"])}</td>'
                     f'<td class="num">{fmt_pts(t["points_for"])}</td><td class="num">{fmt_num(t["scoring_index"], 1)}</td>'
                     f'<td class="num">{fmt_signed(t["luck"])}</td><td class="num">{t["seed"] or "–"}</td>'
                     f'<td class="num" data-v="{t["final_rank"]}">{ordinal(t["final_rank"])} / {t["league_size"]}</td>'
                     f'<td><div class="badges">{"".join(b)}</div></td></tr>')
    seasons_html = table([("Season", "num"), ("Team name", "text"), ("W–L", "num"), ("PF", "num"), ("Index", "num"), ("Luck", "num"),
                          ("Seed", "num"), ("Finish", "num"), ("", "none")], srows)

    hrows = []
    for h in sorted((h for h in d.h2h if h["owner_id"] == oid), key=lambda h: (-h["games"], h["opp_owner_name"])):
        hrows.append(f'<tr><th scope="row">{owner_link(d, root, h["opp_owner_id"])}</th><td class="num">{h["games"]}</td>'
                     f'<td class="num" data-v="{h["reg_w"]}">{record_str(h["reg_w"], h["reg_l"], h["reg_t"])}</td>'
                     f'<td class="num" data-v="{h["playoff_w"]}">{record_str(h["playoff_w"], h["playoff_l"])}</td>'
                     f'<td class="num">{fmt_pct(h["win_pct"])}</td><td class="num">{fmt_pts(h["points_for"])}</td>'
                     f'<td class="num">{fmt_pts(h["points_against"])}</td><td class="num">{e(h["last_meeting"])}</td></tr>')
    h2h_html = table([("Opponent", "text"), ("Games", "num"), ("Regular", "num"), ("Playoffs", "num"), ("Win %", "num"),
                      ("PF", "num"), ("PA", "num"), ("Last met", "text")], hrows,
                     caption="Regular season plus winners-bracket games; consolation games excluded.")

    picks = [dict(p, season=int(yr)) for yr, ps in d.draft.items() for p in ps if p["owner_id"] == oid]
    verified = [p for p in picks if p["quality"] == "VERIFIED" and p["vor_z"] is not None]
    def pick_rows(ps):
        return [f'<tr><td class="num">{season_link(root, p["season"], "#draft")}</td><td class="num">{p["round"]}.{p["round_pick"]:02d}</td>'
                f'<td>{e(p["player"])}</td><td>{e(p["position"])}</td><td class="num">{fmt_pts(p["season_points"])}</td>'
                f'<td class="num">{fmt_signed(p["vor"], 0)}</td></tr>' for p in ps]
    ph = [("Season", "none"), ("Pick", "none"), ("Player", "none"), ("Pos", "none"), ("Pts", "none"), ("VOR", "none")]
    best = sorted(verified, key=lambda p: -p["vor_z"])[:8]
    worst = sorted((p for p in verified if p["round"] <= 4), key=lambda p: p["vor_z"])[:8]
    crows = [f'<tr><td class="num">{season_link(root, c2["season"], "#draft")}</td><td class="num">{c2["class_rank"]} / {c2["teams"]}</td>'
             f'<td class="num">{fmt_num(c2["class_vor"], 0)}</td><td class="num">{fmt_num(c2["class_index"], 2)}</td><td>{e(c2["best_pick"])}</td>'
             f'<td>{quality_badge(c2["quality"])}</td></tr>'
             for c2 in sorted((x for x in d.classes if x["owner_id"] == oid), key=lambda x: -x["season"])]
    draft_html = ('<p class="small muted">Best and worst picks use seasons with verified player scoring only (ESPN-rescored seasons excluded). Worst picks are limited to rounds 1–4.</p>'
                  '<div class="grid lg-3" style="grid-template-columns:repeat(auto-fit,minmax(18rem,1fr))">'
                  + card("Best picks", table(ph, pick_rows(best), sortable=False) if best else '<p class="muted" style="padding:1rem">No verified picks.</p>', "Highest value over replacement", flush=True)
                  + card("Worst early picks", table(ph, pick_rows(worst), sortable=False) if worst else '<p class="muted" style="padding:1rem">No verified picks.</p>', "Lowest value, rounds 1–4", flush=True)
                  + "</div><h3 style=\"margin-top:1.5rem\">Draft classes</h3>"
                  + table([("Season", "num"), ("Class rank", "num"), ("Class VOR", "num"), ("Class index", "num"), ("Best pick", "text"), ("Quality", "none")], crows))

    held = []
    for r in d.records:
        for en in r["entries"]:
            if en["owner_id"] == oid and en["rank"] <= 5:
                held.append((r, en))
    rrows = [f'<tr><td>{e(r["category"])}</td><td><a href="{root}records/index.html#{slug(r["category"] + "-" + r["record"])}">{e(r["record"])}</a></td>'
             f'<td class="num">{badge("Record holder", "champion") if en["rank"] == 1 else ordinal(en["rank"])}</td>'
             f'<td class="num">{fmt_record_value(r["record"], en["value"])}</td><td>{e(en["context"])}</td></tr>'
             for r, en in sorted(held, key=lambda x: (x[1]["rank"], x[0]["category"]))]
    records_html = (table([("Category", "text"), ("Record", "text"), ("Rank", "none"), ("Value", "none"), ("Context", "none")], rrows)
                    if rrows else '<p class="muted">No top-5 record book entries.</p>')

    my_trades = [t for t in d.trades if oid in (t["owner_a_id"], t["owner_b_id"])]
    trows = [f'<tr><td class="num">{season_link(root, t["season"], "#trades")}</td><td class="num">{t["week"]}</td>'
             f'<td>{owner_link(d, root, t["owner_b_id"] if t["owner_a_id"] == oid else t["owner_a_id"])}</td><td>{e(t["detail"])}</td></tr>'
             for t in sorted(my_trades, key=lambda t: (-t["season"], t["week"]))]
    trades_html = ('<p class="small muted">2018 onward; earlier trade history is not available from ESPN.</p>'
                   + (table([("Season", "num"), ("Week", "num"), ("With", "text"), ("Detail", "none")], trows) if trows else "<p>No trades since 2018.</p>"))

    titles = " ".join(badge(f"{y} Champion", "champion") for y in c.get("title_years", []))
    bio = d.content("owners", f"{oid}.md")
    my_stories = [x for x in d.storylines if oid in (x.get("participating_owner_ids") or [])]
    stories_html = ('<div class="grid md-2" style="margin-top:1rem">' + "".join(story_card(d, root, x) for x in my_stories) + "</div>"
                    if my_stories else '<p class="muted" style="margin-top:1rem">No registered storylines yet.</p>')
    body = f"""
<div class="page-head"><div class="kicker">Owner profile · {e(oid)}</div><h1>{e(o['name'])}</h1>
<p class="lede">{o['seasons_played']} season{'s' if o['seasons_played'] != 1 else ''}, {o['first_season']}–{o['last_season']}{' · active' if o['active'] else ''}.</p>
<div class="badges">{titles}</div></div>
<div class="grid sm-2 lg-6" style="margin-bottom:1.5rem">{stats}</div>
<section style="margin-bottom:1.5rem" aria-label="Owner biography">{('<div class="prose">' + bio + '</div>') if bio else placeholder('The ' + o['name'] + ' legacy profile')}</section>
{tabs('owner', [('seasons', 'Seasons', seasons_html), ('h2h', 'Head-to-head', h2h_html), ('draft', 'Draft', draft_html),
                ('records', f'Records ({len(rrows)})', records_html), ('trades', f'Trades ({len(my_trades)})', trades_html),
                ('stories', f'Storylines ({len(my_stories)})', stories_html)])}"""
    site.write(f"owners/{owner_slug(d, oid)}/index.html", o["name"], body, active="Owners",
               crumbs=[("Owners", "owners/index.html"), (o["name"], None)],
               description=f"{o['name']}: D.J.U.A.C. career record, seasons, head-to-head and draft history.")


def fmt_record_value(record: str, value) -> str:
    if value is None:
        return "–"
    if "%" in record and abs(float(value)) <= 1:
        return fmt_pct(value)
    if "drafter" in record.lower():
        return fmt_num(value, 2)
    return fmt_num(value, 2 if abs(float(value)) < 10 else 1)


def page_records(site: Site):
    d = site.d
    root = "../"
    cats = []
    for r in d.records:
        if r["category"] not in cats:
            cats.append(r["category"])
    toc = '<nav class="toc" aria-label="Record categories">' + "".join(
        f'<a class="badge badge-outline" href="#cat-{slug(cat)}">{e(cat)}</a>' for cat in cats) + "</nav>"
    sections = []
    for cat in cats:
        cards = []
        for r in (x for x in d.records if x["category"] == cat):
            rows = [f'<tr><td class="num">{en["rank"]}</td><td>{owner_link(d, root, en["owner_id"]) if en["owner_id"] else e(en["owner_name"])}</td>'
                    f'<td class="num">{fmt_record_value(r["record"], en["value"])}</td><td class="small">{e(en["context"])}</td></tr>'
                    for en in r["entries"]]
            cards.append(f'<div class="record-cat" id="{slug(cat + "-" + r["record"])}">'
                         + card(e(r["record"]), expandable([("#", "none"), ("Owner", "none"), ("Value", "none"), ("Context", "none")], rows),
                                e(r["definition"]) if r["definition"] else "", flush=True) + "</div>")
        sections.append(f'<section class="record-cat" id="cat-{slug(cat)}" style="margin-top:2rem"><h2>{e(cat)}</h2>'
                        f'<div class="grid lg-3" style="grid-template-columns:repeat(auto-fit,minmax(20rem,1fr))">{"".join(cards)}</div></section>')
    body = f"""<div class="page-head"><div class="kicker">Official</div><h1>The Record Book</h1>
<p class="lede">Leaderboards across career, season, week, streak, draft and trade records: the top five shown, up to 25 on a click. Each record shows its definition.
Cross-era scoring records use indexes (score ÷ league average × 100) because 2007's scoring scale was several times larger.</p></div>
<div class="placeholder" role="note" style="margin-bottom:1rem">{badge('How to read', 'secondary')}<p>Results use ESPN official scores; scoring records use points actually scored, so commissioner penalties don't create false record lows.
Draft records use every season except 2018, when ESPN re-scored player points. Trade records cover 2018 onward.</p></div>
{toc}{''.join(sections)}"""
    site.write("records/index.html", "Record Book", body, active="Record Book", crumbs=[("Record Book", None)])


STORY_CATEGORY_LABELS = {
    "championship_drought": "Championship droughts", "dynasty": "Dynasties", "repeat_champion": "Repeat champions",
    "repeat_finalist": "Bridesmaids", "title_game_rematch": "Title-game rematches", "playoff_rivalry": "Playoff rivalries",
    "lopsided_series": "Lopsided series", "top_seed_fate": "Top-seed fate", "underdog_champion": "Underdog champions",
    "playoff_collapse": "Playoff collapses", "redemption": "Redemption arcs", "dominant_season": "Dominant seasons",
    "streak": "Streaks", "trade_partnership": "Trade partnerships", "trade_activity": "Trade activity",
    "draft_loyalty": "Draft loyalty", "membership": "Membership", "franchise_lineage": "Franchise lineage",
    "first_titles": "First titles", "schedule_luck": "Schedule luck", "regular_season_byes": "Regular-season byes",
}
STATUS_KIND = {"Active": "primary", "Developing": "accent", "Dormant": "secondary", "Resolved": "outline", "Historical": "outline"}


def story_card(d: Data, root: str, st: dict, compact=False) -> str:
    owners = ", ".join(owner_link(d, root, oid) for oid in st.get("participating_owner_ids") or [])
    seasons = st.get("relevant_seasons") or []
    span = (f"{min(seasons)}–{max(seasons)}" if len(seasons) > 1 else str(seasons[0])) if seasons else ""
    head = (f'<div class="badges">{badge(st["status"], STATUS_KIND.get(st["status"], "outline"))}'
            f'{badge(STORY_CATEGORY_LABELS.get(st["category"], st["category"].replace("_", " ").title()), "outline")}'
            f'{badge(span, "secondary") if span else ""}</div>')
    body = f'{head}<p style="margin:.5rem 0">{e(st["description"])}</p>'
    if owners:
        body += f'<p class="small muted" style="margin:.25rem 0">Owners: {owners}</p>'
    if not compact:
        events = [ev for ev in st.get("supporting_events") or [] if ev.get("description")][:6]
        if events:
            body += '<ul class="small" style="margin:.5rem 0 0;padding-left:1.1rem">' + "".join(
                f'<li><a href="{root}seasons/{ev["season"]}/index.html">{ev["season"]}</a>{" wk " + str(ev["week"]) if ev.get("week") else ""}: {e(ev["description"])}</li>'
                for ev in events) + "</ul>"
        if st.get("potential_future_developments"):
            body += f'<p class="small muted" style="margin:.5rem 0 0"><strong>What to watch:</strong> {e(st["potential_future_developments"])}</p>'
    return f'<div id="{slug(st["storyline_id"])}">' + card(e(st["title"]), body) + "</div>"


def page_storylines(site: Site):
    d = site.d
    root = "../"
    order = ["Active", "Developing", "Dormant", "Resolved", "Historical"]
    cats = []
    for st in d.storylines:
        if st["category"] not in cats:
            cats.append(st["category"])
    counts = {k: sum(1 for x in d.storylines if x["status"] == k) for k in order}
    filters = ('<nav class="toc" aria-label="Filter storylines by status">'
               + '<button type="button" class="badge badge-primary" data-story-filter="all">All ' + str(len(d.storylines)) + '</button>'
               + "".join(f'<button type="button" class="badge badge-outline" data-story-filter="{k}">{k} {n}</button>' for k, n in counts.items() if n)
               + "</nav>")
    sections = []
    for cat in cats:
        items = sorted((x for x in d.storylines if x["category"] == cat), key=lambda x: (order.index(x["status"]) if x["status"] in order else 9, x["title"]))
        cards = "".join(f'<div data-story-status="{e(x["status"])}">{story_card(d, root, x)}</div>' for x in items)
        sections.append(f'<section data-story-section style="margin-top:2rem" id="cat-{slug(cat)}"><h2>{e(STORY_CATEGORY_LABELS.get(cat, cat.replace("_", " ").title()))}</h2>'
                        f'<div class="grid md-2">{cards}</div></section>')
    script = """<script>
document.querySelectorAll('[data-story-filter]').forEach(function(b){b.addEventListener('click',function(){
 var f=b.getAttribute('data-story-filter');
 document.querySelectorAll('[data-story-filter]').forEach(function(x){x.className='badge '+(x===b?'badge-primary':'badge-outline');x.setAttribute('aria-pressed',x===b);});
 document.querySelectorAll('[data-story-status]').forEach(function(c){c.hidden=!(f==='all'||c.getAttribute('data-story-status')===f);});
 document.querySelectorAll('[data-story-section]').forEach(function(s){s.hidden=!s.querySelector('[data-story-status]:not([hidden])');});
});});
</script>"""
    body = f"""<div class="page-head"><div class="kicker">Registry</div><h1>Storylines</h1>
<p class="lede">{len(d.storylines)} storylines found in {d.meta['first_season']}–{d.meta['last_season']}: droughts, dynasties, rivalries, collapses and comebacks.
Each is built from the data and lists its supporting games. Status is as of the end of {d.meta['last_season']}.</p></div>
<div class="placeholder" role="note" style="margin-bottom:1rem">{badge('How to read', 'secondary')}<p><strong>Active</strong> storylines involve current owners and are still open.
<strong>Developing</strong> ones involve newer owners. <strong>Dormant</strong>, <strong>Resolved</strong> and <strong>Historical</strong> are closed or paused. Written features come after the next season.</p></div>
{filters}{''.join(sections)}{script}"""
    site.write("storylines/index.html", "Storylines", body, active="Storylines", crumbs=[("Storylines", None)],
               description="D.J.U.A.C. storyline registry: droughts, dynasties, rivalries, collapses and comebacks.")


def page_h2h(site: Site):
    d = site.d
    root = "../"
    owners = sorted(d.owners, key=lambda o: (-o["seasons_played"], o["name"]))
    core = {o["owner_id"] for o in owners if o["seasons_played"] >= 4}
    cell = {(h["owner_id"], h["opp_owner_id"]): h for h in d.h2h}
    def occ(oid):
        return "" if oid in core else " occasional"
    head = "".join(f'<th scope="col" class="{occ(o["owner_id"]).strip()}"><a href="{root}owners/{owner_slug(d, o["owner_id"])}/index.html">{e(o["name"])}</a></th>' for o in owners)
    rows = []
    for a in owners:
        tds = []
        for b in owners:
            cls = occ(b["owner_id"]).strip()
            if a["owner_id"] == b["owner_id"]:
                tds.append(f'<td class="self {cls}" aria-label="Same owner">—</td>'); continue
            h = cell.get((a["owner_id"], b["owner_id"]))
            if not h:
                tds.append(f'<td class="{cls}"><span class="muted">·</span></td>'); continue
            w, l, t = h["reg_w"] + h["playoff_w"], h["reg_l"] + h["playoff_l"], h["reg_t"]
            pct = (w + 0.5 * t) / max(w + l + t, 1)
            tone = "pos" if pct > 0.5 else ("neg" if pct < 0.5 else "")
            weight = min(abs(pct - 0.5) * 1.1, 0.45) + 0.06
            style = f' style="--w:{weight:.2f}"' if tone else ""
            tds.append(f'<td class="{tone} {cls}"{style} title="{e(a["name"])} vs {e(b["name"])}: {w}–{l}{"–" + str(t) if t else ""} ({h["games"]} games)">{record_str(w, l, t)}</td>')
        rows.append(f'<tr class="{occ(a["owner_id"]).strip()}"><th scope="row" class="sticky-col">{owner_link(d, root, a["owner_id"])}</th>{"".join(tds)}</tr>')
    body = f"""<div class="page-head"><div class="kicker">Rivalries</div><h1>Head-to-Head Matrix</h1>
<p class="lede">Each cell is the row owner's record against the column owner: regular season plus winners-bracket games (consolation excluded).
Green = winning record, red = losing record; darker = more lopsided.</p></div>
<p><label class="switch"><input type="checkbox" id="core-toggle"> Show owners with fewer than 4 seasons</label></p>
<div class="table-wrap" style="max-height:80vh"><table class="matrix core-only"><thead><tr><th scope="col" class="sticky-col">Owner</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p class="small muted" style="margin-top:.75rem">Full head-to-head detail (points for and against, last meeting) is on each owner's page.</p>"""
    site.write("head-to-head/index.html", "Head-to-Head", body, active="Head-to-Head", crumbs=[("Head-to-Head", None)])


def page_search(site: Site):
    body = """<div class="page-head search-page"><div class="kicker">Find anything</div><h1>Search</h1>
<p class="lede">Owners, season team names, seasons and every drafted player. Tip: press <kbd>Ctrl</kbd> <kbd>K</kbd> (or <kbd>⌘</kbd> <kbd>K</kbd>) on any page.</p>
<label class="sr-only" for="search-page-input">Search the archives</label>
<input class="input" id="search-page-input" type="search" role="combobox" aria-expanded="true" aria-controls="search-page-list" aria-autocomplete="list" placeholder="Try “Josh Book”, “Moosey”, “2016” or “McCaffrey”" autocomplete="off">
<ul class="cmdk-list" id="search-page-list" role="listbox" aria-label="Results"></ul>
<noscript><p>Search needs JavaScript. Browse <a href="../owners/index.html">owners</a> or <a href="../seasons/index.html">seasons</a> instead.</p></noscript></div>"""
    site.write("search/index.html", "Search", body, crumbs=[("Search", None)])


def page_about(site: Site):
    d = site.d
    rows = [f'<tr><td class="num">{season_link("../", c["season"])}</td><td class="num">{c["teams"]}</td>'
            f'<td class="num">{c["regular_season_games"]}</td><td class="num">{c["postseason_games"]}</td><td class="num">{c["draft_picks"]}</td>'
            f'<td>{quality_badge(c["player_points"])}</td>'
            f'<td>{badge(str(c["trade_count"]) + " trades", "verified") if c["trades"] == "Available" else badge("Not available", "unavailable")}</td></tr>'
            for c in d.coverage]
    notes = "".join(f"<li>{e(n)}</li>" for n in d.meta["notes"])
    last = d.meta["last_season"]
    body = f"""<div class="page-head"><div class="kicker">Methodology</div><h1>About the Archives</h1>
<p class="lede">How this record was built, what it covers, and where the source data has gaps.</p></div>
<div class="stack prose" style="max-width:52rem">
<section><h2>Source</h2>
<p>Everything here comes from ESPN's own league history for the D.J.U.A.C. (ESPN Fantasy Football), {d.meta['first_season']}–{last}.
The data was extracted programmatically, stored unchanged, then normalized and cross-checked: computed regular-season records match ESPN's season records for all 195 team-seasons,
every championship-game winner matches ESPN's final rank 1, and every season's draft has teams × rounds picks.</p>
<p>Owners are tracked by a permanent owner ID tied to the displayed owner name, never by team name, so a single owner's history stays together through every rename.
The {d.meta['last_season'] + 1} season is in progress and will be added once it's final.</p></section>
<section><h2>Method notes</h2><ul>{notes}</ul></section>
<section><h2>Definitions</h2><ul>
<li><strong>Regular-season stats</strong> exclude every postseason game.</li>
<li><strong>Playoff appearance</strong> means any winners-bracket entry. Nearly every team has qualified since 2012, so this is mostly ceremonial. <strong>First-round byes</strong> (a top seed that skipped the first winners-bracket round) are the meaningful measure.</li>
<li><strong>Playoff record</strong> counts winners-bracket games only. Consolation games are excluded.</li>
<li><strong>Scoring index</strong> = points per game ÷ that season's league points per game × 100 (100 = average). The <strong>weekly index</strong> compares a score to that week's league mean. Indexes make eras comparable.</li>
<li><strong>All-play record</strong>: each week a team "plays" every other team; wins = teams it outscored.</li>
<li><strong>Luck</strong> = actual regular-season wins − expected wins from the all-play win rate.</li>
<li><strong>Draft value (VOR)</strong> = a player's league-scored season total minus replacement level at his position. Replacement level is the (teams × starting slots + 1)th best player at the position that season, drafted or not. Flex slots are split RB 45% / WR 45% / TE 10%.</li>
<li><strong>Class index</strong> = an owner's total draft-class value in standard deviations against that season's other classes.</li>
</ul></section>
<section><h2>Known limitations</h2><ul>
<li><strong>Trades and transactions before 2018 are not available.</strong> ESPN no longer serves them for those seasons. 2018 onward, trades are derived from week-to-week roster movement, because ESPN's own trade records are incomplete.</li>
<li><strong>Weekly rosters before 2018 are partial.</strong> ESPN returns only season-end rosters for 2007–2017.</li>
<li><strong>Player points for 2018 were recomputed by ESPN.</strong> They don't reconcile with team scores, so 2018 draft values are flagged <em>ESPN rescored</em> and left out of draft records. Before 2017, ESPN's weekly lineups omit some starters, but the player points present are genuine. Team scores are authoritative everywhere.</li>
<li><strong>2007 used a much larger scoring scale</strong> (around 667 points per team-game, with punters and head coaches in the lineup). Use indexes, not raw points, to compare across eras.</li>
<li><strong>2008 had 11 teams</strong>, so some weeks included byes.</li>
<li><strong>2020 data notes:</strong> one team-week (Jesse Christman, week 6) has no starters in ESPN's data and scored 0. Weeks 11–12 include four −60 commissioner penalties. One changed a result: in week 11 Josh Book outscored Nate Hemby 143.5–109.5, and the penalty made it an 83.5–109.5 loss. The other three were losses either way.</li>
</ul></section>
<section><h2>Coverage by season</h2></section></div>
{table([("Season", "num"), ("Teams", "num"), ("Reg. games", "num"), ("Postseason", "num"), ("Draft picks", "num"), ("Player points", "none"), ("Trades", "none")], rows)}
<div class="stack prose" style="max-width:52rem;margin-top:1.5rem">
<section><h2>What's public</h2>
<p>This site publishes league facts only: results, standings, drafts, trades, records and owners' displayed names. It contains no ESPN account identifiers, no raw ESPN data, and no predictions or strategic analysis.</p></section>
</div>"""
    site.write("about/index.html", "About & Methodology", body, active="About", crumbs=[("About", None)])


def page_404(site: Site):
    body = """<div class="page-head"><div class="kicker">404</div><h1>Page not found</h1>
<p class="lede">That page isn't in the archives. Try <a href="index.html">the home page</a> or <a href="search/index.html">search</a>.</p></div>"""
    site.write("404.html", "Not found", body)


# ---------------------------------------------------------------------------- search index & assets

def search_index(d: Data) -> list[dict]:
    idx = []
    for o in d.owners:
        c = d.career.get(o["owner_id"], {})
        idx.append({"t": "owner", "l": o["name"], "s": f'{o["first_season"]}–{o["last_season"]} · {c.get("titles", 0)} titles',
                    "u": f'owners/{owner_slug(d, o["owner_id"])}/index.html', "w": 4})
    for s in sorted(d.seasons, key=lambda s: -s["season"]):
        idx.append({"t": "season", "l": f'{s["season"]} season', "s": f'Champion: {d.name(s["champion"]["owner_id"])}',
                    "u": f'seasons/{s["season"]}/index.html', "k": str(s["season"]), "w": 3})
    seen = set()
    for s in d.seasons:
        for r in s["standings"]:
            key = (r["team_name"].lower(), r["owner_id"])
            years = [x["season"] for x in d.seasons for y in x["standings"] if y["owner_id"] == r["owner_id"] and y["team_name"].lower() == key[0]]
            if key in seen:
                continue
            seen.add(key)
            span = f"{min(years)}" if len(years) == 1 else f"{min(years)}–{max(years)}"
            idx.append({"t": "team", "l": r["team_name"], "s": f'{d.name(r["owner_id"])} · {span}',
                        "u": f'owners/{owner_slug(d, r["owner_id"])}/index.html', "w": 2})
    players = {}
    for yr, picks in d.draft.items():
        for p in picks:
            pid = p["player_id"] if p["player_id"] is not None else p["player"]
            ent = players.setdefault(pid, {"name": p["player"], "pos": p["position"], "picks": []})
            ent["picks"].append((int(yr), p["round"], p["owner_id"]))
    for ent in players.values():
        ent["picks"].sort(reverse=True)
        yr, rnd, oid = ent["picks"][0]
        more = f' · drafted {len(ent["picks"])}×' if len(ent["picks"]) > 1 else ""
        idx.append({"t": "player", "l": ent["name"], "s": f'{ent["pos"]} · {yr} Rd {rnd} by {d.name(oid)}{more}',
                    "u": f"seasons/{yr}/index.html#draft", "k": " ".join(d.name(x[2]) for x in ent["picks"])})
    for label, href in NAV[1:] + [("Search", "search/index.html")]:
        idx.append({"t": "page", "l": label, "u": href, "w": 1})
    return idx


FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#16285f"/><path d="M10 7h12v6a6 6 0 0 1-12 0V7z" fill="#f9b916"/><path d="M13 22h6v3h-6z" fill="#f9b916"/><path d="M16 19v3" stroke="#f9b916" stroke-width="2"/></svg>"""


def build(data_dir: Path, content_dir: Path, out: Path) -> Site:
    d = Data(data_dir, content_dir)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    (out / "assets" / "style.css").write_text(tokens.css() + "\n" + (HERE / "assets" / "style.css").read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copy(HERE / "assets" / "app.js", out / "assets" / "app.js")
    (out / "assets" / "favicon.svg").write_text(FAVICON, encoding="utf-8")
    (out / "assets" / "design-tokens.json").write_text(json.dumps(tokens.as_json(), indent=2) + "\n", encoding="utf-8")
    (out / "assets" / "search-index.js").write_text(
        "window.DJUAC_SEARCH=" + json.dumps(search_index(d), ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    site = Site(d, out)
    page_home(site)
    page_champions(site)
    page_seasons_index(site)
    ordered = sorted(d.season)
    for i, yr in enumerate(ordered):
        page_season(site, d.season[yr], ordered[i - 1] if i else None, ordered[i + 1] if i + 1 < len(ordered) else None)
    page_owners_index(site)
    for o in d.owners:
        page_owner(site, o)
    page_records(site)
    page_h2h(site)
    page_storylines(site)
    page_search(site)
    page_about(site)
    page_404(site)
    return site


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, default=REPO / "data")
    ap.add_argument("--content", type=Path, default=REPO / "content")
    ap.add_argument("--out", type=Path, default=REPO / "_site")
    args = ap.parse_args(argv)
    site = build(args.data, args.content, args.out)
    print(f"built {len(site.pages)} pages into {args.out}"
          + (f" ({site.d.redacted} team-name redactions applied)" if site.d.redacted else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
