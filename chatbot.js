const API_BASE_URL = "請替換成你的 tunnel URL";
const DEMO_API_KEY = "demo key";
const MAX_MESSAGE_LENGTH = 1000;

const widget = document.querySelector(".chat-widget");
const toggleButton = document.getElementById("chatToggle");
const closeButton = document.getElementById("chatClose");
const form = document.getElementById("chatForm");
const input = document.getElementById("chatInput");
const submitButton = document.getElementById("chatSubmit");
const messages = document.getElementById("chatMessages");

toggleButton.addEventListener("click", () => {
    widget.classList.remove("is-collapsed");
    toggleButton.setAttribute("aria-expanded", "true");
    input.focus();
});

closeButton.addEventListener("click", () => {
    widget.classList.add("is-collapsed");
    toggleButton.setAttribute("aria-expanded", "false");
});

input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 130)}px`;
});

input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
    }
});

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const text = input.value.trim();
    if (!text) return;

    if (text.length > MAX_MESSAGE_LENGTH) {
        appendMessage("訊息過長，請限制在 1000 字以內。", "error");
        return;
    }

    appendMessage(text, "user");
    input.value = "";
    input.style.height = "auto";
    setLoading(true);

    const loadingMessage = appendMessage("AI 回覆中...", "assistant loading");

    try {
        const endpoint = getChatEndpoint();
        const response = await fetch(endpoint, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-API-Key": DEMO_API_KEY,
            },
            body: JSON.stringify({ message: text }),
        });

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(data.detail || data.error || `HTTP ${response.status}`);
        }

        loadingMessage.remove();
        appendMessage(data.reply || "沒有收到回覆。", "assistant");
    } catch (error) {
        loadingMessage.remove();
        appendMessage(`呼叫失敗：${error.message}`, "error");
    } finally {
        setLoading(false);
        input.focus();
    }
});

function getChatEndpoint() {
    if (!API_BASE_URL || API_BASE_URL.includes("請替換")) {
        throw new Error("請先在 chatbot.js 設定 API_BASE_URL。");
    }

    return `${API_BASE_URL.replace(/\/$/, "")}/chat`;
}

function appendMessage(text, type) {
    const row = document.createElement("div");
    row.className = `chat-message ${type}`;

    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    bubble.textContent = text;

    row.appendChild(bubble);
    messages.appendChild(row);
    messages.scrollTop = messages.scrollHeight;
    return row;
}

function setLoading(isLoading) {
    submitButton.disabled = isLoading;
    input.disabled = isLoading;
}
