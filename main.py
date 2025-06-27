import os
import sqlite3
import logging
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

@dp.message(F.text == "Я работодатель")
async def employer_start(message: Message):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE telegram_id = ?", (message.from_user.id,))
        user = cur.fetchone()
        if not user:
            employer_code = f"EMP{message.from_user.id}"
            cur.execute(
                "INSERT INTO users (telegram_id, role, employer_code, subscription_active) VALUES (?, ?, ?, 0)",
                (message.from_user.id, "employer", employer_code)
            )
            conn.commit()
        else:
            employer_code = user[2]

    kb = ReplyKeyboardBuilder()
    kb.button(text="Оплатил")
    await message.answer(
        f"✅ Ваш код работодателя: <b>{employer_code}</b>\n\n"
        f"📩 Свяжитесь с админом для оплаты: @{ADMIN_USERNAME}\n"
        f"После оплаты нажмите кнопку <b>Оплатил</b>.",
        reply_markup=kb.as_markup(resize_keyboard=True)
    )

@dp.message(F.text == "Оплатил")
async def check_payment(message: Message):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT subscription_active, subscription_start FROM users WHERE telegram_id = ?", (message.from_user.id,))
        row = cur.fetchone()
        if row and row[0] == 1:
            start_date = datetime.strptime(row[1], "%Y-%m-%d")
            if datetime.now() - start_date <= timedelta(days=30):
                kb = ReplyKeyboardBuilder()
                kb.button(text="Разместить вакансию")
                kb.button(text="Мои вакансии")
                kb.button(text="Подписка")
                await message.answer("✅ Подписка подтверждена. Добро пожаловать!", reply_markup=kb.as_markup(resize_keyboard=True))
                return
    await message.answer("❌ Оплата ещё не подтверждена админом.\nПожалуйста, свяжитесь с ним.")

@dp.message(F.text == "Разместить вакансию")
async def add_vacancy(message: Message):
    user_states.pop(message.from_user.id, None)
    user_edit_states.pop(message.from_user.id, None)
    user_states[message.from_user.id] = {"step": "city"}
    await message.answer("Введите город:")

@dp.message(F.text == "Мои вакансии")
async def my_vacancies(message: Message):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT employer_code, subscription_active, subscription_start FROM users WHERE telegram_id = ?", (message.from_user.id,))
        user = cur.fetchone()
        if not user or user[1] != 1:
            return await message.answer("❌ Подписка не активна.")
        employer_code = user[0]
        cur.execute("SELECT id, description FROM vacancies WHERE employer_code = ?", (employer_code,))
        rows = cur.fetchall()
        if not rows:
            return await message.answer("У вас пока нет вакансий.")
        kb = ReplyKeyboardBuilder()
        for vid, desc in rows:
            short_desc = desc if len(desc) <= 30 else desc[:27] + "..."
            kb.button(text=f"{vid}: {short_desc}")
        await message.answer("Ваши вакансии:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text.regexp(r"^Удалить \d+$"))
async def delete_vacancy(message: Message):
    vid = int(message.text.split()[1])
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM vacancies WHERE id = ?", (vid,))
        if cur.rowcount:
            conn.commit()
            await message.answer(f"Вакансия #{vid} удалена.")
        else:
            await message.answer("Не найдена или не ваша.")

@dp.message(F.text.regexp(r"^Изменить \d+$"))
async def start_edit(message: Message):
    vid = int(message.text.split()[1])
    user_edit_states[message.from_user.id] = vid
    await message.answer(f"Введите новое описание для вакансии #{vid}:")

@dp.message(F.text == "Подписка")
async def subscription_status(message: Message):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT subscription_start FROM users WHERE telegram_id = ?", (message.from_user.id,))
        row = cur.fetchone()
        if not row or not row[0]:
            return await message.answer("Подписка не активна.")
        start = datetime.strptime(row[0], "%Y-%m-%d")
        days_left = 30 - (datetime.now() - start).days
        await message.answer(f"Осталось дней подписки: {days_left}")

@dp.message(F.text == "Ищу работу")
async def search_job(message: Message):
    user_states[message.from_user.id] = {"step": "worker_city"}
    await message.answer("Введите город для поиска:")

@dp.message(F.text == "🔧 Админ-панель")
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("Нет доступа.")
    kb = ReplyKeyboardBuilder()
    kb.button(text="/vacancies")
    kb.button(text="/sql SELECT * FROM users")
    kb.button(text="/sql SELECT * FROM vacancies")
    await message.answer("🔧 Админ-панель активна:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text.startswith("/sql "))
async def sql_command(message: Message):
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
                    return await message.answer("Пусто.")
                result = "\n".join(str(row) for row in rows)
                await message.answer(f"<pre>{result}</pre>", parse_mode="HTML")
            else:
                conn.commit()
                await message.answer("✅ Готово.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message(F.text == "/vacancies")
async def admin_vacancies(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("Нет доступа.")
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, employer_code, city, description FROM vacancies")
        rows = cur.fetchall()
        if not rows:
            return await message.answer("Нет вакансий.")
        text = ""
        for row in rows:
            text += f"{row[0]} | {row[1]} | {row[2]} | {row[3][:40]}...\n"
        await message.answer(f"<pre>{text}</pre>", parse_mode="HTML")

@dp.message()
async def handle_input(message: Message):
    uid = message.from_user.id
    if uid in user_edit_states:
        vid = user_edit_states.pop(uid)
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE vacancies SET description = ? WHERE id = ?", (message.text.strip(), vid))
            conn.commit()
        return await message.answer("Описание обновлено.")
    if uid in user_states:
        state = user_states[uid]
        if state.get("step") == "city":
            state["city"] = message.text.strip()
            state["step"] = "desc"
            return await message.answer("Введите описание вакансии:")
        elif state.get("step") == "desc":
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute("SELECT employer_code FROM users WHERE telegram_id = ?", (uid,))
                row = cur.fetchone()
                if not row:
                    return await message.answer("Ошибка. Вы не работодатель.")
                cur.execute("INSERT INTO vacancies (employer_code, city, description) VALUES (?, ?, ?)", (row[0], state["city"], message.text.strip()))
                conn.commit()
            user_states.pop(uid)
            return await message.answer("Вакансия добавлена.")
        elif state.get("step") == "worker_city":
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, city, description FROM vacancies WHERE city LIKE ?", (f"%{message.text.strip()}%",))
                rows = cur.fetchall()
            if not rows:
                return await message.answer("Вакансий нет.")
            result = ""
            for row in rows:
                result += f"#{row[0]} | {row[1]}: {row[2][:50]}...\n"
            user_states.pop(uid)
            return await message.answer(result)
    else:
        await message.answer("Напиши /start")

if __name__ == "__main__":
    init_db()
    import asyncio
    asyncio.run(dp.start_polling(bot))
