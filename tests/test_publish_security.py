"""Publish safety: raw HTML is escaped, pages only pull files from their own folder, the registry survives a
crash and a failed deploy is never recorded as published, the Worker sends security headers."""
import base64
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from hoop_tape_miner import publish, render_html
from hoop_tape_miner import run as R

FIXTURE = Path(__file__).parent / "fixtures" / "report_min"
WORKER = Path(publish.__file__).with_name("publish_worker.js")


def report(tmp_path: Path, extra: str = "") -> Path:
    folder = tmp_path / "game"
    shutil.copytree(FIXTURE, folder)
    for name in ("README.md", "README.en.md"):
        p = folder / name
        p.write_text(p.read_text(encoding="utf8") + "\n" + extra + "\n", encoding="utf8")
    return folder


def test_raw_html_in_a_readme_is_escaped(tmp_path):
    folder = report(tmp_path, '<script>alert(1)</script>\n\n<img src="x" onerror="alert(2)">\n\n'
                              '<iframe src="https://example.com"></iframe>\n\nSee <date> here.')
    page = render_html.page(folder, share=True, embed=False)
    assert "<script>alert" not in page and "<iframe" not in page and 'onerror="' not in page
    assert "&lt;script&gt;alert(1)" in page and "&lt;date&gt;" in page


def test_markdown_links_cannot_run_script(tmp_path):
    body, _ = render_html.render("[x](javascript:alert(1)) ![y](javascript:alert(2))\n", "en")
    assert '="javascript:' not in body  # markdown-it refuses the link; the text stays as plain text


def test_inline_images_stay_inside_the_report_folder(tmp_path):
    folder = report(tmp_path, "![a](../secret.png)\n\n![b](plot.png)")
    (tmp_path / "secret.png").write_bytes(b"\x89PNG secret")
    (folder / "plot.png").write_bytes(b"\x89PNG plot")
    page = render_html.page(folder)
    assert base64.b64encode(b"\x89PNG secret").decode() not in page
    assert base64.b64encode(b"\x89PNG plot").decode() in page
    absolute = render_html.inline_images(f'<img src="{(tmp_path / "secret.png").as_posix()}">', folder)
    assert "base64" not in absolute


def test_publish_copies_only_files_inside_the_report(tmp_path, monkeypatch, capsys):
    folder = report(tmp_path, '![a](../other/clip.mp4)\n\n![b](C:/Users/someone/x.png)\n\n![c](/etc/passwd)')
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "clip.mp4").write_bytes(b"not yours")
    monkeypatch.setattr(render_html, "duration_s", lambda p: 60.0)
    dest = tmp_path / "site" / "tok"
    warnings = publish.build_report(folder, dest)
    assert not (tmp_path / "site" / "other").exists() and not (tmp_path / "site" / "clip.mp4").exists()
    assert {p.name for p in (tmp_path / "site").rglob("*") if p.is_file()} == {"index.html"}
    page = (dest / "index.html").read_text(encoding="utf8")
    assert "../other" not in page and "C:/Users" not in page and "/etc/passwd" not in page
    assert sum("outside the report" in w for w in warnings) == 3


def test_published_page_pins_its_inline_script(tmp_path, monkeypatch):
    folder = report(tmp_path)
    dest = tmp_path / "site" / "tok"
    publish.build_report(folder, dest)
    page = (dest / "index.html").read_text(encoding="utf8")
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert len(scripts) == 1
    digest = base64.b64encode(hashlib.sha256(scripts[0].encode("utf8")).digest()).decode()
    meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', page)
    assert meta and f"'sha256-{digest}'" in meta.group(1)
    assert page.index("Content-Security-Policy") < page.index("<script>")


def test_registry_write_is_atomic_and_keeps_a_backup(tmp_path):
    path = tmp_path / "publish.json"
    publish.save_registry(path, {"reports": {"a": "1"}})
    publish.save_registry(path, {"reports": {"a": "2"}})
    assert json.loads(path.read_text(encoding="utf8"))["reports"]["a"] == "2"
    assert json.loads(path.with_suffix(".json.bak").read_text(encoding="utf8"))["reports"]["a"] == "1"
    assert not list(tmp_path.glob("*.tmp"))
    path.write_text('{"reports": {"a": "2"', encoding="utf8")  # a crash mid-write (older version)
    assert publish.load_registry(path)["reports"]["a"] == "1"   # recovered, the links already sent stay
    path.with_suffix(".json.bak").unlink()
    with pytest.raises(SystemExit):  # never mint new tokens over a broken registry
        publish.load_registry(path)


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOP_WORKSPACE", str(tmp_path))
    folder = tmp_path / "teams" / "foxes" / "2026-01-01"
    shutil.copytree(FIXTURE, folder)
    (folder / "index.html").write_text("old page", encoding="utf8")
    monkeypatch.setattr(R.Game, "reports", lambda self: [self.folder])
    return folder


def test_failed_deploy_is_not_published(game, monkeypatch):
    def fail(*a):
        raise SystemExit("wrangler deploy failed")
    monkeypatch.setattr(publish, "deploy", fail)
    with pytest.raises(SystemExit):
        publish.main([str(game), "--deploy", "--project", "team-film"])
    reg = json.loads((game.parents[2] / "publish.json").read_text(encoding="utf8"))
    assert reg["reports"]  # the token is kept, so the next try reuses the same link
    assert not R.published(R.Game.load(game))

    monkeypatch.setattr(publish, "deploy", lambda *a: "https://team-film.example.workers.dev")
    publish.main([str(game), "--deploy"])
    assert R.published(R.Game.load(game))


def test_publish_without_deploy_is_not_published(game):
    publish.main([str(game)])
    assert not R.published(R.Game.load(game))


def test_worker_sends_security_headers():
    js = WORKER.read_text(encoding="utf8")
    for h in ("Content-Security-Policy", "X-Content-Type-Options", "nosniff", "Referrer-Policy", "no-referrer",
              "X-Robots-Tag", "noindex", "frame-ancestors 'none'"):
        assert h in js


NODE_CHECK = r"""
import worker from "./worker.mjs";
const body = new Uint8Array(100).map((_, i) => i);
const env = { ASSETS: { async fetch(req) {
  const path = new URL(req.url).pathname;
  if (path === "/tok/clip.mp4") return new Response(body, { status: 200, headers: { "Content-Type": "video/mp4" } });
  return new Response("<!doctype html>", { status: 200, headers: { "Content-Type": "text/html" } });
} } };
const out = {};
for (const [name, url, init] of [
    ["page", "https://x.dev/tok/", {}],
    ["range", "https://x.dev/tok/clip.mp4", { headers: { Range: "bytes=10-19" } }],
    ["dots", "https://x.dev/tok/..%2Fsecret", {}],
    ["post", "https://x.dev/tok/", { method: "POST" }]]) {
  const r = await worker.fetch(new Request(url, init), env);
  out[name] = { status: r.status, headers: Object.fromEntries(r.headers), size: (await r.arrayBuffer()).byteLength };
}
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_worker_headers_on_every_response(tmp_path):
    shutil.copy(WORKER, tmp_path / "worker.mjs")
    (tmp_path / "check.mjs").write_text(NODE_CHECK, encoding="utf8")
    r = subprocess.run(["node", "check.mjs"], cwd=tmp_path, capture_output=True, text=True, encoding="utf8",
                       timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["range"]["status"] == 206 and out["range"]["size"] == 10
    assert out["dots"]["status"] == 404 and out["post"]["status"] == 405
    for name in ("page", "range", "dots", "post"):
        h = out[name]["headers"]
        assert h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "no-referrer"
        assert "noindex" in h["x-robots-tag"] and "default-src 'none'" in h["content-security-policy"]
