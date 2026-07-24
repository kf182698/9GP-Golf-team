# /scorecard — OCR 辨識成績卡

> 將成績卡照片送往 Claude Vision 進行辨識，產生待校對的初稿 JSON

## 用途

總幹事上傳 iSwing 或手寫成績卡照片，本命令自動調用 Claude Vision 辨識逐洞桿數、
球員姓名、驗證欄位，產出 `pending/<date>_draft.json` 供 admin.html 載入和校對。

## 語法

```bash
/scorecard <image_paths...> [選項]
```

### 位置參數
- `image_paths` ：一個或多個成績卡照片路徑（支援 jpg/png 等）

### 選項
- `--card-type iswing|handwritten` ：成績卡類型，預設 `iswing`
  - `iswing` ：機器列印（高辨識率）
  - `handwritten` ：手寫（含信心值、低信心標黃、無法辨識標紅）
- `--provider anthropic|openai|gemini` ：Vision API 提供商，預設 `anthropic`
  - 讀取環境變數 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY`
- `--model <model_id>` ：覆寫預設模型（anthropic 預設 claude-opus-4-8 等）
- `--rules <path>` ：rules.yaml 路徑，預設為 repo 根目錄 `rules.yaml`

## 輸出

呼叫 `ocr_parse.scorecard_ocr()` 並寫入：

- **主檔案**：`pending/<date>_draft.json`（待校對初稿，含 OCR metadata）
  ```json
  {
    "date": "2025-06-21",
    "course": "桃園高爾夫俱樂部",
    "hole_pars": [4,3,5,...],
    "players": [
      {
        "name": "王建亞",
        "ocr_name": "王建亚",  // 原始辨識字串
        "name_match": "uncertain",  // "exact"|"uncertain"|"unmatched"
        "name_candidates": ["王建亞 95%", "王建一 80%", "新增來賓：王建亚"],
        "is_guest": false,
        "front_9": [...],
        "back_9": [...],
        "validation": "pass"
      }
    ]
  }
  ```

- **校對提示**：Console 輸出摘要
  - 通過驗證的列數 vs 需校對的列數
  - 低信心欄位（handwritten 卡）
  - 無法辨識的欄位

## 流程

**辨識只透過本命令（Claude Code）進行，不再有 GitHub Actions 觸發辨識的路徑。**

1. 總幹事於本機執行本命令上傳照片：`/scorecard <照片> --card-type iswing`
2. 產出的 `pending/<date>_draft.json`（手寫卡辨識不出日期時檔名為
   `pending/unknown-<timestamp>_draft.json`）commit + push 到 GitHub main
3. admin.html 步驟①「辨識草稿」區塊會列出 `pending/` 目錄下所有草稿檔案供選擇——
   **不依賴檔名或草稿內容的日期比對**，因為手寫卡常連日期都辨識不出來
4. 總幹事從清單挑選正確的草稿檔案，點「載入所選草稿」；
   `applyDraft()` 填入空格、顯示名字候選、標出低信心格，**但不會覆寫比賽日期**——
   比賽日期一律以步驟①上方欄位為準，須由總幹事自行選定/確認
5. 總幹事校對並手動修正，然後發布確認稿

## 設計原則

- **手動輸入是基礎能力**：無草稿或辨識失敗時，admin.html 仍能獨立完成手 key
- **OCR 純預填**：任何格子總幹事都能覆寫，草稿無效不影響作業
- **名字候選排序**（handwritten 卡）：
  1. 草稿提供的 name_candidates 列表（按相似度降序）
  2. 規則檔名冊中其他會員（可能是 OCR 誤讀）
  3. "新增來賓：<原始名字>"
- **低信心與無法辨識**（handwritten 卡）：
  - 黃格（信心 < 0.8）：為結果，但標記待校對
  - 紅格（null）：無法辨識，必須手補
  - 綠格（信心 ≥ 0.8）：高信心，通常無需改
- **驗證同步**：該列逐洞、半場或總桿計算異常 → 該列紅底待校對

## 參考

- `scripts/ocr_parse.py::scorecard_ocr()` ：實現函數
- `admin.html::refreshDraftList()` ：列出 pending/ 草稿清單供選擇
- `admin.html::applyDraft()` ：校對載入與名字候選（不覆寫比賽日期）
