import os
import random
import asyncio
import time
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# ===== КЛЮЧИ =====
def load_keys(env_var: str) -> list[str]:
    val = os.getenv(env_var, "")
    return [k.strip() for k in val.split(",") if k.strip()]

GROQ_KEYS      = load_keys("GROQ_KEYS")
CEREBRAS_KEYS  = load_keys("CEREBRAS_KEYS")
SAMBANOVA_KEYS = load_keys("SAMBANOVA_KEYS")
MISTRAL_KEYS   = load_keys("MISTRAL_KEYS")

# ===== ПРОВАЙДЕРЫ =====
PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "keys": GROQ_KEYS,
        "models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "gemma2-9b-it",
            "mixtral-8x7b-32768",
        ],
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "keys": CEREBRAS_KEYS,
        "models": [
            "llama3.3-70b",
            "llama3.1-8b",
            "llama-4-scout-17b-16e-instruct",
        ],
    },
    "sambanova": {
        "base_url": "https://api.sambanova.ai/v1",
        "keys": SAMBANOVA_KEYS,
        "models": [
            "Meta-Llama-3.3-70B-Instruct",
            "Meta-Llama-3.1-405B-Instruct",
            "DeepSeek-R1",
            "Qwen3-32B",
        ],
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "keys": MISTRAL_KEYS,
        "models": [
            "mistral-small-latest",
            "mistral-medium-latest",
            "open-mistral-7b",
            "open-mixtral-8x7b",
        ],
    },
}

# Строим обратный словарь: model_id -> provider
MODEL_TO_PROVIDER: dict[str, str] = {}
for provider_name, cfg in PROVIDERS.items():
    for model in cfg["models"]:
        MODEL_TO_PROVIDER[model] = provider_name

# ===== КЛЮЧИ: ротация =====
key_index: dict[str, int] = {p: 0 for p in PROVIDERS}

def get_key(provider: str) -> str:
    keys = PROVIDERS[provider]["keys"]
    if not keys:
        raise HTTPException(500, f"No keys for provider {provider}")
    idx = key_index[provider] % len(keys)
    key_index[provider] = (idx + 1) % len(keys)
    return keys[idx]

# ===== APP =====
app = FastAPI(title="KvasAI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== PING (для keep-alive) =====
@app.get("/ping")
async def ping():
    return {"status": "ok"}

# ===== MODELS =====
@app.get("/v1/models")
async def list_models():
    models = []
    for provider_name, cfg in PROVIDERS.items():
        for model_id in cfg["models"]:
            models.append({
                "id": model_id,
                "object": "model",
                "owned_by": provider_name,
                "created": int(time.time()),
            })
    return {"object": "list", "data": models}

# ===== CHAT COMPLETIONS =====
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    # Проверка авторизации (kvs- ключи и demo)
    auth = request.headers.get("Authorization", "")
    if not (auth.startswith("Bearer kvs-")):
        raise HTTPException(401, "Invalid API key")

    body = await request.json()
    model = body.get("model")
    stream = body.get("stream", False)

    if not model:
        raise HTTPException(400, "model is required")

    provider_name = MODEL_TO_PROVIDER.get(model)
    if not provider_name:
        raise HTTPException(404, f"Model '{model}' not found")

    provider = PROVIDERS[provider_name]
    api_key  = get_key(provider_name)
    url      = f"{provider['base_url']}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        if stream:
            async def generate():
                async with client.stream("POST", url, json=body, headers=headers) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
            return StreamingResponse(generate(), media_type="text/event-stream")
        else:
            resp = await client.post(url, json=body, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(resp.status_code, resp.text)
            return JSONResponse(resp.json())

# ===== СТАТИКА (сайт) =====
app.mount("/", StaticFiles(directory="static", html=True), name="static")

