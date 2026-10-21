"""Publish reports as a private-link website, so the team opens one link instead of downloading files.

usage: hoop-tape-miner publish workspace/teams/<opponent>/<date> [workspace/teams/<opponent>/<date>/player-<N> ...]
       hoop-tape-miner publish ... --deploy --project <cloudflare-worker-name>
       hoop-tape-miner publish --deploy            (re-upload the site as it is)

Each report folder gets a random, stable path: re-publishing after an edit overwrites the same page, so the
link sent once keeps showing the latest version. Pages are the --share text (no local paths or repo links)
with audio and clips kept as files next to them, which in-app browsers play better than embedded data.
Team reports (not player-<N> folders) are also listed on a hub page with its own random path, season pages
(`hoop-tape-miner season`, a folder with season.json) pinned at the top; personal reports are only reachable
through their own link.

Everything is built in <workspace>/site/ (paths -> tokens in <workspace>/publish.json, both gitignored) and
uploaded with `npx wrangler deploy` as Cloudflare Workers static assets (the successor of Pages; free plan,
run `npx wrangler login` once) behind publish_worker.js, which answers the Range requests Safari needs to play
clips. The site lands on https://<project>.<your-subdomain>.workers.dev.
The site is unlisted, not access-controlled: anyone holding a link can open it. See docs/privacy.md.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import media, render_html
from . import workspace as ws

MAX_FILE = 25 * 1024 * 1024  # Cloudflare static assets per-file limit (25 MiB)
HEADERS = """/*
  X-Robots-Tag: noindex, nofollow
  Referrer-Policy: no-referrer
  X-Content-Type-Options: nosniff
"""  # publish_worker.js sets these (and a Content-Security-Policy) on every response, its own 206 answers too
ROBOTS = "User-agent: *\nDisallow: /\n"
BLANK = '<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex"><title>.</title>\n'
LOCAL_SRC = re.compile(r'(src|poster)="((?!https?:|data:|#)[^"]+)"')
ASSET_EXT = {".mp3", ".mp4", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".vtt"}
SCRIPT = re.compile(r"<script>(.*?)</script>", re.S)


def token() -> str:
    return secrets.token_hex(8)  # 64 bits: not guessable, short enough for a chat message


def load_registry(path: Path) -> dict:
    """publish.json, or its .bak when the file is broken. Exits rather than start over: a fresh registry would
    mint new tokens, and every link already sent would stop working."""
    reg = {}
    for p in (path, path.with_name(path.name + ".bak")):
        if not p.exists():
            continue
        try:
            reg = json.loads(p.read_text(encoding="utf8"))
            break
        except ValueError:
            print(f"warning: {p} is not valid JSON", file=sys.stderr)
    else:
        if path.exists():
            sys.exit(f"{path} is broken and has no readable .bak: restore it, or delete it to start new links")
    reg.setdefault("reports", {})
    return reg


def save_registry(path: Path, reg: dict) -> None:
    """Write publish.json atomically (temp file + replace), keeping the previous good version as publish.json.bak."""
    if path.exists():
        try:
            json.loads(path.read_text(encoding="utf8"))
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        except ValueError:
            pass  # never back up a broken file over a good .bak
    media.write_text_atomic(path, json.dumps(reg, indent=2) + "\n")


def is_published(reg: dict, key: str, page: Path) -> bool:
    """A successful deploy uploaded a build of this report made after `page` (its local index.html) was written."""
    built = (reg.get("deployed") or {}).get(key)
    return bool(built) and key in reg["reports"] and (not page.exists() or page.stat().st_mtime <= built + 2.0)


def report_key(folder: Path, root: Path) -> str:
    try:
        return folder.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        sys.exit(f"{folder} is not inside the workspace {root} (set HOOP_WORKSPACE)")


def pin_scripts(page: str) -> str:
    """Add a CSP meta tag that lets only the page's own inline script(s) run, by hash, so a script that slips
    into the page some other way does not."""
    hashes = " ".join("'sha256-" + base64.b64encode(hashlib.sha256(s.encode("utf8")).digest()).decode() + "'"
                      for s in SCRIPT.findall(page)) or "'none'"
    meta = (f'<meta http-equiv="Content-Security-Policy" content="script-src {hashes}; '
            "object-src 'none'; base-uri 'none'\">")
    return page.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n' + meta, 1)


def build_report(folder: Path, dest: Path) -> list[str]:
    """Render the web page into dest (emptied first) and copy the audio/clip files it links to. Only media files
    inside the report folder are copied; any other reference is dropped from the page with a warning.
    Returns warnings (missing, outside or oversized files)."""
    page = render_html.page(folder, share=True, embed=False)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    warnings, copy = [], {}
    root = folder.resolve()

    def keep(m):
        attr, rel = m.groups()
        src = render_html.inside(folder, rel)
        if src is None or src.suffix.lower() not in ASSET_EXT:
            warnings.append(f"{folder.name}: {rel} is outside the report folder or not a media file; left out")
            return f'data-{attr}-removed=""'
        if src.is_file():
            copy[src.relative_to(root).as_posix()] = src
        else:
            warnings.append(f"{folder.name}: {rel} is linked but missing")
        return m.group(0)
    page = pin_scripts(LOCAL_SRC.sub(keep, page))
    (dest / "index.html").write_text(page, encoding="utf8")
    for rel, src in sorted(copy.items()):
        if src.stat().st_size > MAX_FILE:
            warnings.append(f"{folder.name}: {rel} is over 25 MiB, Cloudflare will reject it")
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / rel)
    return sorted(set(warnings))


def has_report(folder: Path) -> bool:
    return any((folder / locale_entry[3]).exists() for locale_entry in render_html.LANGS)


def title_of(folder: Path) -> str:
    m = re.match(r"# (.*)", render_html.first_readme(folder).read_text(encoding="utf8"))
    return m.group(1).strip() if m else folder.name


def hub_page(entries: list[tuple[str, str, str]], seasons: list[tuple[str, str, str]] = ()) -> str:
    """entries: (date, title, token) of team reports, newest first; seasons: (season id, title, token) of season
    pages, listed first."""
    items = "".join(f'<li class="season"><a href="../{t}/"><small>赛季 · Season {html.escape(d)}</small>'
                    f'{html.escape(title)}</a></li>' for d, title, t in seasons)
    items += "".join(f'<li><a href="../{t}/"><small>{html.escape(d)}</small>{html.escape(title)}</a></li>'
                     for d, title, t in entries)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>比赛复盘 · Game reports</title>
<style>
body {{ margin: 0; font: 16px/1.5 system-ui, "PingFang SC", "Noto Sans SC", sans-serif; background: #f5f5f8; color: #221f45; }}
main {{ max-width: 640px; margin: 0 auto; padding: 28px 18px; }}
h1 {{ font-size: 22px; margin: 0 0 16px; }}
ul {{ list-style: none; margin: 0; padding: 0; }}
li a {{ display: block; padding: 14px 16px; margin-bottom: 10px; background: #fff; border: 1px solid #dcdce6;
        border-radius: 10px; color: inherit; text-decoration: none; }}
li a:hover {{ border-color: #5b4bd1; }}
li.season a {{ border-color: #5b4bd1; border-width: 2px; }}
small {{ display: block; color: #6c6b84; }}
</style>
</head>
<body><main><h1>比赛复盘 · Game reports</h1><ul>{items}</ul></main></body>
</html>
"""


def write_site(site: Path, reg: dict, root: Path) -> None:
    site.mkdir(parents=True, exist_ok=True)
    (site / "_headers").write_text(HEADERS, encoding="utf8")
    (site / "robots.txt").write_text(ROBOTS, encoding="utf8")
    (site / "index.html").write_text(BLANK, encoding="utf8")
    team, seasons = [], []
    for key, t in reg["reports"].items():
        folder = root / key
        # player pages and personal (training, movement) sessions get their own link but are never on the team hub
        if (re.fullmatch(r"player-\w+", folder.name) or not has_report(folder)
                or (folder / "session.json").exists() or (folder / "movement.json").exists()):
            continue
        # season pages (`hoop-tape-miner season`) are pinned above the games
        (seasons if (folder / "season.json").exists() else team).append((folder.name, title_of(folder), t))
    if team or seasons:
        reg.setdefault("hub", token())
        hub = site / reg["hub"]
        hub.mkdir(exist_ok=True)
        (hub / "index.html").write_text(hub_page(sorted(team, reverse=True), sorted(seasons, reverse=True)),
                                        encoding="utf8")


def npx() -> str:
    exe = shutil.which("npx")
    if not exe:
        sys.exit("npx not found: install Node.js (https://nodejs.org) to deploy with wrangler")
    return exe


def worker_config(site: Path, project: str, out: Path) -> Path:
    """wrangler.json + worker script in out/: the site as static assets, publish_worker.js in front of them."""
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(__file__).with_name("publish_worker.js"), out / "worker.js")
    cfg = {"name": project, "main": "worker.js", "compatibility_date": "2026-10-01",
           "assets": {"directory": str(site.resolve()), "binding": "ASSETS", "run_worker_first": True}}
    path = out / "wrangler.json"
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf8")
    return path


def deploy(site: Path, project: str, workdir: Path) -> str | None:
    """Upload the site with its Worker; returns the workers.dev URL when wrangler prints one."""
    cfg = worker_config(site, project, workdir)
    r = subprocess.run([npx(), "--yes", "wrangler@4", "deploy", "--config", str(cfg)], cwd=workdir,
                       capture_output=True, text=True, encoding="utf8", errors="replace")
    enc = sys.stdout.encoding or "utf8"  # wrangler prints emoji; a cp1252 console or log file can't take them
    print((r.stdout[-2000:] + "\n" + r.stderr[-2000:]).encode(enc, "replace").decode(enc))
    if r.returncode:
        sys.exit("wrangler deploy failed (not logged in? run `npx wrangler login`)")
    m = re.search(r"https://[\w.-]+\.workers\.dev", r.stdout)
    return m.group(0) if m else None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner publish", description=__doc__.split("\n\n")[0])
    ap.add_argument("folders", nargs="*", help="report folders (README.md + README.en.md) inside the workspace")
    ap.add_argument("--deploy", action="store_true", help="upload the site to Cloudflare (Workers static assets) with wrangler")
    ap.add_argument("--project", help="Cloudflare Worker name, part of the URL (remembered after the first use)")
    ap.add_argument("--base-url", help="site URL, e.g. a custom domain (remembered; else the workers.dev URL)")
    ap.add_argument("--new-link", action="store_true", help="give these folders a fresh path; old links stop working")
    a = ap.parse_args(argv)
    if not a.folders and not a.deploy:
        ap.error("give report folders and/or --deploy")

    root = ws.root()
    site, reg_path = root / "site", root / "publish.json"
    reg = load_registry(reg_path)
    for opt in ("project", "base_url"):
        if getattr(a, opt):
            reg[opt] = getattr(a, opt).rstrip("/")
    warnings = []
    for f in a.folders:
        folder = Path(f)
        if not has_report(folder):
            sys.exit(f"{folder} has no README.md / README.en.md")
        key = report_key(folder, root)
        old = reg["reports"].get(key)
        if a.new_link or not old:
            if old and (site / old).exists():
                shutil.rmtree(site / old)
            reg["reports"][key] = token()
        warnings += build_report(folder, site / reg["reports"][key])
        reg.setdefault("built", {})[key] = time.time()
    write_site(site, reg, root)
    save_registry(reg_path, reg)  # tokens are kept even if the deploy below fails, so the links stay the same
    for w in warnings:
        print("warning:", w, file=sys.stderr)

    if a.deploy:
        if not reg.get("project"):
            sys.exit("first deploy needs --project <name> (lowercase letters, digits, dashes)")
        url = deploy(site, reg["project"], root / "publish-worker")  # exits on failure: nothing is marked live
        if url and not a.base_url:
            reg["base_url"] = url
        # the whole site went up, so every report is live as last built
        reg["deployed"] = {k: reg.get("built", {}).get(k, 0) for k in reg["reports"]}
        save_registry(reg_path, reg)
    base = reg.get("base_url") or "<site-url>"
    print(f"site folder: {site}")
    if reg.get("hub"):
        print(f"  team hub       {base}/{reg['hub']}/")
    for key in (a.folders and [report_key(Path(f), root) for f in a.folders]) or reg["reports"]:
        print(f"  {key:<40s} {base}/{reg['reports'][key]}/")
    if not a.deploy:
        print("not uploaded yet: add --deploy")


if __name__ == "__main__":
    main()
