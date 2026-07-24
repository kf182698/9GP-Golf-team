#!/usr/bin/env python3
"""9GP Golf Team 計分引擎。

所有計積邏輯（差點、獎項、同分）皆從 rules.yaml 讀取，不 hardcode。
輸入為成績卡 JSON（見 CLAUDE.md「OCR 辨識 schema」），輸出計分結果 JSON：
excluded_guests / net_ranking / awards / handicap_adjustment。

同分且差點亦相同時為阻斷性錯誤（TieBreakBlocked），須由總幹事裁定後重跑。

用法:
    python scripts/scoring.py --rules rules.yaml --input tests/fixtures/xxx_input.json
"""

import argparse
import json
import sys

import yaml


class TieBreakBlocked(Exception):
    """淨桿與差點皆相同，程式不得自行排序，須由總幹事裁定。"""

    def __init__(self, names, net):
        self.names = names
        self.net = net
        super().__init__(
            f"淨桿同分 {net} 且差點相同：{'、'.join(names)}，待總幹事裁定"
        )


def load_rules(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def roster_handicaps(rules):
    """rules.yaml players 名冊 → {姓名: 差點}。"""
    return {p["name"]: p["handicap"] for p in rules.get("players", [])}


def classify_players(input_players, roster):
    """分離會員與來賓。is_guest 標記或不在名冊者一律視為來賓。

    會員缺總桿（gross 為 None）會導致排序/淨桿計算崩潰——明確報錯指出是誰，
    不靜默略過（略過會把人從排名裡默默拿掉，反而藏錯）。未出賽者不應出現在
    match_input，請於發布端以「請假」處理。
    """
    members, guests = [], []
    for p in input_players:
        if p.get("is_guest") or p["name"] not in roster:
            guests.append(p)
        else:
            if p.get("gross") is None:
                raise ValueError(
                    f"會員「{p['name']}」缺少總桿數（gross）；請補齊成績，"
                    "或若未出賽請勿列入 match_input（由發布端標記請假）"
                )
            members.append(p)
    return members, guests


def rank_members(members, roster, tie_break_rules, manual_tie_order=None):
    """依淨桿升冪排名，同分依差點少者優先；差點亦同則阻斷。

    manual_tie_order 為總幹事裁定的姓名順序（前者名次較前）：
    「淨桿與差點皆同」的兩人若皆在列即依此排序，否則仍阻斷
    （程式不得自行排序或隨機決定）。
    回傳 net_ranking 列表（rank/name/gross/handicap/net，必要時附 tie_break 說明）。
    """
    order = list(manual_tie_order or [])

    def order_idx(name):
        return order.index(name) if name in order else len(order)

    rows = []
    for p in members:
        hc = roster[p["name"]]
        rows.append(
            {
                "name": p["name"],
                "gross": p["gross"],
                "handicap": hc,
                "net": p["gross"] - hc,
            }
        )

    rows.sort(key=lambda r: (r["net"], r["handicap"], order_idx(r["name"])))

    # 檢查阻斷性同分：淨桿與差點皆相同且未經總幹事裁定
    for a, b in zip(rows, rows[1:]):
        if a["net"] == b["net"] and a["handicap"] == b["handicap"]:
            if a["name"] in order and b["name"] in order:
                a["manual"] = b["manual"] = True
                continue
            raise TieBreakBlocked([a["name"], b["name"]], a["net"])

    ranking = []
    for i, r in enumerate(rows):
        row = {"rank": i + 1, "name": r["name"], "gross": r["gross"],
               "handicap": r["handicap"], "net": r["net"]}
        # 同分裁決說明（僅供閱讀，不參與比對）
        if r.get("manual"):
            row["tie_break"] = "淨桿與差點皆同，順序由總幹事裁定"
        for other in rows:
            if other is not r and other["net"] == r["net"] and r["handicap"] < other["handicap"]:
                row["tie_break"] = (
                    f"與{other['name']}淨桿同為{r['net']}，差點少者優先"
                )
        ranking.append(row)
    return ranking


def award_config(rules, award_id):
    for a in rules.get("awards", []):
        if a["id"] == award_id:
            return a
    return None


def format_prize(prize):
    """{'type':'cash','amount':500} → 'cash 500'；{'type':'ball','quantity':1} → 'ball x1'。"""
    if prize["type"] == "cash":
        return f"cash {prize['amount']}"
    return f"{prize['type']} x{prize.get('quantity', 1)}"


def compute_gross_champion(members, cfg, prior_winners=None):
    """總桿冠軍：會員最低總桿。年度已領過者依 cascade 設定順延至次低未領者。"""
    prior_winners = prior_winners or set()
    ordered = sorted(members, key=lambda p: p["gross"])
    annual_limit = cfg.get("annual_limit_per_player")
    for p in ordered:
        if annual_limit and p["name"] in prior_winners:
            if cfg.get("on_limit_reached") == "next":
                continue  # 順延次低者（cascade）
        return {
            "winner": p["name"],
            "gross": p["gross"],
            "prize": format_prize(cfg["prize"]),
            "note": "須檢查年度是否已領取，已領則連鎖順延",
        }
    return {"winner": None, "gross": None, "prize": format_prize(cfg["prize"]),
            "note": "所有會員年度皆已領取"}


def compute_lucky_share(ranking, cfg, exclude_champion=True):
    """幸運分享獎：依淨桿冠軍淨桿單雙決定得獎名次（單→1,3,5…；雙→2,4,6…）。

    exclude_champion：rules.yaml「exclusivity.net_and_lucky_share」若非 "both"，
    淨桿冠軍（排名 1）已得淨桿冠獎，即使排名單雙落在幸運分享獎名次內也不重複得獎，
    名次序列本身不變（不遞補），僅排名 1 從得獎名單移除。
    """
    basis = ranking[0]["net"]
    parity = "odd" if basis % 2 == 1 else "even"
    start = 1 if parity == "odd" else 2
    winner_ranks = [r["rank"] for r in ranking if r["rank"] % 2 == start % 2]
    excluded_rank = None
    if exclude_champion and 1 in winner_ranks:
        winner_ranks = [rk for rk in winner_ranks if rk != 1]
        excluded_rank = 1
    winners = [r["name"] for r in ranking if r["rank"] in winner_ranks]
    parity_zh = "單數" if parity == "odd" else "雙數"
    note = (
        f"淨桿冠軍淨桿 {basis} 為{parity_zh} → "
        f"淨桿排名 {','.join(map(str, winner_ranks))} 得獎"
    )
    if excluded_rank:
        note += "（排名 1 已得淨桿冠軍，依規則不重複得幸運分享獎）"
    return {
        "parity_basis": basis,
        "parity": parity,
        "winners": winners,
        "prize_each": cfg["prize"]["amount"],
        "note": note,
    }


def compute_eagle(members, hole_pars, cfg):
    """Eagle 獎：逐洞比對 hole_score <= hole_par - 2，一人多隻重複發放。"""
    winners = []
    for p in members:
        holes = list(p.get("front_9", [])) + list(p.get("back_9", []))
        for hole_idx, (score_, par) in enumerate(zip(holes, hole_pars), start=1):
            if score_ is not None and score_ <= par - 2:
                winners.append(
                    {"name": p["name"], "hole": hole_idx,
                     "score": score_, "par": par,
                     "prize": format_prize(cfg["prize"])}
                )
    note = (
        f"{len(members)} 位會員 x18 洞逐格比對，無任何洞低於該洞 par 2 桿"
        if not winners
        else f"{len(members)} 位會員 x18 洞逐格比對"
    )
    return {"winners": winners, "note": note}


def compute_handicap_adjustment(ranking, rules):
    """例賽後差點調整：淨桿前三名依「調整前」差點區間查表扣減。

    亞、季軍無獎項但仍扣差點；差點 0 者不調整；扣減後不低於 floor。
    """
    adj_rules = rules["handicap_adjustment"]
    applies_to = adj_rules.get("applies_to_ranks", [1, 2, 3])
    floor = adj_rules.get("floor", 0)
    rank_keys = {1: "net_1st", 2: "net_2nd", 3: "net_3rd"}

    result = []
    for row in ranking:
        if row["rank"] not in applies_to:
            continue
        before = row["handicap"]
        # 差點 0 已達下限，取得名次亦不調整
        if before == floor and adj_rules.get("bracket_zero_rule") == "no_adjustment":
            continue
        bracket = None
        for b in adj_rules["brackets"]:
            lo, hi = b["range"]
            if lo <= before <= hi:
                bracket = b
                break
        if bracket is None:
            continue
        delta = bracket.get(rank_keys[row["rank"]], 0)
        after = max(before + delta, floor)
        result.append(
            {
                "name": row["name"],
                "net_rank": row["rank"],
                "before": before,
                "bracket": f"{bracket['range'][0]}~{bracket['range'][1]}",
                "delta": delta,
                "after": after,
            }
        )
    return result


def guest_scores(guests):
    """來賓成績：不列入排名與獎項，但成績仍保留於輸出供查閱。"""
    return [
        {"name": g["name"], "is_guest": True, "gross": g.get("gross")}
        for g in guests
    ]


def score(rules, match_input, prior_gross_winners=None):
    """計算一場例賽的完整結果。

    prior_gross_winners: 本年度已領過總桿冠軍者集合（供 cascade 順延判斷）。
    淨桿與差點皆同分時回傳 needs_manual_resolution 標記並中止獎項計算。
    """
    roster = roster_handicaps(rules)
    members, guests = classify_players(match_input["players"], roster)

    try:
        ranking = rank_members(members, roster, rules.get("tie_break", {}),
                               manual_tie_order=match_input.get("manual_tie_order"))
    except TieBreakBlocked as e:
        # 幸運分享獎依排名單雙發獎，順序未定則得獎名單不定 → 阻斷獎項計算
        return {
            "needs_manual_resolution": True,
            "tie": {"names": e.names, "net": e.net},
            "reason": str(e),
            "excluded_guests": [g["name"] for g in guests],
            "guest_scores": guest_scores(guests),
        }

    net_champ_cfg = award_config(rules, "net_champion")
    gross_champ_cfg = award_config(rules, "gross_champion")
    lucky_cfg = award_config(rules, "lucky_share")
    eagle_cfg = award_config(rules, "eagle")

    champion = ranking[0]
    net_and_lucky_share = rules.get("exclusivity", {}).get("net_and_lucky_share", "exclude")
    awards = {
        "gross_champion": compute_gross_champion(
            members, gross_champ_cfg, prior_gross_winners
        ),
        "net_champion": {
            "winner": champion["name"],
            "net": champion["net"],
            "prize": format_prize(net_champ_cfg["prize"]),
        },
        "lucky_share": compute_lucky_share(
            ranking, lucky_cfg, exclude_champion=(net_and_lucky_share != "both")
        ),
        "eagle": compute_eagle(members, match_input["hole_pars"], eagle_cfg),
        "near_pin": {
            "winner": match_input.get("manual_awards", {}).get("near_pin"),
            "note": "待 admin 手動輸入",
        },
    }

    return {
        "excluded_guests": [g["name"] for g in guests],
        "guest_scores": guest_scores(guests),
        "net_ranking": ranking,
        "awards": awards,
        "handicap_adjustment": compute_handicap_adjustment(ranking, rules),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="9GP 計分引擎")
    parser.add_argument("--rules", required=True, help="rules.yaml 路徑")
    parser.add_argument("--input", required=True, help="成績卡 input JSON 路徑")
    args = parser.parse_args(argv)

    rules = load_rules(args.rules)
    with open(args.input, encoding="utf-8") as f:
        match_input = json.load(f)

    result = score(rules, match_input)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # 同分待裁定時以非零碼結束，供 Actions/腳本判斷不得發布
    return 2 if result.get("needs_manual_resolution") else 0


if __name__ == "__main__":
    sys.exit(main())
