"""Coaching knowledge base: every entry is complete and cites a source."""
import re
from pathlib import Path

KB = Path(__file__).resolve().parents[1] / "prompts" / "coach_kb.md"
LABELS = (
    "Symptom (observable)",
    "Why it happens",
    "What to check on film",
    "In-game rule",
    "Drill",
    "Next-game target",
    "Source",
)
PAGE_OR_URL = re.compile(r"(\bpp?\.\s*\d+|\bpages?\s+\d+|https?://)", re.IGNORECASE)


def parse_kb(text: str) -> dict[str, dict[str, str]]:
    """Return {slug: {label: text}} for every `### KB-<slug>` section."""
    entries: dict[str, dict[str, str]] = {}
    sections = re.split(r"^### KB-", text, flags=re.MULTILINE)[1:]
    label_re = re.compile(r"^\*\*(" + "|".join(map(re.escape, LABELS)) + r"):\*\*", re.MULTILINE)
    for sec in sections:
        slug, _, body = sec.partition("\n")
        slug = slug.strip()
        assert slug not in entries, f"duplicate slug KB-{slug}"
        body = re.split(r"^#{1,3} ", body, flags=re.MULTILINE)[0]
        marks = list(label_re.finditer(body))
        fields = {}
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
            fields[m.group(1)] = body[m.end():end].strip()
        entries[slug] = fields
    return entries


def test_kb_entries_complete():
    entries = parse_kb(KB.read_text(encoding="utf-8"))
    assert len(entries) >= 10
    for slug, fields in entries.items():
        assert re.fullmatch(r"[a-z0-9-]+", slug), f"bad slug KB-{slug}"
        for label in LABELS:
            assert fields.get(label), f"KB-{slug}: missing or empty {label}"
        assert PAGE_OR_URL.search(fields["Source"]), f"KB-{slug}: Source needs a page ref or URL"


def test_kb_header_marks_own_numbers_and_rules():
    head = KB.read_text(encoding="utf-8").split("### KB-", 1)[0]
    assert "our own trial value" in head, "header must say targets and success measures are our trial values"
    assert '"(our rule)"' in head, "header must explain how our own rules are marked"
