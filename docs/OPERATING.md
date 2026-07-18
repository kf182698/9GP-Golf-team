# 9GP 成績系統 — 操作與本地檢視指南

本檔說明三件事：**（A）完全本地、免 API 免 PAT 的手 key 檢視**（用來檢查系統、
找還要修的地方）、**（B）OCR 本地測試與換 provider**、**（C）正式上線 checklist**。

---

## A. 本地手 key 檢視（不需要任何金鑰）

目的：在自己電腦把整套流程跑一遍——手 key 一場成績 → 看引擎算出的排名/獎項/
差點——完全離線，用來檢視 UI 與計分邏輯還有哪裡要改。

```bash
# 1. 在 repo 根目錄開本地靜態站
python3 -m http.server 8000

# 2. 手機或電腦瀏覽器開（同一區網路可用電腦 IP 取代 localhost）
#    總幹事登錄頁： http://localhost:8000/admin.html
#    對外查詢頁：   http://localhost:8000/index.html
```

在 `admin.html`：①選日期/球場 → ②勾出賽會員（＋來賓）→ ③單人逐洞大鍵盤
key 完 → ④總表檢查 → ⑤按 **「下載 JSON」**（這步不需要 PAT）。

把下載的 `<日期>_confirmed.json` 餵給引擎，看完整計分結果（不寫任何檔）：

```bash
python3 scripts/publish.py --rules rules.yaml \
    --input ~/Downloads/2025-06-21_confirmed.json \
    --scores golf_scores.json --dry-run
```

`--dry-run` 只印排名、獎項、差點調整，不動 `golf_scores.json` / `rules.yaml`。
確認邏輯無誤後，正式發布再拿掉 `--dry-run`（或走 admin 一鍵發布）。

> 想直接用現成資料試跑，可用測試 fixture 當作「下載的確認稿」：
> `python3 scripts/publish.py --rules rules.yaml \`
> `  --input tests/fixtures/2025-06-21_taoyuan_input.json \`
> `  --scores golf_scores.json --dry-run`

離線自動化測試（不需金鑰、不需瀏覽器）：

```bash
pip install -r requirements-dev.txt   # 首次
python3 -m pytest tests/ -v           # 規則引擎 + 發布 + 辨識後處理
```

---

## B. OCR 本地測試與換 provider

辨識層 `scripts/ocr_parse.py` 支援三家（`--provider`，預設 anthropic）。
後處理（三重驗證、姓名比對、色碼）三家共用，只有 API 呼叫不同。

```bash
# Anthropic（預設，先做這家）
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python3 scripts/ocr_parse.py --rules rules.yaml \
    --image scorecards/2025-06-21/card1.jpg \
    --card-type iswing --provider anthropic \
    --out pending/2025-06-21_draft.json

# 同一張照片換 OpenAI / Gemini 比對（先裝 SDK、設對應金鑰）
pip install openai        # export OPENAI_API_KEY=...
pip install google-genai  # export GEMINI_API_KEY=...
python3 scripts/ocr_parse.py --rules rules.yaml --image <同一張> \
    --card-type iswing --provider openai   --out /tmp/openai_draft.json
python3 scripts/ocr_parse.py --rules rules.yaml --image <同一張> \
    --card-type iswing --provider gemini   --out /tmp/gemini_draft.json
```

三家草稿都會跑三重交叉驗證並逐列標 `validation: pass/fail`，可直接客觀比較
哪家辨識率高、哪家亂猜（`ocr_provider` 欄記錄是哪家產出）。手寫卡改
`--card-type handwritten`，每格會附信心值、無法辨識填 null。

- 模型可用 `--model` 或環境變數 `OCR_MODEL` 覆寫（預設值僅為起點）。
- 金鑰**只從環境變數讀取**，不寫入程式碼；未設定會明確報錯。
- Gemini 目前以 `response_mime_type=json` + prompt 描述 schema（聯集型別與其
  schema 格式不完全相容），實照片測試後可再改用 `response_schema`。

---

## C. 正式上線 checklist（GitHub）

1. **Secrets**（repo → Settings → Secrets and variables → Actions）：
   依要用的 provider 加入對應金鑰 —
   `ANTHROPIC_API_KEY`（預設必備）、需要時再加 `OPENAI_API_KEY` /
   `GEMINI_API_KEY`。金鑰只在 Actions 內使用，不進前端與 repo。
2. **GitHub Pages**：Settings → Pages 設為 **main branch** 部署，
   `score.yml` push 後網頁會自動更新（index.html 讀新的 golf_scores.json）。
3. **PAT**（僅 admin.html 一鍵發布/上傳照片需要）：建立 fine-grained PAT，
   授予此 repo 的 **Contents 讀寫** 與 **Actions 讀寫**，在 admin.html 右上
   ⚙ 貼入（存於手機瀏覽器 localStorage，不進 repo）。無 PAT 時可用
   「下載 JSON」手動走。

上線後日常操作（賽後約 10 分鐘）：admin.html 上傳照片 → 等辨識 → 校對有色格
→ 輸入近洞獎、必要時裁定同分 → 一鍵發布 → 網頁自動更新。
沒有照片時直接手 key 亦可完成整場（OCR 是加速器，非必要條件）。
