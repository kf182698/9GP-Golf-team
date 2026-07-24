#!/usr/bin/env python3
"""9GP Golf Team 成績發布橋接。

把總幹事確認後的單場成績（scoring 引擎 input 格式）跑過 scoring.py，
再轉成 golf_scores.json 的中文列格式寫入，並把差點扣減寫回 rules.yaml。

引擎本身不讀寫檔案；所有檔案 I/O 與格式轉換都在這裡：

    確認稿 JSON ──> scoring.score() ──> golf_scores.json（唯一資料源）
                        │
                        └──> rules.yaml players 差點（逐行正則替換，保留註解）

同分僵局（needs_manual_resolution）→ exit 2，不寫任何檔案，
供 score.yml 判斷不得發布。

用法:
    python scripts/publish.py --rules rules.yaml \\
        --input pending/2025-06-21_confirmed.json \\
        --scores golf_scores.json [--dry-run]
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scoring import load_rules, score  # noqa: E402

# 獎項欄固定順序（display only，程式不得依賴其內容做邏輯判斷）
AWARD_ORDER = ["近洞獎", "總桿冠", "淨桿冠", "幸運獎", "Eagle獎"]


# ------------------ 會期內總桿冠軍彙整 ------------------

def parse_award_period(rules):
    """解析 meta.award_period（"YYYY-MM ~ YYYY-MM"）→ (起, 迄) 年月字串。"""
    period = rules.get("meta", {}).get("award_period", "")
    m = re.match(r"\s*(\d{4}-\d{2})\s*~\s*(\d{4}-\d{2})\s*$", period)
    if not m:
        raise ValueError(f"rules.yaml meta.award_period 格式無法解析: {period!r}")
    return m.group(1), m.group(2)


def collect_prior_gross_winners(scores_rows, rules):
    """從歷史成績彙整本會期內已領過總桿冠軍者（供 cascade 順延）。"""
    start, end = parse_award_period(rules)
    winners = set()
    for row in scores_rows:
        month = str(row.get("賽事日期", ""))[:7]
        award = row.get("所獲獎項") or ""
        if start <= month <= end and "總桿冠" in award:
            winners.add(row["球員姓名"])
    return winners


# ------------------ 中文列格式轉換 ------------------

def match_title(match_input, rules):
    """例賽名稱：YYYY年MM月例賽（短名）。短名取該球場 aliases 最短者。"""
    date = match_input["date"]
    year, month = date[:4], date[5:7]
    course = match_input.get("course", "")
    short = course
    for c in rules.get("courses", []):
        names = [c.get("name", "")] + list(c.get("aliases", []))
        if course in names:
            short = min([n for n in names if n], key=len)
            break
    return f"{year}年{month}月例賽（{short}）"


def player_awards(result, match_input):
    """彙整每人得獎清單 → {姓名: "獎A、獎B"}（依 AWARD_ORDER 固定順序）。"""
    got = {}

    def add(name, award):
        if name:
            got.setdefault(name, set()).add(award)

    awards = result.get("awards", {})
    near_pin = (match_input.get("manual_awards") or {}).get("near_pin")
    for name in ([near_pin] if isinstance(near_pin, str) else (near_pin or [])):
        add(name, "近洞獎")
    add(awards.get("gross_champion", {}).get("winner"), "總桿冠")
    add(awards.get("net_champion", {}).get("winner"), "淨桿冠")
    for name in awards.get("lucky_share", {}).get("winners", []):
        add(name, "幸運獎")
    for e in awards.get("eagle", {}).get("winners", []):
        add(e.get("name"), "Eagle獎")

    return {
        name: "、".join(a for a in AWARD_ORDER if a in items)
        for name, items in got.items()
    }


def build_match_rows(result, match_input, rules):
    """引擎輸出 → golf_scores.json 中文列。

    每場寫全名冊列（缺席者標「請假」），來賓成績保留供查閱（名次「來賓」）。
    """
    date = match_input["date"]
    title = match_title(match_input, rules)
    awards_by_name = player_awards(result, match_input)
    roster = {p["name"]: p["handicap"] for p in rules.get("players", [])}

    def row(name, handicap, gross, net, rank):
        return {
            "賽事日期": date,
            "例賽名稱": title,
            "球員姓名": name,
            "差點": handicap,
            "總桿數": gross,
            "淨桿數": net,
            "名次": rank,
            "所獲獎項": awards_by_name.get(name) or None,
        }

    rows = []
    played = set()
    for r in result["net_ranking"]:
        played.add(r["name"])
        rows.append(row(r["name"], r["handicap"], r["gross"], r["net"], r["rank"]))
    for g in result.get("guest_scores", []):
        played.add(g["name"])
        rows.append(row(g["name"], None, g.get("gross"), None, "來賓"))
    for name, handicap in roster.items():
        if name not in played:
            rows.append(row(name, handicap, None, None, "請假"))
    return rows


def merge_scores(scores_rows, new_rows, date):
    """同日期賽事整批替換（重跑冪等），其餘保留，最後依日期排序。"""
    kept = [r for r in scores_rows if r.get("賽事日期") != date]
    merged = kept + new_rows
    merged.sort(key=lambda r: str(r.get("賽事日期", "")))
    return merged


# ------------------ rules.yaml 差點寫回 ------------------

def apply_handicap_to_rules(rules_path, adjustments):
    """把差點扣減逐行正則替換寫回 players 區塊，完整保留檔內註解。

    禁止 yaml.dump 整檔重寫——rules.yaml 是總幹事維護的設定檔，
    註解與排版必須原樣保留。回傳實際變更的 (姓名, before, after) 列表。
    """
    with open(rules_path, encoding="utf-8") as f:
        text = f.read()

    changed = []
    for adj in adjustments:
        if adj["delta"] == 0:
            continue
        name, after = adj["name"], adj["after"]
        pattern = re.compile(
            r'^(\s*-\s*\{\s*name:\s*"' + re.escape(name)
            + r'"\s*,\s*handicap:\s*)(\d+(?:\.\d+)?)(\s*\})',
            re.MULTILINE,
        )
        new_text, n = pattern.subn(lambda m: f"{m.group(1)}{after}{m.group(3)}", text)
        if n != 1:
            raise RuntimeError(
                f"rules.yaml players 區塊找不到唯一的「{name}」行（匹配 {n} 次），"
                "差點寫回中止以免誤改"
            )
        text = new_text
        changed.append((name, adj["before"], after))

    with open(rules_path, "w", encoding="utf-8") as f:
        f.write(text)
    return changed


# ------------------ 主流程 ------------------

def publish(rules_path, input_path, scores_path, dry_run=False):
    """回傳 (exit_code, summary_text)。exit 2 = 同分待裁定，未寫任何檔案。"""
    rules = load_rules(rules_path)
    with open(input_path, encoding="utf-8") as f:
        match_input = json.load(f)
    with open(scores_path, encoding="utf-8") as f:
        scores_rows = json.load(f)

    prior = collect_prior_gross_winners(scores_rows, rules)
    result = score(rules, match_input, prior_gross_winners=prior)

    if result.get("needs_manual_resolution"):
        tie = result.get("tie", {})
        lines = [
            "## ⚠ 同分待總幹事裁定，成績未發布",
            f"- 淨桿同為 {tie.get('net')}：{'、'.join(tie.get('names', []))}",
            f"- 原因：{result.get('reason', '')}",
            "- 請於 admin 頁面裁定順序後重新發布。",
        ]
        return 2, "\n".join(lines)

    new_rows = build_match_rows(result, match_input, rules)
    merged = merge_scores(scores_rows, new_rows, match_input["date"])
    adjustments = result.get("handicap_adjustment", [])

    lines = [f"## {match_title(match_input, rules)} 發布結果", "", "### 淨桿排名"]
    for r in result["net_ranking"]:
        award = next((row["所獲獎項"] for row in new_rows
                      if row["球員姓名"] == r["name"]), None)
        lines.append(f"{r['rank']}. {r['name']} 總桿 {r['gross']} 差點 {r['handicap']} 淨桿 {r['net']}"
                     + (f"　🏆 {award}" if award else ""))
    if result.get("excluded_guests"):
        lines.append(f"\n來賓（不列入排名）：{'、'.join(result['excluded_guests'])}")
    lines.append("\n### 差點調整")
    for adj in adjustments:
        lines.append(f"- {adj['name']}：{adj['before']} → {adj['after']}"
                     f"（淨桿第 {adj['net_rank']} 名，{adj['delta']:+d}）")

    if dry_run:
        lines.insert(0, "（dry-run，未寫入任何檔案）")
        return 0, "\n".join(lines)

    with open(scores_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
        f.write("\n")
    apply_handicap_to_rules(rules_path, adjustments)
    return 0, "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="9GP 成績發布")
    parser.add_argument("--rules", required=True)
    parser.add_argument("--input", required=True, help="確認稿 JSON（引擎 input 格式）")
    parser.add_argument("--scores", required=True, help="golf_scores.json 路徑")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    code, summary = publish(args.rules, args.input, args.scores, dry_run=args.dry_run)
    print(summary)
    return code


if __name__ == "__main__":
    sys.exit(main())
