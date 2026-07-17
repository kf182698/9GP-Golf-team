"""金標驗收測試：scoring.py 必須重現 2025-06-21 桃園 fixture 的 expected 結果。

比對策略：移除純文字說明欄位（note、tie_break）後做結構相等比對，
並針對關鍵邊界情境各自明確 assert。
"""

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scoring import TieBreakBlocked, load_rules, score  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures"
PROSE_KEYS = {"note", "tie_break"}


def strip_prose(obj):
    """遞迴移除人類閱讀用的說明欄位，只留計算欄位。"""
    if isinstance(obj, dict):
        return {k: strip_prose(v) for k, v in obj.items() if k not in PROSE_KEYS}
    if isinstance(obj, list):
        return [strip_prose(v) for v in obj]
    return obj


@pytest.fixture(scope="module")
def rules():
    return load_rules(REPO_ROOT / "rules.yaml")


@pytest.fixture(scope="module")
def match_input():
    with open(FIXTURES / "2025-06-21_taoyuan_input.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def expected():
    with open(FIXTURES / "2025-06-21_taoyuan_expected.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def result(rules, match_input):
    return score(rules, match_input)


def test_matches_expected_fixture(result, expected):
    """整體結構比對（忽略 note / tie_break 純文字欄位）。"""
    assert strip_prose(result) == strip_prose(expected)


def test_guests_excluded(result):
    """來賓排除：3 位非會員不列入排名與獎項。"""
    assert result["excluded_guests"] == ["吳俊癸", "陳紫晴", "鄭家驊"]
    ranked_names = {r["name"] for r in result["net_ranking"]}
    assert not ranked_names & {"吳俊癸", "陳紫晴", "鄭家驊"}


def test_net_ranking_with_tie_breaks(result):
    """8 位會員排名；兩處同分（net 74、net 75）以差點少者優先。"""
    order = [(r["rank"], r["name"], r["net"]) for r in result["net_ranking"]]
    assert order == [
        (1, "陳淂笙", 71),
        (2, "陳奕仲", 72),
        (3, "王建亞", 74),   # 與陳彥宇同 74，差點 12 < 33
        (4, "陳彥宇", 74),
        (5, "洪榮杰", 75),   # 與曹勇良同 75，差點 30 < 36
        (6, "曹勇良", 75),
        (7, "黃予安", 79),
        (8, "賀錫敬", 80),
    ]


def test_awards(result):
    """總桿冠 86 王建亞、淨桿冠 71 陳淂笙、Eagle 空、近洞待手動。"""
    aw = result["awards"]
    assert aw["gross_champion"]["winner"] == "王建亞"
    assert aw["gross_champion"]["gross"] == 86
    assert aw["gross_champion"]["prize"] == "cash 500"
    assert aw["net_champion"]["winner"] == "陳淂笙"
    assert aw["net_champion"]["net"] == 71
    assert aw["net_champion"]["prize"] == "ball x1"
    assert aw["eagle"]["winners"] == []
    assert aw["near_pin"]["winner"] is None


def test_lucky_share_parity(result):
    """淨桿冠軍淨桿 71 為單數 → 排名 1,3,5,7 得獎，每人 200。"""
    lucky = result["awards"]["lucky_share"]
    assert lucky["parity_basis"] == 71
    assert lucky["parity"] == "odd"
    assert lucky["winners"] == ["陳淂笙", "王建亞", "洪榮杰", "黃予安"]
    assert lucky["prize_each"] == 200


def test_handicap_adjustment_third_place_zero(result):
    """關鍵測試點：11~20 區間季軍欄為空 → 拿到淨桿季軍但不扣差點。"""
    adj = {a["name"]: a for a in result["handicap_adjustment"]}
    assert adj["陳淂笙"] == {"name": "陳淂笙", "net_rank": 1, "before": 16,
                             "bracket": "11~20", "delta": -2, "after": 14}
    assert adj["陳奕仲"] == {"name": "陳奕仲", "net_rank": 2, "before": 20,
                             "bracket": "11~20", "delta": -1, "after": 19}
    assert adj["王建亞"]["delta"] == 0
    assert adj["王建亞"]["after"] == 12  # 季軍不扣


def test_blocking_tie_raises(rules, match_input):
    """淨桿與差點皆相同 → 阻斷，不得自行排序。"""
    # 製造「黃予安 與 曹勇良 差點同為 36、gross 同為 111 → net 同 75」的僵局
    tampered = copy.deepcopy(match_input)
    tampered_rules = copy.deepcopy(rules)
    for p in tampered_rules["players"]:
        if p["name"] == "黃予安":
            p["handicap"] = 36  # 與曹勇良同差點
    for p in tampered["players"]:
        if p["name"] == "黃予安":
            p["gross"] = 111  # net 75 = 曹勇良 net 75
    with pytest.raises(TieBreakBlocked):
        score(tampered_rules, tampered)


def test_gross_champion_cascade(rules, match_input):
    """總桿冠軍年度已領過 → 連鎖順延至次低未領者。"""
    result = score(rules, match_input, prior_gross_winners={"王建亞", "陳淂笙"})
    # 86 王建亞已領、87 陳淂笙已領 → 順延至 92 陳奕仲
    assert result["awards"]["gross_champion"]["winner"] == "陳奕仲"
    assert result["awards"]["gross_champion"]["gross"] == 92
