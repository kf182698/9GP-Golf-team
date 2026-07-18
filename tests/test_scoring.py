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

from scoring import load_rules, score  # noqa: E402

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
    """整體結構比對（忽略 note / tie_break 純文字欄位）。

    expected fixture 未含 guest_scores（後加的輸出欄位），僅比對 expected 涵蓋的鍵。
    """
    got = {k: v for k, v in strip_prose(result).items() if k in expected}
    assert got == strip_prose(expected)


def test_guests_excluded_but_scores_retained(result):
    """來賓排除：3 位非會員不列入排名與獎項，但成績仍保留於輸出。"""
    assert result["excluded_guests"] == ["吳俊癸", "陳紫晴", "鄭家驊"]
    ranked_names = {r["name"] for r in result["net_ranking"]}
    assert not ranked_names & {"吳俊癸", "陳紫晴", "鄭家驊"}
    assert result["guest_scores"] == [
        {"name": "吳俊癸", "is_guest": True, "gross": 96},
        {"name": "陳紫晴", "is_guest": True, "gross": 111},
        {"name": "鄭家驊", "is_guest": True, "gross": 122},
    ]


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


def test_blocking_tie_needs_manual_resolution(rules, match_input):
    """淨桿與差點皆相同 → 回傳 needs_manual_resolution，中止獎項計算。"""
    # 製造「黃予安 與 曹勇良 差點同為 36、gross 同為 111 → net 同 75」的僵局
    tampered = copy.deepcopy(match_input)
    tampered_rules = copy.deepcopy(rules)
    for p in tampered_rules["players"]:
        if p["name"] == "黃予安":
            p["handicap"] = 36  # 與曹勇良同差點
    for p in tampered["players"]:
        if p["name"] == "黃予安":
            p["gross"] = 111  # net 75 = 曹勇良 net 75
    result = score(tampered_rules, tampered)
    assert result["needs_manual_resolution"] is True
    assert set(result["tie"]["names"]) == {"黃予安", "曹勇良"}
    assert result["tie"]["net"] == 75
    # 獎項與差點調整不得出現在阻斷結果中
    assert "awards" not in result
    assert "handicap_adjustment" not in result


def _make_deadlock(rules, match_input):
    """黃予安差點改 36、gross 改 111 → 與曹勇良淨桿 75 且差點同。"""
    tampered_rules = copy.deepcopy(rules)
    tampered = copy.deepcopy(match_input)
    for p in tampered_rules["players"]:
        if p["name"] == "黃予安":
            p["handicap"] = 36
    for p in tampered["players"]:
        if p["name"] == "黃予安":
            p["gross"] = 111
    return tampered_rules, tampered


def test_manual_tie_order_resolves_deadlock(rules, match_input):
    """總幹事裁定順序（manual_tie_order）→ 不阻斷，依裁定排序，獎項照算。"""
    tampered_rules, tampered = _make_deadlock(rules, match_input)
    tampered["manual_tie_order"] = ["曹勇良", "黃予安"]
    result = score(tampered_rules, tampered)
    assert "needs_manual_resolution" not in result
    names = [r["name"] for r in result["net_ranking"]]
    # 淨桿 75 兩人依裁定：曹勇良在前
    assert names.index("曹勇良") < names.index("黃予安")
    assert result["net_ranking"][names.index("曹勇良")]["net"] == 75
    # 幸運分享獎依裁定後的排名計算（冠軍 71 單數 → 1,3,5,7）
    lucky = result["awards"]["lucky_share"]["winners"]
    assert lucky == [r["name"] for r in result["net_ranking"] if r["rank"] % 2 == 1]
    # 反向裁定 → 順序跟著反
    tampered["manual_tie_order"] = ["黃予安", "曹勇良"]
    result2 = score(tampered_rules, tampered)
    names2 = [r["name"] for r in result2["net_ranking"]]
    assert names2.index("黃予安") < names2.index("曹勇良")


def test_manual_tie_order_must_cover_both(rules, match_input):
    """裁定名單沒涵蓋僵局雙方 → 仍阻斷，不得自行排序。"""
    tampered_rules, tampered = _make_deadlock(rules, match_input)
    tampered["manual_tie_order"] = ["曹勇良"]  # 只列一人
    result = score(tampered_rules, tampered)
    assert result["needs_manual_resolution"] is True


def test_gross_champion_cascade(rules, match_input):
    """總桿冠軍年度已領過 → 連鎖順延至次低未領者。"""
    result = score(rules, match_input, prior_gross_winners={"王建亞", "陳淂笙"})
    # 86 王建亞已領、87 陳淂笙已領 → 順延至 92 陳奕仲
    assert result["awards"]["gross_champion"]["winner"] == "陳奕仲"
    assert result["awards"]["gross_champion"]["gross"] == 92


def test_handicap_zero_winner_no_adjustment(rules, match_input):
    """差點 0 者得名次 → 已達下限，不做差點調整（bracket_zero_rule）。"""
    tampered_rules = copy.deepcopy(rules)
    for p in tampered_rules["players"]:
        if p["name"] == "王建亞":
            p["handicap"] = 0
    tampered = copy.deepcopy(match_input)
    for p in tampered["players"]:
        if p["name"] == "王建亞":
            p["gross"] = 70  # net = 70 - 0 = 70 → 淨桿冠軍
    result = score(tampered_rules, tampered)
    assert result["net_ranking"][0]["name"] == "王建亞"
    assert result["net_ranking"][0]["handicap"] == 0
    # 冠軍但差點 0 → 不出現在調整名單
    assert all(a["name"] != "王建亞" for a in result["handicap_adjustment"])
    # 其餘前三名（遞補的 rank 2、3）仍照常調整
    assert {a["net_rank"] for a in result["handicap_adjustment"]} <= {2, 3}


def test_eagle_multiple_per_player(rules, match_input):
    """Eagle 多隻重複發放：同一人兩洞達成 → 兩筆獎項。"""
    tampered = copy.deepcopy(match_input)
    for p in tampered["players"]:
        if p["name"] == "王建亞":
            # 第 3 洞 par 5 打 3（-2）、第 10 洞 par 6 打 4（-2）
            p["front_9"][2] = 3
            p["back_9"][0] = 4
            p["front_9_total"] = sum(p["front_9"])
            p["back_9_total"] = sum(p["back_9"])
            p["gross"] = p["front_9_total"] + p["back_9_total"]
    result = score(rules, tampered)
    eagles = result["awards"]["eagle"]["winners"]
    assert [(e["name"], e["hole"]) for e in eagles] == [("王建亞", 3), ("王建亞", 10)]
    assert all(e["prize"] == "ball x2" for e in eagles)


def test_lucky_share_even_parity(rules, match_input):
    """幸運分享獎雙數情境：淨桿冠軍淨桿為雙數 → 排名 2,4,6,8 得獎。"""
    tampered = copy.deepcopy(match_input)
    for p in tampered["players"]:
        if p["name"] == "陳淂笙":
            p["gross"] = 86  # net 86-16=70（雙數），仍為淨桿冠軍
    result = score(rules, tampered)
    lucky = result["awards"]["lucky_share"]
    assert lucky["parity_basis"] == 70
    assert lucky["parity"] == "even"
    even_rank_names = [r["name"] for r in result["net_ranking"] if r["rank"] % 2 == 0]
    assert lucky["winners"] == even_rank_names
    assert lucky["winners"] == ["陳奕仲", "陳彥宇", "曹勇良", "賀錫敬"]
