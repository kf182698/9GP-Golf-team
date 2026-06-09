# 9GP Chatbot Demo

這份 Demo 讓 GitHub Pages 上的 `chatbot.html` 透過 HTTPS tunnel 呼叫本機 Ubuntu 的 FastAPI proxy，再由 proxy 轉送到 Ollama。

架構：

```text
GitHub Pages chatbot UI
-> HTTPS tunnel URL
-> 本機 FastAPI proxy
-> Ollama http://localhost:11434/api/chat
```

## 1. 啟動 Ollama

在 Ubuntu 安裝並啟動 Ollama 後，確認服務可用：

```bash
ollama serve
```

如果 Ollama 已經由 systemd 或桌面服務啟動，可以略過 `ollama serve`。

下載或確認 Demo 使用的模型：

```bash
ollama pull qwen2.5:14b
ollama list
```

測試 Ollama API：

```bash
curl http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5:14b","stream":false,"messages":[{"role":"user","content":"你好"}]}'
```

## 2. 啟動 FastAPI proxy

進入 backend 目錄，建立虛擬環境並安裝套件：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

建立環境變數檔：

```bash
cp .env.example .env
```

編輯 `.env`。如果前端維持預設 `X-API-Key: demo key`，請把 API_KEY 改成：

```text
API_KEY=demo key
OLLAMA_MODEL=qwen2.5:14b
OLLAMA_URL=http://localhost:11434/api/chat
```

啟動 FastAPI：

```bash
uvicorn app:app --host 127.0.0.1 --port 8000
```

本機測試：

```bash
curl http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: demo key" \
  -d '{"message":"請用一句話介紹 9GP Golf Team chatbot demo"}'
```

## 3. 建立 HTTPS tunnel

GitHub Pages 是 HTTPS 網站，瀏覽器通常會阻擋直接呼叫本機 HTTP，所以需要 HTTPS tunnel。

### ngrok

```bash
ngrok http 8000
```

複製 ngrok 顯示的 `https://...ngrok-free.app` URL。

### Cloudflare Tunnel

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

複製 Cloudflare 顯示的 `https://...trycloudflare.com` URL。

## 4. 更新 chatbot.js

打開 `chatbot.js`，把：

```javascript
const API_BASE_URL = "請替換成你的 tunnel URL";
```

改成你的 HTTPS tunnel URL，例如：

```javascript
const API_BASE_URL = "https://example.trycloudflare.com";
```

前端會呼叫：

```text
POST {API_BASE_URL}/chat
```

並帶入：

```text
Content-Type: application/json
X-API-Key: demo key
```

## 5. 部署到 GitHub Pages

把新增檔案提交到 `main` 分支後，確認 GitHub Pages 設定使用這個 repo 的 `main` 分支。

Demo 頁面網址通常會是：

```text
https://kf182698.github.io/9GP-Golf-team/chatbot.html
```

如果你改了 repo 名稱或 Pages 設定，請以 GitHub Pages 顯示的實際網址為準。

## 6. 安全提醒

不要直接公開 Ollama 的 `11434` port。請讓公開網址只連到 FastAPI proxy，並保留 API key、CORS、訊息長度限制等防護。

這份 Demo 的 `demo key` 只適合展示用途。正式使用時請換成較長、不可猜測的 API key，並同步更新 `.env` 與 `chatbot.js`。
