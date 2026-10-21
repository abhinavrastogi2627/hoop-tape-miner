"""The Four Factors panel on the team page (zh + en), read from the review's summary.json."""
import json
import shutil
from pathlib import Path

import pytest

from hoop_tape_miner import coach_summary as CS
from hoop_tape_miner import render_html
from test_four_factors import TRIPS

FIXTURE = Path(__file__).parent / "fixtures" / "report_min"


def _team_folder(tmp_path, summary):
    folder = tmp_path / "game"
    shutil.copytree(FIXTURE, folder)
    run = tmp_path / "run"
    (run / "review_v1").mkdir(parents=True)
    if summary is not None:
        (run / "review_v1" / "summary.json").write_text(json.dumps(summary), encoding="utf8")
    game = json.loads((folder / "game.json").read_text(encoding="utf8"))
    game["run"] = str(run)
    (folder / "game.json").write_text(json.dumps(game), encoding="utf8")
    return folder


def test_team_page_has_the_four_factors_panel(tmp_path):
    ann = CS.annotate(TRIPS)
    folder = _team_folder(tmp_path, {"all": {"four_factors": CS.four_factors(ann, min_poss=1), "ppp": CS.ppp(ann)}})
    page = render_html.page(folder)
    assert 'class="factors"' in page and "四要素" in page and "Four Factors" in page
    assert "75.0%" in page and "62.5%" in page
    assert "进攻篮板" in page and "Offensive rebounding" in page
    assert page.count('class="factors"') == 2  # one block per language
    assert "决定比赛的因素：进攻篮板（ORB%）" in page and "in favour of us" in page


def test_team_page_without_summary_has_no_panel(tmp_path):
    page = render_html.page(_team_folder(tmp_path, None))
    assert 'class="factors"' not in page


@pytest.mark.parametrize("value,want", [(None, "–"), (12.34, "12.3%")])
def test_panel_pct_format(value, want):
    assert render_html._ff_pct(value) == want
