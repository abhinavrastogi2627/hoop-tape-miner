"""Publish reports as a private-link website, so the team opens one link instead of downloading files.

usage: hoop-tape-miner publish workspace/teams/<opponent>/<date> [workspace/teams/<opponent>/<date>/player-<N> ...]
       hoop-tape-miner publish ... --deploy --project <cloudflare-worker-name>
       hoop-tape-miner publish --deploy            (re-upload the site as it is)

Each report folder gets a random, stable path: re-publishing after an edit overwrites the same page, so the
link sent once keeps showing the latest version. Pages are the --share text (no local paths or repo links)
with audio and clips kept as files next to them, which in-app browsers play better than embedded data.
Team reports (not player-<N> folders) are also listed on a hub page with its own random path; personal
reports are only reachable through their own link.

Everything is built in <workspace>/site/ (paths -> tokens in <workspace>/publish.json, both gitignored) and
uploaded with `npx wrangler deploy` as Cloudflare Workers static assets (the successor of Pages; free plan,
run `npx wrangler login` once) behind publish_worker.js, which answers the Range requests Safari needs to play
clips. The site lands on https://<project>.<your-subdomain>.workers.dev.
The site is unlisted, not access-controlled: anyone holding a link can open it. See docs/privacy.md.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

from . import render_html
from . import workspace as ws

MAX_FILE = 25 * 1024 * 1024  # Cloudflare static assets per-file limit (25 MiB)
HEADERS = """/*
  X-Robots-Tag: noindex, nofollow
  Referrer-Policy: no-referrer
"""
ROBOTS = "User-agent: *\nDisallow: /\n"
BLANK = '<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex"><title>.</title>\n'
LOCAL_SRC = re.compile(r'(?:src|poster)="((?!https?:|data:|#)[^"]+)"')


def token() -> str:
    return secrets.token_hex(8)  # 64 bits: not guessable, short enough for a chat message


def load_registry(path: Path) -> dict:
    reg = json.loads(path.read_text(encoding="utf8")) if path.exists() else {}
    reg.setdefault("reports", {})
    return reg


def report_key(folder: Path, root: Path) -> str:
    try:
        return folder.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        sys.exit(f"{folder} is not inside the workspace {root} (set HOOP_WORKSPACE)")


def build_report(folder: Path, dest: Path) -> list[str]:
    """Render the web page into dest (emptied first) and copy the audio/clip files it links to.
    Returns warnings (missing or oversized files)."""
    page = render_html.page(folder, share=True, embed=False)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    (dest / "index.html").write_text(page, encoding="utf8")
    warnings = []
    for rel in sorted(set(LOCAL_SRC.findall(page))):
        src = folder / rel
        if not src.is_file():
            warnings.append(f"{folder.name}: {rel} is linked but missing")
            continue
        if src.stat().st_size > MAX_FILE:
            warnings.append(f"{folder.name}: {rel} is over 25 MiB, Cloudflare will reject it")
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / rel)
    return warnings


def title_of(folder: Path) -> str:
    m = re.match(r"# (.*)", (folder / "README.md").read_text(encoding="utf8"))
    return m.group(1).strip() if m else folder.name


def hub_page(entries: list[tuple[str, str, str]]) -> str:
    """entries: (date, title, token) of team reports, newest first."""
    items = "".join(f'<li><a href="../{t}/"><small>{html.escape(d)}</small>{html.escape(title)}</a></li>'
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
    team = []
    for key, t in reg["reports"].items():
        folder = root / key
        # player pages and personal (training, movement) sessions get their own link but are never on the team hub
        if (re.fullmatch(r"player-\w+", folder.name) or not (folder / "README.md").exists()
                or (folder / "session.json").exists() or (folder / "movement.json").exists()):
            continue
        team.append((folder.name, title_of(folder), t))
    if team:
        reg.setdefault("hub", token())
        hub = site / reg["hub"]
        hub.mkdir(exist_ok=True)
        (hub / "index.html").write_text(hub_page(sorted(team, reverse=True)), encoding="utf8")


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
        if not (folder / "README.md").exists():
            sys.exit(f"{folder} has no README.md")
        key = report_key(folder, root)
        old = reg["reports"].get(key)
        if a.new_link or not old:
            if old and (site / old).exists():
                shutil.rmtree(site / old)
            reg["reports"][key] = token()
        warnings += build_report(folder, site / reg["reports"][key])
    write_site(site, reg, root)
    reg_path.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf8")
    for w in warnings:
        print("warning:", w, file=sys.stderr)

    if a.deploy:
        if not reg.get("project"):
            sys.exit("first deploy needs --project <name> (lowercase letters, digits, dashes)")
        url = deploy(site, reg["project"], root / "publish-worker")
        if url and not a.base_url:
            reg["base_url"] = url
        reg_path.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf8")
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
