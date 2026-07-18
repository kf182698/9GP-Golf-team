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
┌─ PWA（GitHub Pages 上的手機網頁）────────┐
│ admin.html : ①上傳 ②辨識校對 ③手動獎項輸入 │
│ index.html : 成績與獎項查詢（對外公開唯讀）  │
└──────────┬────────────────────┘
           │ GitHub API（fine-grained PAT，存於瀏覽器 localStorage）
           ▼
┌─ Repo: kf182698/9GP-Golf-team ──────────┐
│ scorecards/      原始照片存檔              │
│ pending/         AI 辨識草稿 JSON          │
│ golf_scores.json 正式成績（唯一資料源）      │
│ rules.yaml       計積規則（唯一規則來源）     │
└──────────┬────────────────────┘
           │ 觸發 GitHub Actions
           ▼
┌─ Actions（金鑰放 GitHub Secrets）─────────┐
│ ocr.yml   : 照片 → Claude Vision → pending/ │
│ score.yml : 確認後 → scoring.py → 更新成績   │
└────────────────────────────────────┘
```

## 目錄結構

```
9GP-Golf-team/
├── index.html          # 對外：成績/獎項/差點走勢
├── admin.html          # 總幹事：上傳、校對、手動輸入、一鍵發布
├── manifest.json       # PWA 設定（加到主畫面）
├── golf_scores.json    # 正式成績資料庫
├── rules.yaml          # 計積規則設定檔
├── scorecards/         # 原始照片，依日期分資料夾
├── pending/            # 待確認辨識草稿
├── scripts/
│   ├── ocr_parse.py    # Claude Vision 辨識成績卡
│   └── scoring.py      # 計分引擎
└── .github/workflows/
    ├── ocr.yml
    └── score.yml
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

## OCR 辨識 schema

`ocr_parse.py` 呼叫 Claude Vision，須輸出：

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
      "is_guest": false,
      "front_9": [5,4,7,4,5,4,5,5,4],
      "back_9": [6,6,3,5,5,5,4,5,4],
      "front_9_total": 43,
      "back_9_total": 43,
      "gross": 86,
      "vs_par": 13,
      "validation": "pass"
    }
  ]
}
```

- 姓名以 rules.yaml 的 players 名冊做模糊比對；比對不到者標記 `is_guest: true`（章程允許來賓與賽）
- **三重交叉驗證**（見 rules.yaml validation 區塊）：逐洞加總 = 半場總和；前九+後九 = 總桿；總桿 − 球場 par = +N 欄
- 驗證不通過的列標記 `validation: "fail"`，校對頁面高亮；通過者綠燈，總幹事只需檢視紅字
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
2. 🔶 `ocr_parse.py` — 程式與離線測試完成（2026-07-17）；**驗收待實際成績卡照片**
   調 prompt，目標欄位辨識率 > 90%。實作決定：
   - 以 structured outputs（`output_config.format` + JSON Schema）強制輸出格式，
     model 預設 `claude-opus-4-8`（`OCR_MODEL` 環境變數或 `--model` 覆寫）
   - iSwing / 手寫共用一支程式，`--card-type` 切換 prompt 與 schema；
     手寫卡每格 `{value, confidence}`，後處理拆成桿數陣列 +
     `low_confidence_holes`（< 0.8 標黃）/ `unreadable_holes`（null 標紅）
   - 三重驗證由 rules.yaml `validation.checks` 驅動；任何 null 格 → 該列 `fail`
   - 姓名以 difflib 對名冊模糊比對（cutoff 0.6），比對到者正規化並保留
     `ocr_name` 原始字串；比對不到 → `is_guest: true`
   - API key 只讀 `ANTHROPIC_API_KEY` 環境變數，未設定即明確報錯
   - CLI：`python scripts/ocr_parse.py --rules rules.yaml --image <照片> \
     --card-type iswing|handwritten [--out pending/xxx.json]`；
     驗證未全過 exit code 1
   - 測試以 fixture input 反推驗證邏輯（實卡 11 列全 pass + 三項檢核竄改必抓）
3. ✅ 兩支 Actions workflow 串接（2026-07-17 完成，見下）
4. ✅ PWA 前端 — 全部完成（2026-07-17，第一回合手動路徑 + 第二回合閉環，見下）

各階段可獨立驗收。**系統開發完工**；僅剩實照片調校（見「待補資料」）。

## 階段 4 第二回合實作決定（2026-07-17：日常操作閉環 + 門面）

日常操作四步驟（上傳→校對→近洞獎/裁定→發布上網頁）全部閉環：

- **manual_tie_order 契約**（引擎小改）：match_input 選用欄位
  `manual_tie_order: ["甲","乙"]`（前者名次較前）。「淨桿與差點皆同」的
  兩人皆在列才解僵局並附 tie_break「總幹事裁定」；未涵蓋雙方仍
  needs_manual_resolution 阻斷——程式永不自行排序。
- **同分裁定介面＝發布前本地預檢**：admin.html 進入⑤時以名冊差點算淨桿
  找「淨桿同且差點同」群組，顯示裁定卡（列差點供判斷、依名次順序點選），
  未裁定完發布鈕鎖定。裁定寫入確認稿，不必等 workflow 失敗才處理。
- **照片上傳**：步驟①選配面板——多選照片 PUT `scorecards/<date>/<檔名>`
  → dispatch ocr.yml(image_dir, card_type)。上傳後點「載入辨識草稿」
  GET pending/<date>_draft.json 預填（比對 courses 帶球場；比對不到轉自訂）。
- **色碼校對**（設計要求 6）：綠=該列驗證 pass、黃=low_confidence_holes、
  紅=unreadable null 格；人工改格即清該格標記；總表顯示「校對 n 格」。
  OCR 純預填，任何格可覆寫，無草稿不影響手 key 路徑。
- **近洞獎**：⑤會員 chips 複選 → `manual_awards.near_pin`（list 或 null）。
- **manifest.json**：start_url admin.html（總幹事工具加主畫面）；
  index.html 維持一般網頁。
- **index.html 升級**：新增「最新例賽快報」（載入即顯示排名/獎項，
  來賓標示、請假不列）；走勢圖加差點 dataset（右軸、虛線 accent）。
- **驗收證據**（Playwright 五場景）：手 key 黃金比對回歸、OCR 預填三色碼
  與補格清標記、裁定卡阻斷→點序→引擎依裁定排序（串驗 scoring.py）、
  上傳請求形狀（PUT scorecards + ocr dispatch payload）、index 快報列數
  與雙 dataset。pytest 38 項全綠。

## 階段 4 實作決定（2026-07-17，第一回合：手動輸入路徑）

`admin.html` 單檔（無建置流程），實現「完全沒有 OCR 也能手 key 完成整場」：

- **設定來源**：fetch 同源 `rules.yaml` + js-yaml CDN 解析——名冊與球場
  不 hardcode 於前端。視覺沿用 index.html（Tailwind CDN、primary/accent）。
- **五步驟精靈**：①場次（球場下拉自動帶 hole_pars；「其他球場」手動 par，
  新球場不卡死）→ ②名單（會員按鈕勾選 + 來賓輸入）→ ③單人逐洞
  （大鍵盤 1-9 單鍵即進即跳洞、10+ 兩位數、「照par」、⌫；18 格膠囊列
  可點跳任一洞；前九/後九/總桿即時小計；18 洞完自動跳下一位未完成者）
  → ④總表（紅底=未填，點列跳回補）→ ⑤發布。
- **草稿**：每格輸入即寫 localStorage `gp9_draft`；重開頁偵測草稿詢問續作。
- **發布**：組確認稿 JSON（totals/vs_par 自動計算、`validation: "pass"`、
  `manual_awards.near_pin: null`，與引擎 input 完全同構）→
  GitHub Contents API PUT `pending/<date>_confirmed.json`（已存在帶 sha 更新）
  → dispatch `score.yml`。PAT 存 localStorage `gp9_pat`（⚙ 設定面板），
  金鑰不進 repo。「下載 JSON」為無 PAT 備援。
- **驗收證據**（Playwright 行動 viewport 端到端，腳本不進 repo）：
  模擬 key 完 fixture 11 人 → 產出 JSON 與 fixture input 全欄位一致 →
  直接餵 scoring.py 重現 expected 結果；reload 草稿 198 格不丟；
  發布請求形狀（PUT + dispatch payload）正確。11 人共 198 次點擊
  （每人 18 點、單鍵自動跳洞），估算 ≈5 分鐘 < 10 分鐘驗收線。

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
- **workflow 觸發**：兩支皆 `workflow_dispatch`（供 admin.html 以 GitHub API
  觸發），不做 push 自動觸發（避免多張照片分次上傳重複跑辨識）。
  - `ocr.yml` inputs：`image_dir`（整個資料夾餵同一次辨識）、`card_type`。
    ocr_parse exit 1（有紅字）不視為失敗，草稿照 commit，summary 提示校對。
  - `score.yml` inputs：`input_path`（確認稿，引擎 input 格式）。
    發布前先跑 pytest 守門；成功後刪除該場確認稿與同日期 `*_draft.json`。
- **待辦**：repo Settings → Secrets 需由總幹事加入 `ANTHROPIC_API_KEY`
  （金鑰只在 Actions 內使用）；Actions 實跑驗證待照片階段一併進行。

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
- [ ] iSwing 是否提供匯出功能（若有，OCR 層可簡化為 fallback）
- [ ] repo Settings → Secrets 加入 `ANTHROPIC_API_KEY`（ocr.yml 需要）
- [ ] 確認 GitHub Pages 設定為 main branch 部署（score.yml push 後自動更新網頁）
- [ ] **實照片調校**：拿實際 iSwing / 手寫成績卡跑 ocr.yml，調 prompt 至
  欄位辨識率 > 90%（全系統唯一未驗收項）
