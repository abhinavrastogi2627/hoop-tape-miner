"""timefmt: one mm:ss rule for every stage (format at minute boundaries, parse h:mm:ss)."""
import pytest

from hoop_tape_miner import clips, coach_eval, coach_review, momentum, movement, official, plusminus, training
from hoop_tape_miner import move_scan
from hoop_tape_miner.timefmt import mmss, seconds


def test_whole_seconds_truncate_and_never_show_sixty():
    assert mmss(83.44) == "01:23"
    assert mmss(59.96) == "00:59"
    assert mmss(60.0) == "01:00"
    assert mmss(3725.9) == "62:05"     # minutes run past 59, as clip markers expect
    assert mmss(-3) == "00:00"


def test_tenths_round_first():
    assert mmss(83.44, 1) == "01:23.4"
    assert mmss(59.97, 1) == "01:00.0" and mmss(119.96, 1) == "02:00.0"
    assert mmss(0.04, 1) == "00:00.0"


def test_parse_mm_ss_and_h_mm_ss():
    assert seconds("1:05") == 65
    assert seconds("01:23.4") == pytest.approx(83.4)
    assert seconds("31:46.5") == 1906.5
    assert seconds("1:02:03.5") == pytest.approx(3723.5)
    assert seconds(12) == 12.0 and seconds(" 07:24 ") == 444
    with pytest.raises(ValueError):
        seconds("soon")


def test_stages_share_the_rule():
    for f in (coach_eval._mmss, coach_review.mmss, momentum._mmss, plusminus.mmss):
        assert f(59.96) == "00:59" and f(61) == "01:01"
    assert training.mmss(59.97) == move_scan._mmss(59.97) == "01:00.0"
    assert clips.seconds("1:02.5") == 62.5 and movement.secs("1:02:03") == 3723
    assert training.seconds("1:02:03.5") == pytest.approx(3723.5)
    assert official._mmss("12:34") == 754 and isinstance(official._mmss("12:34"), int)
