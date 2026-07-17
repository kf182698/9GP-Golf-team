"""辨識層測試（不呼叫 API）。

用 tests/fixtures 的 input JSON 反推驗證邏輯：fixture 取自實際 iSwing 卡且
標記全數 validation: "pass"，validate() 必須重現相同結果；再以竄改資料
驗證三項檢核各自會抓出錯誤。另涵蓋姓名模糊比對與手寫卡正規化。
"""

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from ocr_parse import (  # noqa: E402
    build_prompt,
    call_vision,
    load_rules,
    match_names,
    normalize_handwritten,
    output_schema,
    validate,
)

FIXTURES = REPO_ROOT / "tests" / "fixtures"


@pytest.fixture(scope="module")
def rules():
    return load_rules(REPO_ROOT / "rules.yaml")


@pytest.fixture()
def card():
    """實際 iSwing 卡的辨識結果（fixture input），11 位球員全數驗證通過。"""
    with open(FIXTURES / "2025-06-21_taoyuan_input.json", encoding="utf-8") as f:
        return json.load(f)


# ------------------ 三重交叉驗證 ------------------

def test_fixture_passes_all_checks(card, rules):
    """反推驗證：實卡資料 11 列應全數 pass，與 fixture 既有標記一致。"""
    result = validate(copy.deepcopy(card), rules)
    assert len(result["players"]) == 11
    assert all(p["validation"] == "pass" for p in result["players"])


def test_nine_sum_mismatch_fails(card, rules):
    """逐洞加總 ≠ 半場總和 → 該列 fail，其他列不受影響。"""
    card["players"][0]["front_9"][0] += 1
    result = validate(card, rules)
    assert result["players"][0]["validation"] == "fail"
    assert all(p["validation"] == "pass" for p in result["players"][1:])


def test_gross_sum_mismatch_fails(card, rules):
    """前九+後九 ≠ 總桿 → fail。（連動 nine_sum 也會抓到，但單獨驗 gross）"""
    card["players"][1]["gross"] += 2
    result = validate(card, rules)
    assert result["players"][1]["validation"] == "fail"


def test_vs_par_mismatch_fails(card, rules):
    """總桿 − 球場 par ≠ +N 欄 → fail。桃園 par 73 ≠ 差點基準 72。"""
    card["players"][2]["vs_par"] += 1
    result = validate(card, rules)
    assert result["players"][2]["validation"] == "fail"


def test_null_hole_fails_validation(card, rules):
    """無法判讀的格子為 null → 驗證不可能通過，列標 fail 供人工補正。"""
    card["players"][3]["front_9"][4] = None
    result = validate(card, rules)
    assert result["players"][3]["validation"] == "fail"


# ------------------ 姓名模糊比對 ------------------

def test_exact_member_name(rules):
    parsed = {"players": [{"name": "王建亞"}]}
    result = match_names(parsed, rules)
    assert result["players"][0]["is_guest"] is False


def test_fuzzy_member_name_normalized(rules):
    """OCR 誤辨一字仍應比對回名冊姓名，並保留原始字串供校對。"""
    parsed = {"players": [{"name": "王建亚"}]}  # 簡體「亚」的常見誤辨
    result = match_names(parsed, rules)
    p = result["players"][0]
    assert p["name"] == "王建亞"
    assert p["ocr_name"] == "王建亚"
    assert p["is_guest"] is False


def test_unknown_name_marked_guest(rules):
    """名冊外姓名（如 fixture 的來賓陳紫晴）→ is_guest: true。"""
    parsed = {"players": [{"name": "陳紫晴"}]}
    result = match_names(parsed, rules)
    assert result["players"][0]["is_guest"] is True


# ------------------ 手寫卡正規化 ------------------

def test_handwritten_normalization():
    cells = [{"value": 5, "confidence": 0.95}] * 8 + [{"value": 4, "confidence": 0.5}]
    back = [{"value": None, "confidence": 0.0}] + [{"value": 5, "confidence": 0.9}] * 8
    parsed = {"players": [{"name": "測試", "front_9": cells, "back_9": back}]}
    result = normalize_handwritten(parsed)
    p = result["players"][0]
    assert p["front_9"] == [5] * 8 + [4]
    assert p["front_9_confidence"][-1] == 0.5
    assert p["back_9"][0] is None
    assert p["low_confidence_holes"] == [9]   # 第 9 洞信心 0.5 → 標黃
    assert p["unreadable_holes"] == [10]      # 第 10 洞 null → 標紅


# ------------------ prompt 與 schema ------------------

def test_prompt_contains_roster_and_no_guess_rule(rules):
    for card_type in ("iswing", "handwritten"):
        prompt = build_prompt(card_type, rules)
        assert "王建亞" in prompt            # 名冊帶入
        assert "嚴禁推測" in prompt          # 不可產生看似正確的錯誤資料
        assert "HANDICAP" in prompt          # 手算欄不辨識
    assert "confidence" in build_prompt("handwritten", rules)
    assert "三重交叉驗證" in build_prompt("iswing", rules)


def test_output_schema_shapes():
    iswing = output_schema("iswing")
    hand = output_schema("handwritten")
    iswing_cell = iswing["properties"]["players"]["items"]["properties"]["front_9"]["items"]
    hand_cell = hand["properties"]["players"]["items"]["properties"]["front_9"]["items"]
    assert iswing_cell == {"type": ["integer", "null"]}
    assert set(hand_cell["required"]) == {"value", "confidence"}


def test_call_vision_requires_api_key(monkeypatch, rules):
    """API key 只從環境變數讀取；未設定時應明確報錯而非默默失敗。"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        call_vision(["nonexistent.jpg"], "iswing", rules)
