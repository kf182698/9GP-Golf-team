#!/usr/bin/env python3
"""9GP Golf Team 成績卡辨識層。

呼叫 Claude Vision 將成績卡照片辨識為 CLAUDE.md 定義的 OCR schema JSON，
輸出草稿到 pending/ 供總幹事在 admin 頁面校對。

兩種卡並存：
- iswing      : iSwing 機器列印卡，三重交叉驗證（nine_sum / gross_sum / vs_par）
- handwritten : 手寫卡，每格附 confidence (0~1)；無法判讀填 null，嚴禁推測

支援三家 Vision provider（--provider，預設 anthropic）：後處理（正規化、
姓名比對、三重驗證）三家共用，只有 API 呼叫層不同。schema 由三家各自的
結構化輸出機制強制。API key 一律只從對應環境變數讀取，不寫入程式碼。

用法:
    export ANTHROPIC_API_KEY=sk-ant-...
    python scripts/ocr_parse.py --rules rules.yaml \\
        --image scorecards/2025-06-21/card1.jpg \\
        --card-type iswing --provider anthropic \\
        --out pending/2025-06-21_draft.json

    # 換 provider 比對（先設對應金鑰、裝對應 SDK）：
    #   openai : pip install openai      ; export OPENAI_API_KEY=...
    #   gemini : pip install google-genai; export GEMINI_API_KEY=...
"""

import argparse
import base64
import difflib
import json
import mimetypes
import os
import sys

import yaml

# provider 註冊表：金鑰環境變數 + 預設模型（可用 --model 或 OCR_MODEL 覆寫）。
# 預設模型僅為起點，實照片測試後可依辨識率調整。
PROVIDERS = {
    "anthropic": {"key_env": "ANTHROPIC_API_KEY", "default_model": "claude-opus-4-8"},
    "openai":    {"key_env": "OPENAI_API_KEY",    "default_model": "gpt-4o"},
    "gemini":    {"key_env": "GEMINI_API_KEY",    "default_model": "gemini-1.5-pro"},
}
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = PROVIDERS[DEFAULT_PROVIDER]["default_model"]  # 相容既有引用
# 手寫卡低信心門檻：低於此值的格子在校對頁面標黃
LOW_CONFIDENCE_THRESHOLD = 0.8
# 姓名模糊比對門檻（difflib ratio）
NAME_MATCH_CUTOFF = 0.6


# ------------------ rules.yaml 讀取 ------------------

def load_rules(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def roster_names(rules):
    return [p["name"] for p in rules.get("players", [])]


# ------------------ 輸出 schema（structured outputs）------------------

def hole_cell_schema(card_type):
    """單一洞格的 schema。手寫卡每格附信心值；無法判讀 value 為 null。"""
    if card_type == "handwritten":
        return {
            "type": "object",
            "properties": {
                "value": {"type": ["integer", "null"]},
                "confidence": {"type": "number"},
            },
            "required": ["value", "confidence"],
            "additionalProperties": False,
        }
    return {"type": ["integer", "null"]}


def output_schema(card_type):
    """CLAUDE.md「OCR 辨識 schema」的 JSON Schema 版本，交給 API 強制輸出格式。"""
    nine = {"type": "array", "items": hole_cell_schema(card_type)}
    player = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "front_9": nine,
            "back_9": nine,
            "front_9_total": {"type": ["integer", "null"]},
            "back_9_total": {"type": ["integer", "null"]},
            "gross": {"type": ["integer", "null"]},
            "vs_par": {"type": ["integer", "null"]},
        },
        "required": ["name", "front_9", "back_9", "front_9_total",
                     "back_9_total", "gross", "vs_par"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "date": {"type": ["string", "null"]},
            "course": {"type": ["string", "null"]},
            "course_par": {"type": ["integer", "null"]},
            "front_nine_name": {"type": ["string", "null"]},
            "back_nine_name": {"type": ["string", "null"]},
            "hole_pars": {"type": "array", "items": {"type": ["integer", "null"]}},
            "players": {"type": "array", "items": player},
        },
        "required": ["date", "course", "course_par", "front_nine_name",
                     "back_nine_name", "hole_pars", "players"],
        "additionalProperties": False,
    }


# ------------------ 辨識 prompt ------------------

def build_prompt(card_type, rules):
    """組出 Vision 辨識指示。名冊與球場資料帶入以輔助比對與預設值。"""
    names = "、".join(roster_names(rules))
    courses = []
    for c in rules.get("courses", []):
        nines = "；".join(
            f"{n['name']}: {','.join(map(str, n['pars']))}" for n in c.get("nines", [])
        )
        courses.append(f"- {c['name']}（par {c.get('par_total')}）：{nines}")
    courses_txt = "\n".join(courses) if courses else "（尚無登錄球場）"

    common = f"""你是高爾夫成績卡辨識引擎。請將照片中的成績卡辨識為 JSON。

球隊會員名冊（辨識姓名時對照使用，卡上可能出現名冊外的來賓）：
{names}

已登錄球場每洞標準桿（供對照驗證）：
{courses_txt}

辨識規則：
1. 逐洞桿數：前九 front_9 與後九 back_9 各 9 格，依洞序排列。
2. 表頭：日期(date, YYYY-MM-DD)、球場(course)、球場實際標準桿(course_par)、
   前後九區域名稱(front_nine_name / back_nine_name)、每洞標準桿(hole_pars, 18 格)。
3. 卡上的 HANDICAP / NET SCORE 欄位一律不辨識、不採用——差點與淨桿由計分引擎重算。
4. 任何無法判讀的格子一律填 null。嚴禁推測數字——
   寧可留空讓人補，不可產生看似正確的錯誤資料。
"""

    if card_type == "handwritten":
        return common + """
此為【手寫成績卡】（鉛筆字，可能有遮蔽、對摺變形、字跡淡、塗改）：
5. 每一格逐洞桿數輸出 {"value": 數字或 null, "confidence": 0~1}。
   confidence 表示你對該格判讀的把握；被遮蔽、模糊、塗改過的格子給低值。
6. 完全無法判讀時 value 填 null、confidence 填 0。
7. 半場總和/總桿若卡上有手寫值就照抄（供交叉驗證），沒有或看不清填 null。
"""
    return common + """
此為【iSwing 機器列印卡】，字體清晰：
5. 逐洞桿數直接輸出整數。
6. 照抄卡上的半場總和(front_9_total / back_9_total)、總桿(gross)、
   與總桿減標準桿欄(vs_par)——這些用於三重交叉驗證，不要自行計算。
7. 總桿排名欄可能含並列標記（如 T8），不需輸出。
"""


# ------------------ Vision API 呼叫 ------------------

def encode_image(path):
    """讀圖 → (media_type, raw_bytes)，各 provider 再自行包裝格式。"""
    media_type = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        return media_type, f.read()


def _b64(raw):
    return base64.standard_b64encode(raw).decode("utf-8")


def _require_key(provider):
    env = PROVIDERS[provider]["key_env"]
    if not os.environ.get(env):
        raise RuntimeError(f"缺少 {env} 環境變數（API key 不得寫入程式碼）")


# --- 各 provider 呼叫層：都回傳 schema 相符的 dict（json.loads 後）---

def _call_anthropic(images, prompt, schema, model, client):
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    content = [{"type": "image", "source": {"type": "base64",
               "media_type": mt, "data": _b64(raw)}} for mt, raw in images]
    content.append({"type": "text", "text": prompt})
    with client.messages.stream(
        model=model, max_tokens=64000, thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": content}],
    ) as stream:
        message = stream.get_final_message()
    text = next(b.text for b in message.content if b.type == "text")
    return json.loads(text)


def _call_openai(images, prompt, schema, model):
    from openai import OpenAI
    client = OpenAI()
    content = [{"type": "text", "text": prompt}]
    for mt, raw in images:
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:{mt};base64,{_b64(raw)}"}})
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_schema", "json_schema": {
            "name": "scorecard", "strict": True, "schema": schema}},
    )
    return json.loads(resp.choices[0].message.content)


def _call_gemini(images, prompt, schema, model):
    # google-genai 的 response_schema 與本檔 JSON Schema（含 ["integer","null"]
    # 聯集型別）格式不完全相同，故以 response_mime_type 強制 JSON、schema 由
    # prompt 描述 + 後段三重驗證把關；實照片測試後可再改用 response_schema。
    from google import genai
    from google.genai import types
    client = genai.Client()
    parts = [types.Part.from_bytes(data=raw, mime_type=mt) for mt, raw in images]
    parts.append(types.Part.from_text(text=prompt))
    resp = client.models.generate_content(
        model=model, contents=parts,
        config={"response_mime_type": "application/json"},
    )
    return json.loads(resp.text)


_DISPATCH = {"anthropic": _call_anthropic, "openai": _call_openai,
             "gemini": _call_gemini}


def call_vision(image_paths, card_type, rules, provider=DEFAULT_PROVIDER,
                model=None, client=None):
    """辨識成績卡照片，回傳 schema 相符的 dict。provider 選 anthropic/openai/gemini。"""
    provider = provider or DEFAULT_PROVIDER
    if provider not in PROVIDERS:
        raise ValueError(f"未知 provider: {provider}（可選 {', '.join(PROVIDERS)}）")
    # 注入 client（測試/anthropic）時免金鑰檢查；否則先檢查金鑰再讀圖
    if not (provider == "anthropic" and client is not None):
        _require_key(provider)
    model = model or os.environ.get("OCR_MODEL") or PROVIDERS[provider]["default_model"]
    images = [encode_image(p) for p in image_paths]
    prompt = build_prompt(card_type, rules)
    schema = output_schema(card_type)
    if provider == "anthropic":
        return _call_anthropic(images, prompt, schema, model, client)
    return _DISPATCH[provider](images, prompt, schema, model)


# ------------------ 後處理：手寫卡格式正規化 ------------------

def normalize_handwritten(parsed, threshold=LOW_CONFIDENCE_THRESHOLD):
    """把手寫卡的 {value, confidence} 格拆成桿數陣列 + 信心陣列。

    校對頁面色碼依據：confidence < threshold 標黃、value 為 null 標紅。
    """
    for p in parsed.get("players", []):
        for key in ("front_9", "back_9"):
            cells = p.get(key, [])
            if not any(isinstance(c, dict) for c in cells):
                continue  # 沒有 {value,confidence} 格 → 已是正規化桿數陣列，跳過
            # 逐格安全解析：非 dict（如 null 或已是數字）不讓後續 sum() 崩潰
            values, conf = [], []
            for c in cells:
                if isinstance(c, dict):
                    values.append(c.get("value"))
                    conf.append(c.get("confidence", 0.0))
                else:
                    values.append(c if isinstance(c, int) else None)
                    conf.append(0.0)
            p[key] = values
            p[f"{key}_confidence"] = conf
        conf = p.get("front_9_confidence", []) + p.get("back_9_confidence", [])
        values = list(p.get("front_9", [])) + list(p.get("back_9", []))
        p["low_confidence_holes"] = [
            i + 1 for i, (v, c) in enumerate(zip(values, conf))
            if v is not None and c < threshold
        ]
        p["unreadable_holes"] = [i + 1 for i, v in enumerate(values) if v is None]
    return parsed


# ------------------ 姓名比對 ------------------

def match_names(parsed, rules, cutoff=NAME_MATCH_CUTOFF):
    """以名冊做模糊比對。比對得到者正規化姓名；比對不到者標記 is_guest。"""
    roster = roster_names(rules)
    for p in parsed.get("players", []):
        raw = (p.get("name") or "").strip()
        if raw in roster:
            p["is_guest"] = False
            continue
        candidates = difflib.get_close_matches(raw, roster, n=1, cutoff=cutoff)
        if candidates:
            p["ocr_name"] = raw          # 保留原始辨識字串供校對
            p["name"] = candidates[0]    # 正規化為名冊姓名
            p["is_guest"] = False
        else:
            p["is_guest"] = True         # 章程允許來賓與賽
    return parsed


# ------------------ 三重交叉驗證 ------------------

def _check_nine_sum(p, _parsed):
    for key in ("front_9", "back_9"):
        holes = p.get(key, [])
        total = p.get(f"{key}_total")
        if any(h is None for h in holes) or total is None or len(holes) != 9:
            return False
        if sum(holes) != total:
            return False
    return True


def _check_gross_sum(p, _parsed):
    f, b, g = p.get("front_9_total"), p.get("back_9_total"), p.get("gross")
    if None in (f, b, g):
        return False
    return f + b == g


def _check_vs_par(p, parsed):
    g, par, vs = p.get("gross"), parsed.get("course_par"), p.get("vs_par")
    if None in (g, par, vs):
        return False
    return g - par == vs


_CHECKS = {
    "nine_sum": _check_nine_sum,
    "gross_sum": _check_gross_sum,
    "vs_par": _check_vs_par,
}


def validate(parsed, rules):
    """依 rules.yaml validation.checks 執行交叉檢核，逐列標記 pass/fail。

    驗證不通過（含任何 null 格）的列由校對頁面高亮，總幹事只需檢視紅字。
    """
    check_ids = [c["id"] for c in rules.get("validation", {}).get("checks", [])]
    for p in parsed.get("players", []):
        ok = all(_CHECKS[cid](p, parsed) for cid in check_ids if cid in _CHECKS)
        p["validation"] = "pass" if ok else "fail"
    return parsed


# ------------------ 主流程 ------------------

def parse_scorecard(image_paths, card_type, rules, provider=DEFAULT_PROVIDER,
                    model=None, client=None):
    """照片 → Vision 辨識 → 正規化 → 姓名比對 → 三重驗證 → 草稿 dict。"""
    parsed = call_vision(image_paths, card_type, rules, provider=provider,
                         model=model, client=client)
    if card_type == "handwritten":
        parsed = normalize_handwritten(parsed)
    parsed = match_names(parsed, rules)
    parsed = validate(parsed, rules)
    parsed["source"] = ("iSwing 列印成績卡" if card_type == "iswing"
                        else "手寫成績卡")
    parsed["card_type"] = card_type
    parsed["ocr_provider"] = provider          # 供比對時追溯是哪家辨識的
    parsed.setdefault("manual_awards", {"near_pin": None})  # 近洞獎由 admin 手動輸入
    return parsed


def main(argv=None):
    parser = argparse.ArgumentParser(description="9GP 成績卡辨識")
    parser.add_argument("--rules", required=True, help="rules.yaml 路徑")
    parser.add_argument("--image", required=True, action="append",
                        help="成績卡照片路徑（可重複指定多張）")
    parser.add_argument("--card-type", choices=["iswing", "handwritten"],
                        default="iswing")
    parser.add_argument("--provider", choices=list(PROVIDERS),
                        default=DEFAULT_PROVIDER,
                        help=f"Vision 供應商（預設 {DEFAULT_PROVIDER}）")
    parser.add_argument("--model", default=None,
                        help="覆寫模型（預設依 provider，亦可用環境變數 OCR_MODEL）")
    parser.add_argument("--out", default=None,
                        help="輸出草稿 JSON 路徑（預設 pending/<date>_draft.json）")
    args = parser.parse_args(argv)

    rules = load_rules(args.rules)
    draft = parse_scorecard(args.image, args.card_type, rules,
                            provider=args.provider, model=args.model)

    out = args.out
    if out is None:
        date = draft.get("date") or "unknown-date"
        out = os.path.join("pending", f"{date}_draft.json")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)

    failed = [p["name"] for p in draft.get("players", [])
              if p.get("validation") != "pass"]
    print(f"草稿已寫入 {out}")
    if failed:
        print(f"⚠ 驗證未通過（校對頁面將高亮）：{'、'.join(failed)}")
        return 1
    print("三重交叉驗證全數通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
