import os

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

API_KEY = os.getenv("API_KEY", "change-me")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "1000"))

app = FastAPI(title="9GP Ollama Chat Proxy")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://kf182698.github.io"],
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)


class ChatRequest(BaseModel):
    message: str


def verify_api_key(x_api_key: str = Header(default="", alias="X-API-Key")):
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


@app.post("/chat")
def chat(payload: ChatRequest, _: None = Depends(verify_api_key)):
    message = payload.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    if len(message) > MAX_MESSAGE_LENGTH:
        raise HTTPException(
            status_code=413,
            detail=f"Message exceeds {MAX_MESSAGE_LENGTH} characters",
        )

    ollama_payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": message,
            }
        ],
    }

    try:
        response = requests.post(OLLAMA_URL, json=ollama_payload, timeout=120)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Ollama request failed: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Ollama returned invalid JSON") from exc

    reply = data.get("message", {}).get("content", "")

    if not reply:
        raise HTTPException(status_code=502, detail="Ollama response did not include a reply")

    return {"reply": reply}
