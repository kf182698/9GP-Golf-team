"""發布橋接測試（全部離線）。

用桃園 fixture input 驗證 publish.py 的中文列轉換、會期彙整、
rules.yaml 差點寫回（保留註解）、冪等替換與同分阻斷。
"""

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from publish import (  # noqa: E402
    apply_handicap_to_rules,
    collect_prior_gross_winners,
    main,
    match_title,
    merge_scores,
    parse_award_period,
)
from scoring import load_rules  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures"
INPUT = FIXTURES / "2025-06-21_taoyuan_input.json"


@pytest.fixture()
def rules():
    return load_rules(REPO_ROOT / "rules.yaml")


@pytest.fixture()
def sandbox(tmp_path):
    """tmp 沙盒：rules.yaml 副本 + 空成績檔 + fixture 確認稿。"""
    rules_path = tmp_path / "rules.yaml"
    scores_path = tmp_path / "golf_scores.json"
    input_path = tmp_path / "confirmed.json"
    shutil.copy(REPO_ROOT / "rules.yaml", rules_path)
    scores_path.write_text("[]", encoding="utf-8")
    shutil.copy(INPUT, input_path)
    return rules_path, scores_path, input_path


def run_publish(rules_path, scores_path, input_path, extra=()):
    return main(["--rules", str(rules_path), "--input", str(input_path),
                 "--scores", str(scores_path), *extra])


# ------------------ 中文列轉換 ------------------

def test_publish_builds_full_roster_rows(sandbox, capsys):
    rules_path, scores_path, input_path = sandbox
    assert run_publish(rules_path, scores_path, input_path) == 0

    rows = json.loads(scores_path.read_text(encoding="utf-8"))
    # 名冊 15 + 來賓 3 = 18 列
    assert len(rows) == 18
    by_name = {r["球員姓名"]: r for r in rows}

    ranked = [r for r in rows if isinstance(r["名次"], int)]
    guests = [r for r in rows if r["名次"] == "來賓"]
    absent = [r for r in rows if r["名次"] == "請假"]
    assert (len(ranked), len(guests), len(absent)) == (8, 3, 7)

    # 例賽名稱用 courses aliases 短名
    assert rows[0]["例賽名稱"] == "2025年06月例賽（桃園）"

    # 冠軍列抽查：淨桿冠 + 幸運獎（近洞獎 null 不出現），固定順序
    champ = by_name["陳淂笙"]
    assert (champ["名次"], champ["差點"], champ["總桿數"], champ["淨桿數"]) == (1, 16, 87, 71)
    assert champ["所獲獎項"] == "淨桿冠、幸運獎"
    # 總桿冠 + 幸運獎
    assert by_name["王建亞"]["所獲獎項"] == "總桿冠、幸運獎"
    # 無獎者為 null
    assert by_name["陳彥宇"]["所獲獎項"] is None

    # 來賓：成績保留、差點/淨桿 null
    g = by_name["鄭家驊"]
    assert (g["名次"], g["總桿數"], g["差點"], g["淨桿數"]) == ("來賓", 122, None, None)

    # 請假：差點=名冊現值、桿數 null
    a = by_name["楊嘉一"]
    assert (a["名次"], a["差點"], a["總桿數"], a["淨桿數"]) == ("請假", 18, None, None)


def test_manual_near_pin_award(sandbox):
    rules_path, scores_path, input_path = sandbox
    data = json.loads(input_path.read_text(encoding="utf-8"))
    data["manual_awards"]["near_pin"] = ["王建亞", "賀錫敬"]
    input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    assert run_publish(rules_path, scores_path, input_path) == 0
    rows = json.loads(scores_path.read_text(encoding="utf-8"))
    by_name = {r["球員姓名"]: r for r in rows}
    assert by_name["王建亞"]["所獲獎項"] == "近洞獎、總桿冠、幸運獎"
    assert by_name["賀錫敬"]["所獲獎項"] == "近洞獎"


# ------------------ 會期彙整 ------------------

def test_parse_award_period(rules):
    assert parse_award_period(rules) == ("2025-07", "2026-09")


def test_prior_gross_winners_scoped_to_award_period(rules):
    scores = [
        {"賽事日期": "2025-06-21", "球員姓名": "會期外", "所獲獎項": "總桿冠"},
        {"賽事日期": "2025-08-23", "球員姓名": "會期內", "所獲獎項": "近洞獎、總桿冠"},
        {"賽事日期": "2026-05-22", "球員姓名": "另一位", "所獲獎項": "總桿冠、淨桿冠"},
        {"賽事日期": "2026-05-22", "球員姓名": "非總桿", "所獲獎項": "幸運獎"},
    ]
    assert collect_prior_gross_winners(scores, rules) == {"會期內", "另一位"}


def test_gross_champion_cascades_from_history(sandbox):
    """歷史成績中王建亞已於會期內領過總桿冠 → 順延至次低者陳淂笙。"""
    rules_path, scores_path, input_path = sandbox
    scores_path.write_text(json.dumps([
        {"賽事日期": "2025-08-23", "例賽名稱": "x", "球員姓名": "王建亞",
         "差點": 12, "總桿數": 80, "淨桿數": 68, "名次": 1, "所獲獎項": "總桿冠"},
    ], ensure_ascii=False), encoding="utf-8")

    assert run_publish(rules_path, scores_path, input_path) == 0
    rows = json.loads(scores_path.read_text(encoding="utf-8"))
    june = {r["球員姓名"]: r for r in rows if r["賽事日期"] == "2025-06-21"}
    assert "總桿冠" not in (june["王建亞"]["所獲獎項"] or "")
    assert "總桿冠" in june["陳淂笙"]["所獲獎項"]


# ------------------ rules.yaml 差點寫回 ------------------

def test_handicap_written_back_preserving_comments(sandbox):
    rules_path, scores_path, input_path = sandbox
    before = rules_path.read_text(encoding="utf-8")
    assert run_publish(rules_path, scores_path, input_path) == 0

    after = rules_path.read_text(encoding="utf-8")
    updated = yaml.safe_load(after)
    hc = {p["name"]: p["handicap"] for p in updated["players"]}
    assert hc["陳淂笙"] == 14   # 冠軍 16 → -2
    assert hc["陳奕仲"] == 19   # 亞軍 20 → -1
    assert hc["王建亞"] == 12   # 季軍 11~20 區間扣 0 → 不變

    # 註解與其他區塊原樣保留
    assert "# 差點基準日: 2026-05-22" in after
    assert "bracket_zero_rule" in after
    # 只有兩行差點數字被改動
    diff_lines = [
        (a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b
    ]
    assert len(diff_lines) == 2


def test_apply_handicap_refuses_ambiguous_name(tmp_path):
    """名冊找不到唯一匹配行 → 中止而非誤改。"""
    p = tmp_path / "rules.yaml"
    p.write_text('players:\n  - { name: "甲", handicap: 10 }\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="乙"):
        apply_handicap_to_rules(p, [{"name": "乙", "before": 9, "after": 8, "delta": -1}])


# ------------------ 冪等 / 排序 / 阻斷 ------------------

def test_republish_is_idempotent(sandbox):
    rules_path, scores_path, input_path = sandbox
    assert run_publish(rules_path, scores_path, input_path) == 0
    first = json.loads(scores_path.read_text(encoding="utf-8"))
    # 第二次發布：同日期整批替換，不重複（差點已被第一次改過，
    # 列內容會反映新差點，但列數與成員不變）
    assert run_publish(rules_path, scores_path, input_path) == 0
    second = json.loads(scores_path.read_text(encoding="utf-8"))
    assert len(second) == len(first) == 18
    assert {r["球員姓名"] for r in second} == {r["球員姓名"] for r in first}


def test_merge_keeps_other_matches_sorted():
    old = [{"賽事日期": "2025-08-23", "球員姓名": "甲"}]
    new = [{"賽事日期": "2025-06-21", "球員姓名": "乙"}]
    merged = merge_scores(old, new, "2025-06-21")
    assert [r["賽事日期"] for r in merged] == ["2025-06-21", "2025-08-23"]


def test_blocking_tie_exits_2_and_writes_nothing(sandbox, capsys):
    rules_path, scores_path, input_path = sandbox
    # 製造僵局：改 rules 副本讓黃予安差點=36，input 讓其 gross=111（同曹勇良）
    text = rules_path.read_text(encoding="utf-8")
    rules_path.write_text(
        text.replace('- { name: "黃予安", handicap: 32 }',
                     '- { name: "黃予安", handicap: 36 }'),
        encoding="utf-8")
    data = json.loads(input_path.read_text(encoding="utf-8"))
    for p in data["players"]:
        if p["name"] == "黃予安":
            p["gross"] = 111
    input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    rules_before = rules_path.read_text(encoding="utf-8")
    assert run_publish(rules_path, scores_path, input_path) == 2
    assert "同分待總幹事裁定" in capsys.readouterr().out
    # 未寫任何檔案
    assert scores_path.read_text(encoding="utf-8") == "[]"
    assert rules_path.read_text(encoding="utf-8") == rules_before


def test_manual_tie_order_publishes(sandbox):
    """確認稿帶 manual_tie_order → 僵局解除、正常發布 exit 0。"""
    rules_path, scores_path, input_path = sandbox
    text = rules_path.read_text(encoding="utf-8")
    rules_path.write_text(
        text.replace('- { name: "黃予安", handicap: 32 }',
                     '- { name: "黃予安", handicap: 36 }'),
        encoding="utf-8")
    data = json.loads(input_path.read_text(encoding="utf-8"))
    for p in data["players"]:
        if p["name"] == "黃予安":
            p["gross"] = 111
    data["manual_tie_order"] = ["黃予安", "曹勇良"]
    input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    assert run_publish(rules_path, scores_path, input_path) == 0
    rows = json.loads(scores_path.read_text(encoding="utf-8"))
    by_name = {r["球員姓名"]: r for r in rows}
    assert by_name["黃予安"]["名次"] < by_name["曹勇良"]["名次"]


def test_dry_run_writes_nothing(sandbox, capsys):
    rules_path, scores_path, input_path = sandbox
    rules_before = rules_path.read_text(encoding="utf-8")
    assert run_publish(rules_path, scores_path, input_path, extra=["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry-run" in out and "陳淂笙" in out
    assert scores_path.read_text(encoding="utf-8") == "[]"
    assert rules_path.read_text(encoding="utf-8") == rules_before


# ------------------ workflow 檔案 ------------------

def test_workflows_parse_and_have_required_fields():
    for name in ("ocr.yml", "score.yml"):
        with open(REPO_ROOT / ".github" / "workflows" / name, encoding="utf-8") as f:
            wf = yaml.safe_load(f)
        # PyYAML 會把 on 解析成 True（YAML 1.1 布林）
        triggers = wf.get("on") or wf.get(True)
        assert "workflow_dispatch" in triggers
        assert wf["permissions"] == {"contents": "write"}
        assert "jobs" in wf
    with open(REPO_ROOT / ".github" / "workflows" / "ocr.yml", encoding="utf-8") as f:
        ocr = yaml.safe_load(f)
    inputs = (ocr.get("on") or ocr.get(True))["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"image_dir", "card_type"}
    assert inputs["card_type"]["options"] == ["iswing", "handwritten"]
