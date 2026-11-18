"""Render the social share card (site/assets/og.png, 1200x630). Optional: needs Playwright + Chromium.

    python site/make_og.py --letter J --chrome /usr/bin/google-chrome
Re-run when the letter changes (each new champion), then rebuild the site."""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent

HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family: Anton; src: url("{fonts}/anton-latin-400-normal.woff2"); }}
@font-face {{ font-family: Archivo; src: url("{fonts}/archivo-latin-800-normal.woff2"); font-weight: 800; }}
body {{ margin: 0; }}
.card {{ width: 1200px; height: 630px; box-sizing: border-box; background: #FFE14D; border: 14px solid #0B0B0B; position: relative; overflow: hidden;
  font-family: Archivo, sans-serif; padding: 64px 72px; display: flex; flex-direction: column; justify-content: center; gap: 18px; }}
.mark {{ font-family: Anton, sans-serif; font-size: 190px; line-height: .9; color: #0B0B0B; }}
.mark span {{ display: inline-block; line-height: .9; background: #D7261E; color: #fff; padding: 10px 18px 0; }}
.sub {{ font-weight: 800; font-size: 30px; position: relative; z-index: 1; letter-spacing: .08em; color: #0B0B0B; }}
.tag {{ font-family: Anton, sans-serif; font-size: 46px; color: #0B0B0B; background: #fff; display: inline-block; padding: 6px 18px; border: 5px solid #0B0B0B; align-self: flex-start; }}
.t {{ position: absolute; right: -120px; bottom: -150px; width: 440px; height: 440px; }}
</style></head><body><div class="card">
<svg class="t" viewBox="0 0 64 64"><circle cx="32" cy="32" r="29" fill="none" stroke="#0B0B0B" stroke-width="2.4"/><circle cx="32" cy="32" r="21" fill="none" stroke="#D7261E" stroke-width="2.4"/><path d="M32 1v12M32 51v12M1 32h12M51 32h12" stroke="#0B0B0B" stroke-width="2.4"/></svg>
<div class="mark">D.<span>{letter}</span>.U.A.C.</div>
<div class="sub">DEFEAT {letter} UNDER ALL CIRCUMSTANCES · EST. 2007</div>
<div class="tag">THE OFFICIAL LEAGUE ARCHIVES</div>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--letter", required=True)
    ap.add_argument("--chrome", default=None)
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    page_file = HERE / "_og.html"
    page_file.write_text(HTML.format(letter=a.letter, fonts=(HERE / "assets" / "fonts").as_uri()), encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch(**({"executable_path": a.chrome} if a.chrome else {}))
        pg = b.new_page(viewport={"width": 1200, "height": 630})
        pg.goto(page_file.as_uri()); pg.wait_for_timeout(300)
        pg.screenshot(path=str(HERE / "assets" / "og.png"))
        b.close()
    page_file.unlink()
    print("wrote", HERE / "assets" / "og.png")


if __name__ == "__main__":
    main()
