import sqlite3
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "7957098235:AAEI6XTZ_zZBMYViaJDymUZ-HFhXhyZtoew"
ADMIN_ID = 8143784621
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

user_states = {}
user_edit_states = {}

def init_db():
    with sqlite3.connect("jobs.db") as conn:
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                role TEXT,
                employer_code TEXT,
                subscription_active INTEGER DEFAULT 1,
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
    await message.answer("Выберите роль:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "Я работодатель")
async def employer_start(message: Message):
    with sqlite3.connect("jobs.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE telegram_id = ?", (message.from_user.id,))
        user = cur.fetchone()
        if not user:
            employer_code = f"EMP{message.from_user.id}"
            cur.execute(
                "INSERT INTO users (telegram_id, role, employer_code, subscription_active, subscription_start) VALUES (?, ?, ?, 1, ?)",
                (message.from_user.id, "employer", employer_code, datetime.now().strftime("%Y-%m-%d"))
            )
            conn.commit()
        else:
            employer_code = user[2]
    kb = ReplyKeyboardBuilder()
    kb.button(text="Разместить вакансию")
    kb.button(text="Мои вакансии")
    kb.button(text="Подписка")
    await message.answer(f"Код: <b>{employer_code}</b>\nВыберите действие.", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "Разместить вакансию")
async def add_vacancy(message: Message):
    uid = message.from_user.id
    with sqlite3.connect("jobs.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT role FROM users WHERE telegram_id = ?", (uid,))
        if not cur.fetchone() or cur.fetchone()[0] != "employer":
            await message.answer("Только для работодателей.")
            return
    user_states[uid] = {"step": "city"}
    await message.answer("Введите город:")

@dp.message(F.text == "Мои вакансии")
async def my_vacancies(message: Message):
    with sqlite3.connect("jobs.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT employer_code FROM users WHERE telegram_id = ?", (message.from_user.id,))
        user = cur.fetchone()
        if not user:
            await message.answer("Зарегистрируйтесь как работодатель.")
            return
        employer_code = user[0]
        cur.execute("SELECT id, description FROM vacancies WHERE employer_code = ?", (employer_code,))
        vacancies = cur.fetchall()
        if not vacancies:
            await message.answer("Нет вакансий.")
            return
        kb = ReplyKeyboardBuilder()
        for vid, desc in vacancies:
            short_desc = desc[:27] + "..." if len(desc) > 30 else desc
            kb.button(text=f"{vid}: {short_desc}")
        await message.answer("Выберите вакансию:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text.regexp(r"^Удалить \d+$"))
async def delete_vacancy(message: Message):
    vid = int(message.text.split()[1])
    uid = message.from_user.id
    with sqlite3.connect("jobs.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT employer_code FROM users WHERE telegram_id = ?", (uid,))
        user = cur.fetchone()
        if not user:
            await message.answer("Ошибка авторизации.")
            return
        employer_code = user[0]
        cur.execute("DELETE FROM vacancies WHERE id = ? AND employer_code = ?", (vid, employer_code))
        if cur.rowcount == 0:
            await message.answer("Вакансия не найдена.")
            return
        conn.commit()
    await message.answer(f"Вакансия #{vid} удалена.")

@dp.message(F.text.regexp(r"^Изменить \d+$"))
async def start_edit_vacancy(message: Message):
    vid = int(message.text.split()[1])
    uid = message.from_user.id
    with sqlite3.connect("jobs.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT employer_code FROM users WHERE telegram_id = ?", (uid,))
        user = cur.fetchone()
        if not user:
            await message.answer("Ошибка авторизации.")
            return
        employer_code = user[0]
        cur.execute("SELECT description FROM vacancies WHERE id = ? AND employer_code = ?", (vid, employer_code))
        if not cur.fetchone():
            await message.answer("Вакансия не найдена.")
            return
    user_edit_states[uid] = vid
    await message.answer(f"Новое описание для #{vid}:")

@dp.message(~F.text.regexp(r"^(Удалить|Изменить) \d+$"))
async def handle_edit_or_add(message: Message):
    uid = message.from_user.id
    if uid in user_edit_states:
        vid = user_edit_states.pop(uid)
        new_desc = message.text.strip()
        with sqlite3.connect("jobs.db") as conn:
            cur = conn.cursor()
            cur.execute("SELECT employer_code FROM users WHERE telegram_id = ?", (uid,))
            user = cur.fetchone()
            if not user:
                await message.answer("Ошибка.")
                return
            employer_code = user[0]
            cur.execute("UPDATE vacancies SET description = ? WHERE id = ? AND employer_code = ?", (new_desc, vid, employer_code))
            if cur.rowcount == 0:
                await message.answer("Ошибка обновления.")
                return
            conn.commit()
        await message.answer(f"Вакансия #{vid} обновлена.")
        return
    if uid in user_states:
        state = user_states[uid]
        if state.get("step") == "city":
            user_states[uid]["city"] = message.text.strip()
            user_states[uid]["step"] = "desc"
            await message.answer("Опишите вакансию:")
        elif state.get("step") == "desc":
            city = user_states[uid]["city"]
            desc = message.text.strip()
            with sqlite3.connect("jobs.db") as conn:
                cur = conn.cursor()
                cur.execute("SELECT employer_code FROM users WHERE telegram_id = ?", (uid,))
                user = cur.fetchone()
                if not user:
                    await message.answer("Ошибка.")
                    user_states.pop(uid)
                    return
                employer_code = user[0]
                cur.execute("INSERT INTO vacancies (employer_code, city, description) VALUES (?, ?, ?)", (employer_code, city, desc))
                conn.commit()
            user_states.pop(uid)
            await message.answer("Вакансия добавлена.")
        return
    if ':' in message.text and message.text.split(":")[0].strip().isdigit():
        vid = int(message.text.split(":")[0].strip())
        with sqlite3.connect("jobs.db") as conn:
            cur = conn.cursor()
            cur.execute("SELECT employer_code FROM users WHERE telegram_id = ?", (uid,))
            user = cur.fetchone()
            if not user:
                await message.answer("Ошибка.")
                return
            employer_code = user[0]
            cur.execute("SELECT description FROM vacancies WHERE id = ? AND employer_code = ?", (vid, employer_code))
            vac = cur.fetchone()
            if not vac:
                await message.answer("Вакансия не найдена.")
                return
        kb = ReplyKeyboardBuilder()
        kb.button(text=f"Изменить {vid}")
        kb.button(text=f"Удалить {vid}")
        await message.answer(f"<b>#{vid}:</b>\n{vac[0]}", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "Подписка")
async def subscription_status(message: Message):
    with sqlite3.connect("jobs.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT subscription_start FROM users WHERE telegram_id = ?", (message.from_user.id,))
        row = cur.fetchone()
        if not row or not row[0]:
            await message.answer("Подписка активна бесконечно.")
        else:
            start = datetime.strptime(row[0], "%Y-%m-%d")
            days_left = 30 - (datetime.now() - start).days
            await message.answer(f"Осталось: {max(0, days_left)} дней.")

@dp.message(F.text == "Ищу работу")
async def search_job(message: Message):
    user_states[message.from_user.id] = {"step": "worker_city"}
    await message.answer("Введите город для поиска:")

@dp.message()
async def search_worker_vacancies(message: Message):
    uid = message.from_user.id
    if uid in user_states and user_states[uid].get("step") == "worker_city":
        city = message.text.strip()
        with sqlite3.connect("jobs.db") as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, description FROM vacancies WHERE city LIKE ?", (f"%{city}%",))
            rows = cur.fetchall()
            if not rows:
                await message.answer("Вакансий нет.")
            else:
                text = "<b>Вакансии:</b>\n\n"
                for vid, desc in rows:
                    short_desc = desc[:67] + "..." if len(desc) > 70 else desc
                    text += f"#{vid}: {short_desc}\n\n"
                await message.answer(text)
        user_states.pop(uid)

# Админ-команды
@dp.message(F.text.startswith("/setsub"))
async def set_subscription(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Используйте: /setsub <user_id> <days>")
        return
    uid, days = int(args[1]), int(args[2])
    with sqlite3.connect("jobs.db") as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO users (telegram_id, subscription_active, subscription_start) VALUES (?, 1, ?)",
                    (uid, datetime.now().strftime("%Y-%m-%d")))
        conn.commit()
    await message.answer(f"Подписка для {uid} установлена на {days} дней.")

@dp.message(F.text.startswith("/deluser"))
async def delete_user(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Используйте: /deluser <user_id>")
        return
    uid = int(args[1])
    with sqlite3.connect("jobs.db") as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE telegram_id = ?", (uid,))
        cur.execute("DELETE FROM vacancies WHERE employer_code IN (SELECT employer_code FROM users WHERE telegram_id = ?)", (uid,))
        conn.commit()
    await message.answer(f"Пользователь {uid} удалён.")

@dp.message(F.text == "/listusers")
async def list_users(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    with sqlite3.connect("jobs.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT telegram_id, role, subscription_active FROM users")
        users = cur.fetchall()
        if not users:
            await message.answer("Нет пользователей.")
            return
        text = "<b>Пользователи:</b>\n"
        for uid, role, sub in users:
            text += f"ID: {uid}, Роль: {role}, Подписка: {sub}\n"
        await message.answer(text)

if __name__ == "__main__":
    init_db()
    import asyncio
    asyncio.run(dp.start_polling(bot))
