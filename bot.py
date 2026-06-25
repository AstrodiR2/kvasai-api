import os
import asyncio
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN   = os.getenv("BOT_TOKEN")
KVAS_URL    = os.getenv("KVAS_URL", "https://your-app.onrender.com")
ADMIN_IDS   = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# Хранилище ключей пользователей (в памяти, для продакшна лучше БД)
user_keys: dict[int, str] = {}

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

# ===== KEEP-ALIVE =====
async def keep_alive():
    """Пингует сервер каждые 10 минут чтобы не засыпал на Render"""
    await asyncio.sleep(60)  # стартовая задержка
    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.get(f"{KVAS_URL}/ping")
        except Exception:
            pass
        await asyncio.sleep(600)  # 10 минут

# ===== КОМАНДЫ =====
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я бот KvasAI.\n\n"
        "Команды:\n"
        "/getkey — получить API ключ\n"
        "/mykey — посмотреть свой ключ\n"
        "/models — список моделей\n"
        "/ask <вопрос> — задать вопрос AI"
    )

@dp.message(Command("models"))
async def cmd_models(message: Message):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{KVAS_URL}/v1/models")
        models = resp.json().get("data", [])
        text = "📋 *Доступные модели:*\n\n"
        current_provider = None
        for m in models:
            provider = m.get("owned_by", "")
            if provider != current_provider:
                text += f"\n*{provider.upper()}*\n"
                current_provider = provider
            text += f"• `{m['id']}`\n"
        await message.answer(text, parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("getkey"))
async def cmd_getkey(message: Message):
    uid = message.from_user.id
    if uid in user_keys:
        await message.answer(
            f"У тебя уже есть ключ:\n`{user_keys[uid]}`",
            parse_mode="Markdown"
        )
        return

    # Генерируем простой ключ
    import secrets
    key = f"kvs-{secrets.token_hex(16)}"
    user_keys[uid] = key

    await message.answer(
        f"✅ Твой API ключ:\n`{key}`\n\n"
        f"Base URL:\n`{KVAS_URL}/v1`\n\n"
        "Сохрани ключ — повторно не выдаётся.",
        parse_mode="Markdown"
    )

@dp.message(Command("mykey"))
async def cmd_mykey(message: Message):
    uid = message.from_user.id
    if uid not in user_keys:
        await message.answer("У тебя нет ключа. Используй /getkey")
        return
    await message.answer(
        f"🔑 Твой ключ:\n`{user_keys[uid]}`",
        parse_mode="Markdown"
    )

@dp.message(Command("ask"))
async def cmd_ask(message: Message):
    uid = message.from_user.id
    text = message.text.replace("/ask", "", 1).strip()

    if not text:
        await message.answer("Напиши вопрос: /ask Как дела?")
        return

    if uid not in user_keys:
        await message.answer("Сначала получи ключ: /getkey")
        return

    thinking = await message.answer("⏳ Думаю...")

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{KVAS_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {user_keys[uid]}"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": text}]
                }
            )
        result = resp.json()
        answer = result["choices"][0]["message"]["content"]
        await thinking.edit_text(answer)
    except Exception as e:
        await thinking.edit_text(f"❌ Ошибка: {e}")

# ===== ЗАПУСК =====
async def main():
    asyncio.create_task(keep_alive())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

