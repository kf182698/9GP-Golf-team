# CLAUDE.md — 9GP Golf Team 成績系統

> 本檔為 Claude Code 的專案指引。每次開新 session 會自動讀取，不需重述背景。

## 專案目的

取代總幹事手工登錄成績的流程。目標流程：

```
成績卡拍照 → AI 辨識 → 人工校對 → 自動計分/頒獎 → 發布至 GitHub Pages
```

使用者為球隊總幹事（非全職開發者），系統須「能被一個人在賽後 10 分鐘內完成操作」。

## 系統架構

```
┌─ 本地 Claude Code IDE ──────────────────┐
│ /scorecard <照片> --card-type iswing    │
│   ↓ 呼叫 ocr_parse.scorecard_ocr()      │
│   ↓ 寫入 pending/<date>_draft.json      │
└──────────┬────────────────────┘
           ▼
┌─ PWA（GitHub Pages 上的手機網頁）────────────────┐
│ admin.html :                               │
│ ① 選日期、偵測 draft → 載入預填              │
│ ② 會員下拉 + 名字候選 → 校對確認           │
│ ③ 逐洞輸入（手 key 或 OCR 預填）           │
│ ④ 總表檢視 → ⑤ 手動獎項 + 同分裁定 + 發布 │
│ index.html : 成績與獎項查詢（對外公開唯讀）  │
└──────────┬────────────────────┘
           │ GitHub API（fine-grained PAT，存於瀏覽器 localStorage）
           ▼
┌─ Repo: kf182698/9GP-Golf-team ──────────┐
│ scorecards/      原始照片存檔              │
│ pending/         OCR 辨識草稿 JSON         │
│ golf_scores.json 正式成績（唯一資料源）      │
│ rules.yaml       計積規則（唯一規則來源）     │
└──────────┬────────────────────┘
           │ 觸發 GitHub Actions
           ▼
┌─ Actions（score.yml，金鑰放 GitHub Secrets）──────┐
│ 確認稿 → scoring.py 計分 → 獲獎名單 + 差點調整 →   │
│ golf_scores.json + rules.yaml + GitHub Pages 自動更新 │
└────────────────────────────────────┘
```

## 目錄結構

```
9GP-Golf-team/
├── index.html          # 對外：成績/獎項/差點走勢
├── admin.html          # 總幹事：選日期、校對、手動輸入、一鍵發布
├── manifest.json       # PWA 設定（加到主畫面）
├── golf_scores.json    # 正式成績資料庫
├── rules.yaml          # 計積規則設定檔
├── scorecards/         # 原始照片存檔，依日期分資料夾
├── pending/            # OCR 辨識草稿 JSON
├── scripts/
│   ├── ocr_parse.py    # Claude Vision 辨識成績卡（由 /scorecard 命令呼叫）
│   └── scoring.py      # 計分引擎
├── .claude/
│   └── commands/
│       └── scorecard.md  # /scorecard 命令規格
└── .github/workflows/
    └── score.yml         # 確認稿 → 計分 + 發布
```

## 核心設計原則

1. **rules.yaml 是唯一規則來源。** 任何計積邏輯（差點、獎項、同分）都必須從 yaml 讀取，禁止 hardcode 在 scoring.py 內。規則會改，程式不該跟著改。
2. **golf_scores.json 是唯一資料源。** index.html 只讀這個檔，不查其他來源。
3. **手動輸入是基礎能力，OCR 是加速器。** admin.html 的成績網格必須在「完全沒有 OCR」的情況下也能獨立完成整場成績登錄。OCR 只負責預填格子，任何一格總幹事都能覆寫。系統不得有「OCR 失敗就無法作業」的路徑。
4. **人工確認不可省。** 流程必須是「AI 產草稿 → 人校對 → 才寫入正式成績」。任何跳過校對直接寫入 golf_scores.json 的設計都不接受。
5. **金鑰不進前端。** Claude API key 只存在於 GitHub Secrets、只在 Actions 內使用。

## 計積規則要點（詳見 rules.yaml）

- 淨桿 = 總桿 − 差點；標準桿 72；差點上限 36、下限 0
- **排名以淨桿為準**；同分依 ①差點少 ②年齡大
- **例賽後淨桿前三名扣減差點**，依「調整前」差點區間查表
- **關鍵：差點調整適用淨桿前三名，但獎項只發淨桿冠軍**——亞、季軍無獎但仍扣差點。兩者邏輯必須分離
- 總桿冠軍每人每年限領一次，已領過則**連鎖順延**至次低未領者
- Eagle 獎需逐洞 par（由成績卡 OCR 取得），一人多隻重複發放
- 近洞獎程式無法計算，由 admin 頁面手動輸入
- 年度差點重算由總幹事手算後直接改 rules.yaml，程式不自動執行

## 成績卡：兩種來源並存

球場不一定提供 iSwing，因此**兩種來源都必須支援**：

| 來源 | 特性 | 處理方式 |
|---|---|---|
| **iSwing 列印卡** | 機器印刷、含三重交叉驗證欄位 | OCR 高可靠，驗證全綠即通過 |
| **手寫成績卡** | 鉛筆字、可能遮蔽/彎曲/塗改 | OCR 盡力預填，低信心標黃、無法辨識標紅，總幹事手動補正 |

**設計底線：手寫卡辨識失敗時，總幹事在 admin.html 直接空白手 key 即可完成作業。**
OCR 是選配，手動輸入網格是必備。

### iSwing 卡結構

| 欄位 | 說明 |
|---|---|
| 表頭 | 球隊、球場、比賽人數、總桿數、日期 |
| 區域 | 前後九名稱（例：西 / 東） |
| HOLE / HDCP / PAR | 洞號、該洞難度指數（計分不用）、該洞標準桿 |
| 總和 / 標準桿 / 總桿 / 總桿排名 | 半場小計、球場實際 par（例：桃園=73）、18洞合計、含並列標記(T8) |

**重要**：差點計算一律以 72 為基準（章程明定）；Eagle 判定與 +N 欄用球場實際 par。

### 手寫卡注意事項

- 卡上的 HANDICAP / NET SCORE 欄為會員現場手算，**不辨識、不採用**，一律由 scoring.py 重算，避免人工誤算污染資料
- 只辨識逐洞桿數 + 球員姓名
- 常見障礙：鉛筆遮蔽、手指遮蔽、卡片對摺變形、字跡淡、塗改痕跡

## 球場資料庫

`rules.yaml` 的 `courses` 區塊登錄各球場每洞 par。選定球場後自動帶入，
減少手動輸入量、提供輸入預設值、供 Eagle 判定與驗證使用。新球場第一次打完後補登。

## OCR 辨識流程與 schema

`/scorecard` 命令呼叫 `ocr_parse.scorecard_ocr()` 進行辨識，輸出 `pending/<date>_draft.json`。
Draft schema 如下：

```json
{
  "date": "2025-06-21",
  "course": "桃園高爾夫俱樂部",
  "course_par": 73,
  "front_nine_name": "西",
  "back_nine_name": "東",
  "hole_pars": [4,3,5,4,4,4,5,4,3, 6,4,3,4,4,5,3,4,4],
  "players": [
    {
      "name": "王建亞",
      "ocr_name": "王建亚",
      "name_match": "exact",
      "name_candidates": null,
      "is_guest": false,
      "front_9": [5,4,7,4,5,4,5,5,4],
      "back_9": [6,6,3,5,5,5,4,5,4],
      "front_9_total": 43,
      "back_9_total": 43,
      "gross": 86,
      "vs_par": 13,
      "validation": "pass",
      "low_confidence_holes": null,
      "unreadable_holes": null
    }
  ]
}
```

### Draft 欄位說明

- **name_match**：`"exact"` / `"uncertain"` / `"unmatched"`
  - `exact`：與名冊完全或高度匹配（相似度 > 0.9）
  - `uncertain`：部分匹配（0.6 ≤ 相似度 ≤ 0.9）→ admin.html 提供候選下拉
  - `unmatched`：名冊查無此人 → 標記 is_guest、提供「新增來賓」選項
- **name_candidates**：不確定時提供的候選列表（按相似度排序）
- **validation**：`"pass"` / `"fail"`（三重交叉驗證：逐洞和 = 半場、前後九 = 總桿、總桿 − par = vs_par）
- **low_confidence_holes**（手寫卡）：信心 < 0.8 的洞號列表，前端標黃
- **unreadable_holes**（手寫卡）：無法辨識（null）的洞號列表，前端標紅

### 辨識原則

- 姓名以 rules.yaml 的 players 名冊做模糊比對（cutoff 0.6）；比對不到者標記 `is_guest: true`
- **三重交叉驗證**：逐洞加總 = 半場總和；前九+後九 = 總桿；總桿 − 球場 par = +N 欄
- 驗證不通過的列標記 `validation: "fail"`，校對頁面高亮；通過者綠燈
- **手寫卡額外要求**：每格需附信心值 `confidence` (0~1)；無法判讀者填 `null` 而非猜測。
  嚴禁在遮蔽或字跡不清時推測數字——寧可留空讓人補，不可產生看似正確的錯誤資料。

## admin.html 輸入介面設計要求

手機端 18 洞 × 11 人 = 近 200 格，UX 決定系統可用性：

1. **單人逐洞模式**：一次顯示一位球員的 18 格，大數字鍵盤、輸入後自動跳下一洞
2. **即時驗證**：邊輸入邊算前九/後九小計與總桿，key 錯當場顯示
3. **原圖對照**：畫面上半固定顯示成績卡照片（可縮放平移），下半為輸入格，不需切畫面
4. **草稿自動存**：每格輸入即寫 localStorage，中斷後可續作
5. **預設值**：帶入該洞 par（取自 courses 資料庫），多數洞僅需微調
6. **格子色碼**：綠=驗證通過 / 黃=OCR 低信心 / 紅=無法辨識或驗證失敗，總幹事只需處理有色格
7. **手動獎項欄**：近洞獎得主由此輸入（程式無法計算）

## 開發階段

1. ✅ `scoring.py` + `rules.yaml` — 規則程式化，含測試案例（2026-07-17 完成，見下）
2. ✅ `ocr_parse.py` — 模組化完成（2026-07-21）；由 `/scorecard` 命令呼叫
   - `scorecard_ocr(image_paths, card_type, rules, provider, model)` 函數
   - 不處理 CLI 或檔案 I/O 邏輯（由 /scorecard 命令負責）
   - 支援 iSwing / 手寫兩種卡型；多 provider 可切換
   - 輸出 `pending/<date>_draft.json`；待實卡照片調校至 > 90% 辨識率
3. ✅ `/scorecard` 命令規格（2026-07-21）：.claude/commands/scorecard.md
   - 呼叫 `ocr_parse.scorecard_ocr()` 進行辨識
   - 支援 `--card-type`, `--provider`, `--model`, `--rules` 等選項
4. ✅ admin.html 完整流程（2026-07-21）：步驟①～⑤
   - ① 日期選定 → 自動偵測 `pending/<date>_draft.json`
   - ② 會員下拉 + 名字候選（不確定度排序）→ is_guest 標記
   - ③ 逐洞輸入（OCR 預填或完全手 key 皆可）→ 色碼校對（綠/黃/紅）
   - ④ 總表檢視
   - ⑤ 近洞獎 + 同分裁定 → 人員摘要 + 發布
5. ✅ score.yml workflow —— 確認稿 → 計分 → 獲獎 + 差點調整 → 發布
   - 同分僵局：exit 2 中止、待手動裁定
6. ✅ index.html 升級（2026-07-17）：最新例賽快報 + 差點走勢圖

**系統開發完工**；僅剩實照片調校（見「待補資料」）。

## 階段 4 第四回合實作決定（2026-07-24：草稿清單新增手動刪除）

- **問題**：`score.yml` 發布成功後只會用確認稿的 `date` 去 glob
  `pending/${date}*_draft.json` 清掉「同日期」草稿；`unknown-<timestamp>_draft.json`
  （手寫卡辨識不出日期時的檔名，見上一輪決定）檔名對不上任何實際比賽日期，
  永遠不會被自動清掉。加上重複上傳、校對後放棄的草稿，`pending/` 會隨使用時間
  持續累積。
- **解法**：草稿選取清單旁加「🗑 刪除」按鈕，直接呼叫 GitHub Contents API
  `DELETE /repos/{repo}/contents/{path}`（既有 PAT 已具備 Contents 讀寫權限，
  不需額外授權）。刪除前 `confirm()` 二次確認、刪除只影響 `pending/` 底下的
  草稿檔案，不觸碰 `golf_scores.json`／`rules.yaml`。刪除的 `sha` 取自
  `refreshDraftList()` 抓清單時 GitHub API 回傳的值（放在 `<option data-sha>`）。
- 未做自動清理（例如定期清空舊草稿）：草稿是否該留由總幹事人工判斷
  （例如尚未校對完成的草稿不該被自動清掉），符合「人工確認不可省」原則。

## 階段 4 第三回合實作決定（2026-07-24：草稿選取與日期主權修正）

- **辨識僅透過 Claude Code（`/scorecard`）**：刪除已停用但殘留的
  `.github/workflows/ocr.yml`（v2 架構早已決定移除 Actions 自動觸發辨識，
  但檔案沒清掉；`tests/test_publish.py` 早就寫著「ocr.yml moved to local
  /scorecard command」卻沒人真的刪檔）。辨識流程只剩一條路：總幹事在本機
  跑 `/scorecard`，產物 commit + push 上 GitHub。
- **修正 admin.html「載入辨識草稿」按鈕完全無法點擊的 bug**：
  `renderStep1()` 綁定事件時依序執行到 `$("fCardType").onchange = ...` 與
  `$("fProvider").onchange = ...`，但這兩個輸入框在目前版面早就不存在
  （v1 時代殘留，OCR provider/card-type 選擇已移到 `/scorecard` 指令本身）。
  對 `null` 設定 `.onchange` 會丟例外，導致下一行
  `$("draftBtn").onclick = loadDraft` 永遠執行不到——按鈕從頭到尾沒有綁定
  點擊事件。移除這兩行殘留綁定。
- **草稿載入改為清單選取，不再依日期比對檔名**：原本邏輯是「目前選定的
  比賽日期」去猜 `pending/${日期}_draft.json` 檔名，手寫卡經常連日期都
  辨識不出來（`ocr_parse.py` 會退回 `unknown-<timestamp>_draft.json`），
  這種猜測必然落空。改為 `refreshDraftList()` 直接列出 `pending/` 目錄下
  所有 `*_draft.json` 供總幹事挑選，與目前日期欄位無關。
- **比賽日期主權回到總幹事**：`applyDraft()` 不再用草稿內的 `date` 覆寫
  `S.date`；草稿辨識到的日期只在載入後的提示訊息顯示供參考。日期永遠是
  步驟①欄位裡總幹事自己選定/確認的值，不受 OCR 結果影響。
- `ocr_parse.py::scorecard_ocr()`：辨識不到日期時的檔名從固定字串
  `unknown-date_draft.json` 改成 `unknown-<unix time>_draft.json`，避免
  同一天多張辨識不出日期的草稿互相覆蓋。

## 階段 4 第二回合實作決定（2026-07-21：v2 OCR 架構 + 日常操作閉環）

日常操作四步驟（辨識→校對→獎項/裁定→發布）全部閉環：

- **v2 OCR 架構**：移除 GitHub Actions 自動觸發，改用本地 `/scorecard` 命令
  - 優點：開發迴圈快、無須等待 workflow、易除錯
  - 總幹事執行：`/scorecard <照片> --card-type iswing` 後稍候 1-2 分鐘
  - 產物：`pending/<date>_draft.json`
- **draft 偵測與載入**：
  - 步驟① 選日期時自動檢查 `pending/<date>_draft.json` 是否存在
  - 若存在：顯示提示「偵測到未處理草稿」，點「載入辨識草稿」按鈕預填
  - 載入規則：**只填空格，不覆寫已有輸入**（防止人工輸入被 OCR 覆蓋）
- **名字候選**（不確定度排序）：
  - OCR 辨識不確定時：提供候選列表（按相似度降序）
  - 總幹事從下拉選單選定正確名字（含「新增來賓」選項）
  - 選定後自動標記 is_guest / 清除 OCR metadata
- **色碼校對**（設計要求 6）：
  - 綠=驗證通過、黃=低信心（handwritten 卡）、紅=無法辨識或驗證失敗
  - 人工改值後自動清除該格標記
  - 總表顯示「待校對 n 格」提醒
- **manual_tie_order 契約**（引擎）：match_input 選用欄位
  `manual_tie_order: ["甲","乙"]`。「淨桿與差點皆同」的兩人皆在列才解僵局；
  否則阻斷且不計算獎項。
- **同分裁定介面**：步驟⑤發布前本地預檢
  - 自動找出「淨桿同且差點同」群組
  - 顯示裁定卡（列差點供判斷、依名次順序點選）
  - 總幹事裁定後寫入確認稿 `manual_tie_order`，無需等待 workflow 失敗
- **近洞獎**：步驟⑤會員複選 → `manual_awards.near_pin`
- **人員摘要**：發布前確認 → 會員人數、排名對象、來賓標記

## 階段 4 實作決定（2026-07-21，前端改動：dropdown member + draft merge）

`admin.html` 單檔（無建置流程），實現完全手 key 與 OCR 預填雙軌並行：

- **設定來源**：fetch 同源 `rules.yaml` + js-yaml CDN 解析——名冊與球場
  不 hardcode 於前端。視覺沿用 index.html（Tailwind CDN、primary/accent）。
- **五步驟精靈**：
  - ① 場次：日期 + 球場下拉（自動帶 hole_pars；「其他球場」手動 par、新球場不卡）
    → 自動偵測 `pending/<date>_draft.json` 並顯示載入提示
  - ② 名單：dropdown 選會員 + 新增來賓欄位 + is_guest checkbox
    （原按鈕勾選改為 dropdown + add row/delete row 按鈕）；
    載入 draft 時顯示名字候選（模糊比對不確定 → 提供相似度排序列表 + 新增來賓選項）
  - ③ 逐洞：單人逐洞模式（大鍵盤、單鍵自動跳、前後九即時小計；18 格膠囊可點跳）
  - ④ 總表：紅底=未填，點列回補
  - ⑤ 發布：人員摘要 + 近洞獎 + 同分裁定 + 確認按鈕
- **draft 載入**（merge 規則）：
  - 檢查 player 是否已在 S.players（根據 rules.yaml 名冊比對）
  - 若存在：保留其現有 scores，不覆寫（防止人工輸入遺失）
  - 若不存在：新增 player 並填入 draft 的逐洞與驗證結果
  - 名字不確定 → 填入 nameCandidates 供 ② 步驟展示下拉選單
- **草稿**：每格輸入即寫 localStorage `gp9_draft`；重開頁偵測草稿詢問續作。
- **色碼校對**（draft 且 validation/low_confidence 非空時）：
  - 載入 draft 時標記格子顏色（綠=pass、黃=low_confidence、紅=unreadable/fail）
  - 人工改值即自動清除該格標記
- **發布**：組確認稿 JSON（逐洞/totals/vs_par 自動計算、validation 計算、
  manual_awards.near_pin/manual_tie_order 從 UI 讀取）→
  GitHub Contents API PUT `pending/<date>_confirmed.json` →
  dispatch `score.yml`。PAT 存 localStorage `gp9_pat`（⚙ 設定面板），
  金鑰不進 repo。
- **驗收證據**（Playwright 行動 viewport 端到端）：
  - 手 key 黃金路徑（無 draft）198 格完整填入 → 產出 JSON 吻合 fixture
  - draft 載入 + merge 規則（既存 player 保留 scores）
  - 名字候選與相似度排序、選定後 is_guest 正確
  - 色碼標記與手動改值清標
  - 同分裁定卡 + manual_tie_order 寫入確認稿 → 餵 scoring.py 無阻斷

## 階段 3 實作決定（2026-07-17）

新增 `scripts/publish.py`（發布橋接）+ `.github/workflows/{ocr,score}.yml`。
引擎不讀寫檔案的約定不變；檔案 I/O 全在 publish.py。

- **總桿冠軍年度限領以「章程會期」為準**（總幹事裁定）：
  `publish.py` 解析 `meta.award_period`（`"YYYY-MM ~ YYYY-MM"`），
  彙整區間內 golf_scores.json `所獲獎項` 含「總桿冠」者傳入引擎做 cascade。
  會期換屆時總幹事更新 award_period 即自動重置。
- **差點扣減自動寫回 rules.yaml**（總幹事裁定）：發布成功後
  golf_scores.json + rules.yaml 同一 commit 更新。寫回用**逐行正則替換**
  players 該行 handicap 數字，嚴禁 yaml.dump 整檔重寫（註解必須保留）；
  匹配不到唯一行即中止。delta=0 不動。
- **中文列格式**：每場寫全名冊列。排名會員名次 int；來賓 `名次:"來賓"`
  （總桿保留、差點/淨桿 null）；缺席 `名次:"請假"`（差點=現值）。
  `例賽名稱` = `YYYY年MM月例賽（短名）`，短名取 courses aliases 最短者。
  `所獲獎項` 固定順序 `近洞獎、總桿冠、淨桿冠、幸運獎、Eagle獎` 以「、」串接。
- **冪等**：同日期賽事整批替換後依日期排序，重跑安全。
- **同分僵局**：publish.py exit 2、不寫任何檔案；score.yml 據此 job fail。
- **workflow 觸發**：`score.yml` 採 `workflow_dispatch`（由 admin.html 以 GitHub API
  觸發），發布時自動調用。
  - `score.yml` inputs：`input_path`（確認稿路徑，引擎 input 格式）。
    發布前先跑 pytest 守門；成功後刪除該場確認稿與同日期 `*_draft.json`。
- **待辦**：repo Settings → Secrets 需由總幹事加入 `ANTHROPIC_API_KEY`
  （金鑰用於 `/scorecard` 命令）；Actions 實跑驗證待照片階段一併進行。

## 階段 1 實作決定（2026-07-17）

`scripts/scoring.py` 已完成並通過驗收（11 項 pytest 全綠，fixture 完全吻合）。
後續階段介接時以下列介面為準：

- **入口**：`score(rules, match_input, prior_gross_winners=None)`。
  `prior_gross_winners` 為本年度已領總桿冠軍者集合，供 cascade 順延；
  呼叫端（未來 score.yml）負責從歷史成績彙整後傳入，引擎本身不讀 golf_scores.json。
- **輸出鍵**：`excluded_guests`（姓名列表）、`guest_scores`（來賓成績保留供查閱，
  含 name/is_guest/gross）、`net_ranking`、`awards`、`handicap_adjustment`。
- **同分僵局**：淨桿與差點皆同 → 回傳
  `{needs_manual_resolution: true, tie: {names, net}, reason, ...}`，
  **不含** awards 與 handicap_adjustment（中止獎項計算）。
  CLI 以 **exit code 2** 結束，供 Actions 判斷不得發布；正常為 0。
- **CLI**：`python scripts/scoring.py --rules rules.yaml --input <input.json>`
  → 結果 JSON 印至 stdout。
- **獎金/獎品字串格式**：`"cash 500"`、`"ball x1"`；幸運分享獎為 `prize_each: 200`。
- **prose 欄位約定**：輸出中的 `note`、`tie_break` 為人類閱讀用說明，
  測試比對一律先剝除（見 `tests/test_scoring.py::strip_prose`），
  程式或前端不得依賴其內容做邏輯判斷。
- **測試涵蓋**（除 fixture 主驗收外）：差點 0 者得名次不調整、
  同分僵局觸發 needs_manual_resolution、總桿冠軍連鎖順延、
  Eagle 多隻重複發放、幸運分享獎雙數情境。
- 開發相依：`requirements-dev.txt`（pyyaml、pytest）；
  執行 `python -m pytest tests/ -v` 驗收。

## 同分裁定（重要）

同分依 ①差點少者優先；若差點亦相同 → **程式必須停止並標記「待總幹事裁定」**，
不得自行排序或隨機決定。

理由：幸運分享獎依「淨桿排名單雙號」發獎，排名順序一動，得獎名單整批改變。
因此未裁定的同分是**阻斷性**的，必須裁定後才能計算獎項。

admin.html 需提供裁定介面（顯示雙方差點供判斷，總幹事指定順序）。

## 測試 fixture

`tests/fixtures/2025-06-21_taoyuan_*.json` 為第一組驗收測試，取自實際 iSwing 成績卡。
`scoring.py` 必須能重現 expected 檔的結果。涵蓋的邊界情境：

- 來賓排除（3 位非會員不列入排名與獎項）
- 同分以差點裁決（觸發兩次：net 74 與 net 75）
- **淨桿季軍不扣差點**（11~20 區間季軍欄為空）— 最易誤解的規則點
- 幸運分享獎單雙判定（淨桿冠軍 71 為單數 → 排名 1,3,5,7 得獎）
- Eagle 為空的情境
- 球場 par 73 ≠ 差點基準 72

注意 fixture 的差點採 2026-05-22 現值，屬機械驗算，非還原 2025 年真實結果。

## 待補資料

- [ ] 補登其他常打球場的每洞 par（rules.yaml courses 區塊）
- [ ] repo Settings → Secrets 加入 `ANTHROPIC_API_KEY`（/scorecard 命令需要）
- [ ] 確認 GitHub Pages 設定為 main branch 部署（score.yml push 後自動更新網頁）
- [ ] **實照片調校**：拿實際 iSwing / 手寫成績卡跑 `/scorecard` 命令，調 prompt 至
  欄位辨識率 > 90%（全系統唯一未驗收項）
- [ ] 驗證 /scorecard 命令完整流程（draft 生成 → admin.html 載入 → 校對 → 發布）
