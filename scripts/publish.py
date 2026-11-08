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
    """彙整每人得獎清單 → {姓名: "獎A、獎B"}（依 AWARD_ORDER 固定順序）。

    近洞獎與 Eagle 獎同一人可得多個（每個 par-3 洞各一位、一人多隻 Eagle
    重複發放），得 2 個以上時記為「近洞獎×2」，獎品數量才不會在紀錄中遺失。
    """
    got = {}

    def add(name, award, times=1):
        if name:
            counts = got.setdefault(name, {})
            counts[award] = counts.get(award, 0) + times

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

    def label(award, n):
        return f"{award}×{n}" if n > 1 else award

    return {
        name: "、".join(label(a, counts[a]) for a in AWARD_ORDER if a in counts)
        for name, counts in got.items()
    }


def build_match_rows(result, match_input, rules):
    """引擎輸出 → golf_scores.json 中文列。

    每場寫全名冊列（缺席者標「請假」），來賓成績保留供查閱（名次「來賓」）。
    """
    date = match_input["date"]
    title = match_title(match_input, rules)
    awards_by_name = player_awards(result, match_input)
    roster = {p["name"]: p["handicap"] for p in rules.get("players", [])}

    # 逐洞成績：index.html 只讀 golf_scores.json（唯一資料源），逐洞明細表
    # 需要的資料必須一併寫入成績列，不另開檔案。出賽者寫 18 格與該場每洞 par，
    # 請假者為 None。
    hole_pars = match_input.get("hole_pars")
    holes_by_name = {}
    for p in match_input.get("players", []):
        holes = list(p.get("front_9") or []) + list(p.get("back_9") or [])
        if any(h is not None for h in holes):
            holes_by_name[p["name"]] = holes

    # 下場區域：同一球場可能有三區以上（如新豐 西/東/中），每場實際打哪兩區不固定，
    # 必須隨成績記錄下來，事後才查得到該場 18 洞 par 的來歷。
    nines_played = None
    fn, bn = match_input.get("front_nine_name"), match_input.get("back_nine_name")
    if fn and bn:
        nines_played = f"{fn}／{bn}"

    def row(name, handicap, gross, net, rank):
        holes = holes_by_name.get(name)
        return {
            "賽事日期": date,
            "例賽名稱": title,
            "球員姓名": name,
            "差點": handicap,
            "總桿數": gross,
            "淨桿數": net,
            "名次": rank,
            "所獲獎項": awards_by_name.get(name) or None,
            "逐洞": holes,
            "每洞標準桿": hole_pars if holes else None,
            "下場區域": nines_played if holes else None,
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


# ------------------ 單洞計桿上限（雙柏忌）------------------

def apply_hole_cap(match_input, rules):
    """依 rules.yaml `hole_score_cap` 把超過上限的單洞桿數封頂，並重算前後九、總桿、vs_par。

    只在比賽日期 >= effective_from 時套用（之前的場次維持當時定案）。
    直接修改 match_input，回傳調整明細 [(姓名, 洞號, 原桿數, 封頂後)]。
    """
    cap = rules.get("hole_score_cap") or {}
    if cap.get("max") != "double_par":
        return []
    since = cap.get("effective_from")
    if since and match_input.get("date", "") < str(since):
        return []
    pars = match_input.get("hole_pars") or []
    if len(pars) != 18 or any(not isinstance(p, int) for p in pars):
        return []
    changes = []
    for p in match_input.get("players", []):
        holes = list(p.get("front_9") or []) + list(p.get("back_9") or [])
        if len(holes) != 18:
            continue
        for i, (v, par) in enumerate(zip(holes, pars)):
            if isinstance(v, int) and v > 2 * par:
                changes.append((p["name"], i + 1, v, 2 * par))
                holes[i] = 2 * par
        if any(c[0] == p["name"] for c in changes):
            p["front_9"], p["back_9"] = holes[:9], holes[9:]
            p["front_9_total"], p["back_9_total"] = sum(holes[:9]), sum(holes[9:])
            p["gross"] = sum(holes)
            p["vs_par"] = p["gross"] - sum(pars)
    return changes


# ------------------ rules.yaml 未登錄九洞區 par 補登 ------------------

def pending_nine_pars(match_input, rules):
    """找出本場下場、但 rules.yaml 中 pars 仍為 null（待補）的九洞區。

    回傳 [(球場名稱, 區名, 9 洞 par)]。只補「待補」的區，已登錄的區即使
    確認稿的 par 不同也不覆寫——已登錄值的修正必須由總幹事人工改 rules.yaml。
    """
    course = match_input.get("course", "")
    pars = match_input.get("hole_pars") or []
    if len(pars) != 18:
        return []
    c = next((c for c in rules.get("courses", [])
              if course in [c.get("name")] + list(c.get("aliases", []))), None)
    if not c:
        return []
    out = []
    for name, seg in ((match_input.get("front_nine_name"), pars[:9]),
                      (match_input.get("back_nine_name"), pars[9:])):
        nine = next((n for n in c.get("nines", []) if n.get("name") == name), None)
        if nine is not None and nine.get("pars") is None:
            if any(not isinstance(p, int) for p in seg):
                raise RuntimeError(f"{c['name']}「{name}」區 par 不完整，無法補登：{seg}")
            out.append((c["name"], name, list(seg)))
    return out


def fill_nine_pars_in_rules(rules_path, fills):
    """把待補區的 `pars: null, total: null` 逐行替換為實際值，保留檔內註解。

    只在該球場區塊內（`name: "<球場>"` 到下一個 `- id:` 之間）找唯一一行，
    找不到或不唯一即中止，避免誤改其他球場同名的區。
    """
    if not fills:
        return []
    with open(rules_path, encoding="utf-8") as f:
        text = f.read()
    for course, zone, pars in fills:
        start = text.find(f'name: "{course}"')
        if start < 0:
            raise RuntimeError(f"rules.yaml 找不到球場「{course}」，補登中止")
        nxt = text.find("\n  - id:", start)
        end = nxt if nxt >= 0 else len(text)
        block = text[start:end]
        pattern = re.compile(
            r'^(\s*-\s*\{\s*name:\s*"' + re.escape(zone)
            + r'"\s*,\s*)pars:\s*null\s*,\s*total:\s*null(\s*\})',
            re.MULTILINE,
        )
        new_block, n = pattern.subn(
            lambda m: f"{m.group(1)}pars: [{','.join(map(str, pars))}], total: {sum(pars)}{m.group(2)}",
            block)
        if n != 1:
            raise RuntimeError(f"rules.yaml「{course}」找不到唯一的待補「{zone}」區行（匹配 {n} 次），補登中止")
        text = text[:start] + new_block + text[end:]
    with open(rules_path, "w", encoding="utf-8") as f:
        f.write(text)
    return fills


# ------------------ 主流程 ------------------

def publish(rules_path, input_path, scores_path, dry_run=False):
    """回傳 (exit_code, summary_text)。exit 2 = 同分待裁定，未寫任何檔案。"""
    rules = load_rules(rules_path)
    with open(input_path, encoding="utf-8") as f:
        match_input = json.load(f)
    with open(scores_path, encoding="utf-8") as f:
        scores_rows = json.load(f)

    capped = apply_hole_cap(match_input, rules)   # 先封頂再計分，總桿與排名都以封頂後為準
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

    lines = [f"## {match_title(match_input, rules)} 發布結果", ""]
    if capped:
        lines.append("### 單洞上限封頂（雙柏忌）")
        for name, hole, before, after in capped:
            lines.append(f"- {name} 第 {hole} 洞 {before} → {after} 桿")
        lines.append("")
    lines.append("### 淨桿排名")
    for r in result["net_ranking"]:
        award = next((row["所獲獎項"] for row in new_rows
                      if row["球員姓名"] == r["name"]), None)
        lines.append(f"{r['rank']}. {r['name']} 總桿 {r['gross']} 差點 {r['handicap']} 淨桿 {r['net']}"
                     + (f"　🏆 {award}" if award else ""))
    if result.get("excluded_guests"):
        lines.append(f"\n來賓（不列入排名）：{'、'.join(result['excluded_guests'])}")
    fills = pending_nine_pars(match_input, rules)
    if fills:
        lines.append("\n### 球場分區補登")
        for course, zone, pars in fills:
            lines.append(f"- {course}「{zone}」區首次下場，par 補登為 {','.join(map(str, pars))}（{sum(pars)}）")
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
    fill_nine_pars_in_rules(rules_path, fills)
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
