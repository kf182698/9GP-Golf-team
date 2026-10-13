"""活的 rules.yaml 章程設定驗證（2026-10 新年度）。

本檔刻意讀「活的」rules.yaml——金標 fixture 讀凍結快照
（tests/fixtures/2025-06-21_taoyuan_rules.yaml），那是為了讓名冊差點的例行
扣減不會打壞計分邏輯的比對；但「章程本身」（會期、賽制、名冊組成）就是
要盯活檔，章程改了而程式沒跟上才是真正要擋下的事。

重要：score.yml 發布前會跑 pytest 當守門，測試一壞則所有一鍵發布都會被擋。
因此本檔的斷言只能是**整個會期內都成立**的不變式：
  - 名冊人數與姓名（會期內不變）
  - 差點只會被例賽扣減、不會自行上升 → 活檔差點 <= 年度基準
  - 新會期尚未發布任何例賽時，活檔差點必須完全等於年度基準
下次年度重算（調高差點）時，連同 BASELINE_2026 一併更新。
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from publish import collect_prior_gross_winners, parse_award_period  # noqa: E402
from scoring import load_rules  # noqa: E402

LIVE_RULES = REPO_ROOT / "rules.yaml"
LIVE_SCORES = REPO_ROOT / "golf_scores.json"

AWARD_PERIOD_2026 = ("2026-10", "2027-09")

# 2026 年度重算後的差點基準（差點基準日 2026-10-01，新會期 2026-10-24 首場起適用）
# 依據：2025-10 ~ 2026-09 共 6 場例賽平均總桿 − 72，四捨五入採「.5 進位」
BASELINE_2026 = {
    "陳翊彥": 13,
    "王建亞": 17,
    "陳淂笙": 20,
    "陳奕仲": 20,
    "賀錫敬": 22,
    "楊嘉一": 22,
    "林家進": 23,
    "何崇華": 28,
    "劉韋廷": 29,
    "洪榮杰": 32,
    "劉維智": 32,
    "陳彥宇": 33,
    "黃予安": 34,
    "曹勇良": 36,
    "曾吟芳": 36,
    # 2026-10 新年度入隊，差點以上限 36 起算
    "黃心瀅": 36,
    "林寬宸": 36,
}


@pytest.fixture(scope="module")
def rules():
    return load_rules(LIVE_RULES)


@pytest.fixture(scope="module")
def live_rows():
    with open(LIVE_SCORES, encoding="utf-8") as f:
        return json.load(f)


# ------------------ 賽制與會期 ------------------

def test_award_period_is_new_charter_year(rules):
    assert parse_award_period(rules) == AWARD_PERIOD_2026


def test_event_frequency_is_monthly(rules):
    """新年度章程：球敘由每 2 個月一次改為每月一場。"""
    assert rules["event"]["frequency"] == "monthly"


def test_annual_review_declares_half_up_rounding(rules):
    """平均桿數四捨五入採「.5 進位」（同 Excel ROUND），以規則欄位登載而非僅寫在 note。"""
    assert rules["handicap"]["annual_review"]["rounding"] == "half_up"


def test_new_award_period_resets_prior_gross_winners(rules):
    """總桿冠軍「年度限領一次」隨會期重新起算：舊會期得主一律不計入。

    用舊會期（2025-07 ~ 2026-09）的實際總桿冠紀錄餵進去，新會期應回傳空集合，
    代表這些人在新會期都能再領一次，不會被誤判為已領而觸發 cascade 順延。
    """
    prior_period_winners = [
        {"賽事日期": "2025-08-23", "球員姓名": "劉韋廷", "所獲獎項": "總桿冠、淨桿冠"},
        {"賽事日期": "2025-10-18", "球員姓名": "陳翊彥", "所獲獎項": "總桿冠"},
        {"賽事日期": "2026-01-10", "球員姓名": "王建亞", "所獲獎項": "總桿冠"},
        {"賽事日期": "2026-03-29", "球員姓名": "陳奕仲", "所獲獎項": "幸運獎、總桿冠"},
        {"賽事日期": "2026-05-22", "球員姓名": "楊嘉一", "所獲獎項": "總桿冠、幸運獎"},
        {"賽事日期": "2026-07-25", "球員姓名": "林家進", "所獲獎項": "總桿冠、淨桿冠"},
        {"賽事日期": "2026-09-12", "球員姓名": "洪榮杰", "所獲獎項": "近洞獎、總桿冠、淨桿冠"},
    ]
    assert collect_prior_gross_winners(prior_period_winners, rules) == set()


def test_all_published_matches_predate_new_award_period(rules, live_rows):
    """實際成績檔驗證：新會期開賽前，歷史紀錄不該有任何人被記為本會期已領總桿冠。"""
    start, _ = parse_award_period(rules)
    published_in_period = {
        r["球員姓名"] for r in live_rows
        if str(r.get("賽事日期", ""))[:7] >= start
    }
    if not published_in_period:
        assert collect_prior_gross_winners(live_rows, rules) == set()
    else:
        # 新會期已開打：只會收錄本會期內的得主，舊會期紀錄仍不得混入
        for name in collect_prior_gross_winners(live_rows, rules):
            months = [str(r["賽事日期"])[:7] for r in live_rows
                      if r["球員姓名"] == name and "總桿冠" in (r.get("所獲獎項") or "")]
            assert any(m >= start for m in months)


# ------------------ 名冊 ------------------

def test_roster_is_17_members_matching_baseline(rules):
    """2026 新年度名冊共 17 人（原 15 人 + 黃心瀅、林寬宸）。"""
    players = rules["players"]
    assert len(players) == 17
    names = [p["name"] for p in players]
    assert len(set(names)) == 17, "名冊有重複姓名"
    assert set(names) == set(BASELINE_2026)


def test_new_members_start_at_handicap_cap(rules):
    hc = {p["name"]: p["handicap"] for p in rules["players"]}
    cap = rules["handicap"]["max"]
    assert hc["黃心瀅"] == cap
    assert hc["林寬宸"] == cap


def test_handicaps_within_bounds(rules):
    lo, hi = rules["handicap"]["min"], rules["handicap"]["max"]
    for p in rules["players"]:
        assert isinstance(p["handicap"], int), f"{p['name']} 差點非整數"
        assert lo <= p["handicap"] <= hi, f"{p['name']} 差點 {p['handicap']} 超出 {lo}~{hi}"


def test_live_handicaps_track_2026_baseline(rules, live_rows):
    """活檔差點與年度基準的關係，在整個會期內都成立。

    新會期尚未發布任何例賽 → 必須完全等於基準（確認重算值正確寫入）；
    已發布過 → 淨桿前三名的差點被扣減，只會比基準低，不可能更高
    （publish.py 的 delta 一律 <= 0，差點上升只發生在年度重算）。
    """
    hc = {p["name"]: p["handicap"] for p in rules["players"]}
    start, end = parse_award_period(rules)
    published = [r for r in live_rows
                 if start <= str(r.get("賽事日期", ""))[:7] <= end]

    if not published:
        assert hc == BASELINE_2026
    else:
        for name, base in BASELINE_2026.items():
            assert hc[name] <= base, (
                f"{name} 差點 {hc[name]} 高於 2026 年度基準 {base}；"
                "差點只會被例賽扣減，上升代表名冊被誤改或基準未同步更新"
            )
