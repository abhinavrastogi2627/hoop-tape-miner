"""coach-summary reads v2 trips and still reads v1."""
from hoop_tape_miner.coach_schema import migrate_v1
from hoop_tape_miner.coach_summary import summarise

V1 = [{"offence": "us", "entry": "transition", "result": "made2 + FT 1/1 (and-one)", "foul": {"who": "21"}},
      {"offence": "us", "entry": "halfcourt_set", "result": "FT (0/2)", "foul": {"who": "them", "type": "reach_in"}},
      {"offence": "us", "entry": "halfcourt_set", "result": "FT (1/2)"},
      {"offence": "them", "entry": "halfcourt_set", "result": "turnover"}]


def test_summary_v2_matches_v1_where_information_is_the_same():
    v2 = [migrate_v1(x) for x in V1]
    a, b = summarise(V1), summarise(v2)
    assert b["us"]["results"] == {"made2": 1, "foul_ft": 2}
    assert b["us"]["transition_scores"] == 1 and b["us"]["halfcourt_scores"] == 1  # FT 0/2 scores nothing in v2
    assert a["us"]["halfcourt_scores"] == 2  # v1 counted any FT trip as a score
    assert b["them"]["turnovers"] == a["them"]["turnovers"] == 1
    assert b["fouls"] == {"them:unclear": 1, "them:reach_in": 1}  # a missing v1 type becomes "unclear"
