import os
import sqlite3
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")

DB_PATH = os.getenv("DB_PATH", "jobs.db")
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

user_states = {}
user_edit_states = {}

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                role TEXT,
                employer_code TEXT,
                subscription_active INTEGER DEFAULT 0,
                subscription_start TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS vacancies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employer_code TEXT,
                city TEXT,
                description TEXT
            )
        ''')
        conn.commit()

@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    kb = ReplyKeyboardBuilder()
    kb.button(text="Я работодатель")
    kb.button(text="Ищу работу")
    if message.from_user.id == ADMIN_ID:
        kb.button(text="🔧 Админ-панель")
    await message.answer("Выберите вашу роль:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "🔧 Админ-панель")
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("Нет доступа.")
    kb = ReplyKeyboardBuilder()
    kb.button(text="/vacancies")
    kb.button(text="/sql SELECT * FROM users")
    kb.button(text="/sql SELECT * FROM vacancies")
    kb.button(text="/start")
    await message.answer("🔧 Выберите действие:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text.startswith("/sql "))
async def run_sql(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("Нет доступа.")
    query = message.text[5:]
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute(query)
            if query.lower().startswith("select"):
                rows = cur.fetchall()
                if not rows:
                    return await message.answer("Нет данных.")
                msg = "\n".join(str(r) for r in rows)
                await message.answer(f"<pre>{msg}</pre>", parse_mode="HTML")
            else:
                conn.commit()
                await message.answer("✅ Выполнено.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(F.text == "/vacancies")
async def all_vacancies(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("Нет доступа.")
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, employer_code, city, description FROM vacancies")
        rows = cur.fetchall()
        if not rows:
            return await message.answer("Нет вакансий.")
        msg = "<b>Вакансии:</b>\n\n"
        for vid, code, city, desc in rows:
            msg += f"#{vid} [{code}] {city}: {desc[:50]}...\n"
        await message.answer(msg)

if __name__ == "__main__":
    init_db()
    import asyncio
    asyncio.run(dp.start_polling(bot))
