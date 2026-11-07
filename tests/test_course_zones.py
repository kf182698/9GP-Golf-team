"""球場分區測試（2026-11-07 起：以九洞區登錄、每場記錄下場區域、待補區自動補登）。

情境取自新豐高爾夫球場：西／東／中三區，11/7 只打西＋東，中區 par 尚未登錄。
沙盒用活的 rules.yaml 副本，只驗證分區相關行為，不比對差點數值。
"""

import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from publish import (  # noqa: E402
    build_match_rows,
    fill_nine_pars_in_rules,
    pending_nine_pars,
    publish,
)
from scoring import load_rules, score  # noqa: E402

RULES = REPO_ROOT / "rules.yaml"
WEST = [4, 4, 3, 4, 5, 3, 4, 4, 5]
EAST = [4, 3, 4, 4, 5, 4, 4, 3, 5]
MIDDLE = [4, 5, 3, 4, 4, 3, 5, 4, 4]   # 測試用假設值，非實際中區 par


def xinfeng(rules):
    return next(c for c in rules["courses"] if c["name"] == "新豐高爾夫球場")


def match(front, back, pars):
    holes = [p + 1 for p in pars]              # 全場每洞柏忌
    return {
        "date": "2026-12-05", "course": "新豐高爾夫球場",
        "course_par": sum(pars), "front_nine_name": front, "back_nine_name": back,
        "hole_pars": pars, "manual_awards": {"near_pin": []},
        "players": [{"name": "陳彥宇", "is_guest": False,
                     "front_9": holes[:9], "back_9": holes[9:],
                     "front_9_total": sum(holes[:9]), "back_9_total": sum(holes[9:]),
                     "gross": sum(holes), "vs_par": 18, "validation": "pass"}],
    }


def test_xinfeng_registered_as_three_zones_with_middle_pending():
    c = xinfeng(load_rules(RULES))
    assert [n["name"] for n in c["nines"]] == ["西", "東", "中"]
    assert c["nines"][0]["pars"] == WEST and c["nines"][1]["pars"] == EAST
    assert c["nines"][2]["pars"] is None, "中區未打過，par 應為待補（null）"


def test_every_registered_zone_is_nine_holes_or_pending():
    for c in load_rules(RULES)["courses"]:
        for n in c["nines"]:
            assert n["pars"] is None or (len(n["pars"]) == 9 and n["total"] == sum(n["pars"])), \
                f"{c['name']}「{n['name']}」區 par 格式錯誤"


def test_rows_record_zones_played():
    rules = load_rules(RULES)
    m = match("西", "東", WEST + EAST)
    rows = build_match_rows(score(rules, m), m, rules)
    me = next(r for r in rows if r["球員姓名"] == "陳彥宇")
    assert me["下場區域"] == "西／東"
    absent = next(r for r in rows if r["名次"] == "請假")
    assert absent["下場區域"] is None


def test_known_zones_are_not_backfilled():
    assert pending_nine_pars(match("西", "東", WEST + EAST), load_rules(RULES)) == []


def test_pending_zone_backfilled_on_publish_keeps_comments(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    shutil.copy(RULES, rules_path)
    scores_path = tmp_path / "golf_scores.json"
    scores_path.write_text("[]", encoding="utf-8")
    input_path = tmp_path / "confirmed.json"
    input_path.write_text(json.dumps(match("東", "中", EAST + MIDDLE), ensure_ascii=False),
                          encoding="utf-8")

    code, summary = publish(str(rules_path), str(input_path), str(scores_path))
    assert code == 0 and "「中」區首次下場" in summary

    text = rules_path.read_text(encoding="utf-8")
    c = xinfeng(yaml.safe_load(text))
    mid = next(n for n in c["nines"] if n["name"] == "中")
    assert mid["pars"] == MIDDLE and mid["total"] == sum(MIDDLE)
    assert c["nines"][0]["pars"] == WEST, "已登錄的區不得被改動"
    assert "# 中區尚未打過" in text, "補登必須保留檔內註解"

    rows = json.loads(scores_path.read_text(encoding="utf-8"))
    assert next(r for r in rows if r["球員姓名"] == "陳彥宇")["下場區域"] == "東／中"


def test_backfill_refuses_incomplete_pars():
    m = match("東", "中", EAST + MIDDLE)
    m["hole_pars"] = EAST + MIDDLE[:8] + [None]   # 中區最後一洞漏填
    with pytest.raises(RuntimeError):
        pending_nine_pars(m, load_rules(RULES))


def test_backfill_aborts_when_course_missing(tmp_path):
    p = tmp_path / "rules.yaml"
    p.write_text("courses: []\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        fill_nine_pars_in_rules(str(p), [("不存在球場", "中", MIDDLE)])
