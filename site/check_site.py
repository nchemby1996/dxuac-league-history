#!/usr/bin/env python3
"""Verify a built _site/: every internal link and anchor resolves, and nothing private leaks.

    python site/check_site.py [_site]

Checks: href/src targets exist (fragments must match an id), no GUID-like strings anywhere,
no private file paths. (The in-progress season may appear on the site since 2026-11-18, by commissioner
decision: weekly newsletter issues and the running season story are published.)
Exit code 1 on any failure."""

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
PRIVATE = re.compile(r"(/home/|/root/|raw/espn|identity/|manifests/|espn_s2|SWID|intelligence)", re.I)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.ids = [], set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        for k in ("href", "src"):
            if a.get(k):
                self.links.append(a[k])


# Deliberate outbound links (commissioner-approved). Everything else external fails the check.
ALLOWED_EXTERNAL = {"https://fantasy.espn.com/football/league?leagueId=46009"}

def main(site: Path) -> int:
    errors = []
    pages = {}
    for path in site.rglob("*.html"):
        p = Links()
        p.feed(path.read_text(encoding="utf-8"))
        pages[path.resolve()] = p
    checked = 0
    for path, p in pages.items():
        for link in p.links:
            parts = urlsplit(link)
            if link in ALLOWED_EXTERNAL:
                continue
            if parts.scheme in ("http", "https", "mailto") or link.startswith("//"):
                errors.append(f"{path.relative_to(site.resolve())}: external link {link}")
                continue
            target = path if not parts.path else (path.parent / unquote(parts.path)).resolve()
            if target.is_dir():
                target = target / "index.html"
            checked += 1
            if not target.exists():
                errors.append(f"{path.relative_to(site.resolve())}: broken link {link}")
            elif parts.fragment and target.suffix == ".html":
                tp = pages.get(target)
                if tp is not None and parts.fragment not in tp.ids:
                    errors.append(f"{path.relative_to(site.resolve())}: missing anchor {link}")
    for path in site.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(site)
        if GUID.search(text):
            errors.append(f"{rel}: GUID-like string")
        if PRIVATE.search(text):
            errors.append(f"{rel}: private path/identifier: {PRIVATE.search(text).group(0)}")
    for err in errors:
        print("FAIL", err)
    print(f"{len(pages)} pages, {checked} internal links checked, {len(errors)} problems")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "_site")))
