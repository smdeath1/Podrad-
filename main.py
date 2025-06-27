import os
import sqlite3
import logging
import base64
import requests
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
DB_PATH = os.getenv("DB_PATH", "/tmp/data/jobs.db")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_PATH = os.getenv("GITHUB_PATH", "jobs.db")

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
user_states = {}
user_edit_states = {}

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if not os.path.exists(DB_PATH) and GITHUB_TOKEN and GITHUB_REPO:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_PATH}"
            headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3.raw"}
            r = requests.get(url, headers=headers)
            if r.status_code == 200:
                content = base64.b64decode(r.json()["content"])
                with open(DB_PATH, "wb") as f:
                    f.write(content)
                logger.info("База восстановлена с GitHub")
        except Exception as e:
            logger.error(f"GitHub восстановление: {e}")
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            role TEXT,
            employer_code TEXT,
            subscription_active INTEGER DEFAULT 0,
            subscription_start TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS vacancies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employer_code TEXT,
            city TEXT,
            description TEXT)''')
        conn.commit()

def backup_db():
    if GITHUB_TOKEN and GITHUB_REPO and os.path.exists(DB_PATH):
        try:
            with open(DB_PATH, "rb") as f:
                content = base64.b64encode(f.read()).decode("utf-8")
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_PATH}"
            headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
            resp = requests.get(url, headers=headers)
            sha = resp.json().get("sha") if resp.status_code == 200 else None
            data = {
                "message": "Update jobs.db",
                "content": content,
                "branch": "main"
            }
            if sha:
                data["sha"] = sha
            put = requests.put(url, headers=headers, json=data)
            if put.status_code not in [200, 201]:
                logger.error(f"GitHub сохранение: {put.status_code}")
        except Exception as e:
            logger.error(f"GitHub бэкап: {e}")

@dp.message(F.text == "/start")
async def start(message: Message):
    kb = ReplyKeyboardBuilder()
    kb.button(text="Я работодатель")
    kb.button(text="Ищу работу")
    if message.from_user.id == ADMIN_ID:
        kb.button(text="🔧 Админ-панель")
    await message.answer("Выберите вашу роль:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "Я работодатель")
async def employer(message: Message):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE telegram_id = ?", (message.from_user.id,))
        row = cur.fetchone()
        if not row:
            code = f"EMP{message.from_user.id}"
            cur.execute("INSERT INTO users (telegram_id, role, employer_code, subscription_active) VALUES (?, ?, ?, 0)",
                        (message.from_user.id, "employer", code))
            conn.commit()
            backup_db()
        else:
            code = row[2]
    kb = ReplyKeyboardBuilder()
    kb.button(text="Оплатил")
    await message.answer(f"Ваш код: <b>{code}</b>\nСвяжитесь с @{ADMIN_USERNAME} для оплаты.", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "Оплатил")
async def confirm(message: Message):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT subscription_active, subscription_start FROM users WHERE telegram_id = ?", (message.from_user.id,))
        row = cur.fetchone()
        if row and row[0] == 1:
            start = datetime.strptime(row[1], "%Y-%m-%d")
            if (datetime.now() - start).days <= 30:
                kb = ReplyKeyboardBuilder()
                kb.button(text="Разместить вакансию")
                kb.button(text="Мои вакансии")
                kb.button(text="Подписка")
                return await message.answer("✅ Подписка активна!", reply_markup=kb.as_markup(resize_keyboard=True))
    await message.answer("❌ Подписка не подтверждена.")

@dp.message(F.text == "Разместить вакансию")
async def add_vacancy(message: Message):
    user_states[message.from_user.id] = {"step": "city"}
    await message.answer("Введите город:")

@dp.message(F.text == "Мои вакансии")
async def my_vacancies(message: Message):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT employer_code FROM users WHERE telegram_id = ?", (message.from_user.id,))
        user = cur.fetchone()
        if not user:
            return await message.answer("Вы не работодатель.")
        cur.execute("SELECT id, description FROM vacancies WHERE employer_code = ?", (user[0],))
        rows = cur.fetchall()
        if not rows:
            return await message.answer("Нет вакансий.")
        kb = ReplyKeyboardBuilder()
        for vid, desc in rows:
            kb.button(text=f"{vid}: {desc[:30]}")
            kb.button(text=f"Изменить {vid}")
            kb.button(text=f"Удалить {vid}")
        await message.answer("Ваши вакансии:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text.regexp(r"^Удалить \d+$"))
async def delete_vacancy(message: Message):
    vid = int(message.text.split()[1])
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM vacancies WHERE id = ?", (vid,))
        conn.commit()
        backup_db()
    await message.answer(f"Удалено: #{vid}")

@dp.message(F.text.regexp(r"^Изменить \d+$"))
async def edit_vacancy_start(message: Message):
    user_edit_states[message.from_user.id] = int(message.text.split()[1])
    await message.answer("Введите новое описание:")

@dp.message(F.text == "Подписка")
async def subscription(message: Message):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT subscription_start FROM users WHERE telegram_id = ?", (message.from_user.id,))
        row = cur.fetchone()
        if not row or not row[0]:
            return await message.answer("Подписка не активна.")
        days = 30 - (datetime.now() - datetime.strptime(row[0], "%Y-%m-%d")).days
        await message.answer(f"Осталось {max(0, days)} дней подписки.")

@dp.message(F.text == "Ищу работу")
async def find_work(message: Message):
    user_states[message.from_user.id] = {"step": "worker_city"}
    await message.answer("Введите город:")

@dp.message()
async def handler(message: Message):
    uid = message.from_user.id
    if uid in user_edit_states:
        vid = user_edit_states.pop(uid)
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE vacancies SET description = ? WHERE id = ?", (message.text.strip(), vid))
            conn.commit()
            backup_db()
        return await message.answer("Обновлено.")
    if uid in user_states:
        step = user_states[uid]["step"]
        if step == "city":
            user_states[uid]["city"] = message.text.strip()
            user_states[uid]["step"] = "desc"
            return await message.answer("Введите описание:")
        elif step == "desc":
            city = user_states[uid]["city"]
            desc = message.text.strip()
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute("SELECT employer_code FROM users WHERE telegram_id = ?", (uid,))
                row = cur.fetchone()
                if not row:
                    return await message.answer("Вы не работодатель.")
                cur.execute("INSERT INTO vacancies (employer_code, city, description) VALUES (?, ?, ?)", (row[0], city, desc))
                conn.commit()
                backup_db()
            user_states.pop(uid)
            return await message.answer("Вакансия добавлена.")
        elif step == "worker_city":
            city = message.text.strip()
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, description FROM vacancies WHERE city LIKE ?", (f"%{city}%",))
                rows = cur.fetchall()
            user_states.pop(uid)
            if not rows:
                return await message.answer("Вакансий нет.")
            text = "\n".join([f"#{r[0]}: {r[1][:50]}" for r in rows])
            return await message.answer(text)
    await message.answer("Напиши /start")

if __name__ == "__main__":
    init_db()
    import asyncio
    asyncio.run(dp.start_polling(bot))
