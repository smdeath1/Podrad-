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
DB_PATH = os.getenv("DB_PATH", "/tmp/data/jobs.db")  # Изменено на /tmp
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")  # Например, "username/telegram-bot-data"
GITHUB_PATH = os.getenv("GITHUB_PATH", "jobs.db")  # Путь к файлу в репозитории

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

user_states = {}
user_edit_states = {}

def init_db():
    # Создаем директорию для базы данных
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:  # Проверяем, что путь не пустой
        try:
            os.makedirs(db_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"Ошибка создания директории {db_dir}: {e}")
    
    # Скачиваем базу данных с GitHub, если она не существует локально
    if not os.path.exists(DB_PATH) and GITHUB_TOKEN and GITHUB_REPO:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_PATH}"
            headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3.raw"}
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                with open(DB_PATH, "wb") as f:
                    f.write(base64.b64decode(response.json()["content"]))
                logger.info("База данных восстановлена с GitHub")
            else:
                logger.warning("База данных не найдена на GitHub, создается новая")
        except Exception as e:
            logger.error(f"Ошибка восстановления базы данных: {e}")

    # Инициализируем базу данных
    try:
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
    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")

def backup_db():
    # Загружаем базу данных на GitHub
    if GITHUB_TOKEN and GITHUB_REPO and os.path.exists(DB_PATH):
        try:
            with open(DB_PATH, "rb") as f:
                content = base64.b64encode(f.read()).decode("utf-8")
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_PATH}"
            headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
            # Проверяем, существует ли файл
            response = requests.get(url, headers=headers)
            sha = response.json().get("sha") if response.status_code == 200 else None
            # Обновляем или создаем файл
            data = {
                "message": "Update jobs.db",
                "content": content,
                "branch": "main"
            }
            if sha:
                data["sha"] = sha
            response = requests.put(url, headers=headers, json=data)
            if response.status_code in [200, 201]:
                logger.info("База данных сохранена на GitHub")
            else:
                logger.error(f"Ошибка сохранения базы данных: {response.status_code}")
        except Exception as e:
            logger.error(f"Ошибка при резервном копировании: {e}")

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
    try:
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
                backup_db()
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
    except Exception as e:
        logger.error(f"Ошибка в employer_start: {e}")
        await message.answer("Ошибка. Попробуйте позже.")

@dp.message(F.text == "Оплатил")
async def check_payment(message: Message):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT subscription_active, subscription_start FROM users WHERE telegram_id = ?", (message.from_user.id,))
            row = cur.fetchone()
            if row and row[0] == 1:
                start_date = datetime.strptime(row[1], "%Y-%m-%d")
                if datetime.now() - start_date <= timedelta(days=30):
                    kb = ReplyKeyboardBuilder()
                    kb.button(text="Разместить вакансию")
                    kb

                    .button(text="Мои вакансии")
                    kb.button(text="Подписка")
                    await message.answer("✅ Подписка подтверждена. Добро пожаловать!", reply_markup=kb.as_markup(resize_keyboard=True))
                    return
        await message.answer("❌ Оплата ещё не подтверждена админом.\nПожалуйста, свяжитесь с ним.")
    except Exception as e:
        logger.error(f"Ошибка в check_payment: {e}")
        await message.answer("Ошибка. Попробуйте позже.")

@dp.message(F.text == "Разместить вакансию")
async def add_vacancy(message: Message):
    user_states.pop(message.from_user.id, None)
    user_edit_states.pop(message.from_user.id, None)
    user_states[message.from_user.id] = {"step": "city"}
    await message.answer("Введите город:")

@dp.message(F.text == "Мои вакансии")
async def my_vacancies(message: Message):
    try:
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
                kb.button(text=f"Изменить {vid}")
                kb.button(text=f"Удалить {vid}")
            kb.adjust(1)
            await message.answer("Ваши вакансии:", reply_markup=kb.as_markup(resize_keyboard=True))
    except Exception as e:
        logger.error(f"Ошибка в my_vacancies: {e}")
        await message.answer("Ошибка. Попробуйте позже.")

@dp.message(F.text.regexp(r"^Удалить \d+$"))
async def delete_vacancy(message: Message):
    try:
        vid = int(message.text.split()[1])
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT employer_code FROM users WHERE telegram_id = ?", (message.from_user.id,))
            user = cur.fetchone()
            if not user:
                return await message.answer("Ошибка. Вы не работодатель.")
            employer_code = user[0]
            cur.execute(" DEL
ETE FROM vacancies WHERE id = ? AND employer_code = ?", (vid, employer_code))
            if cur.rowcount:
                conn.commit()
                backup_db()
                await message.answer(f"Вакансия #{vid} удалена.")
            else:
                await message.answer("Вакансия не найдена или не принадлежит вам.")
    except Exception as e:
        logger.error(f"Ошибка в delete_vacancy: {e}")
        await message.answer("Ошибка. Попробуйте позже.")

@dp.message(F.text.regexp(r"^Изменить \d+$"))
async def start_edit(message: Message):
    try:
        vid = int(message.text.split()[1])
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT employer_code FROM users WHERE telegram_id = ?", (message.from_user.id,))
            user = cur.fetchone()
            if not user:
                return await message.answer("Ошибка. Вы не работодатель.")
            employer_code = user[0]
            cur.execute("SELECT id FROM vacancies WHERE id = ? AND employer_code = ?", (vid, employer_code))
            if not cur.fetchone():
                return await message.answer("Вакансия не найдена или не принадлежит вам.")
        user_edit_states[message.from_user.id] = vid
        await message.answer(f"Введите новое описание для вакансии #{vid}:")
    except Exception as e:
        logger.error(f"Ошибка в start_edit: {e}")
        await message.answer("Ошибка. Попробуйте позже.")

@dp.message(F.text == "Подписка")
async def subscription_status(message: Message):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT subscription_start FROM users WHERE telegram_id = ?", (message.from_user.id,))
            row = cur.fetchone()
            if not row or not row[0]:
                return await message.answer("Подписка не активна.")
            start = datetime.strptime(row[0], "%Y-%m-%d")
            days_left = 30 - (datetime.now() - start).days
            if days_left < 0:
                cur.execute("UPDATE users SET subscription_active = 0, subscription_start = NULL WHERE telegram_id = ?", (message.from_user.id,))
                conn.commit()
                backup_db()
                await message.answer("Подписка истекла.")
            else:
                await message.answer(f"Осталось дней подписки: {days_left}")
    except Exception as e:
        logger.error(f"Ошибка в subscription_status: {e}")
        await message.answer("Ошибка. Попробуйте позже.")

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
    kb.button(text="/confirm_subscription")
    kb.adjust(1)
    await message.answer("🔧 Админ-панель активна:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "/confirm_subscription")
async def confirm_subscription_start(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("Нет доступа.")
    user_states[message.from_user.id] = {"step": "confirm_subscription"}
    await message.answer("Введите Telegram ID или employer_code пользователя для подтверждения подписки:")

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
                backup_db()
                await message.answer("✅ Готово.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message(F.text == "/vacancies")
async def admin_vacancies(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("Нет доступа.")
    try:
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
    except Exception as e:
        logger.error(f"Ошибка в admin_vacancies: {e}")
        await message.answer("Ошибка. Попробуйте позже.")

@dp.message()
async def handle_input(message: Message):
    uid = message.from_user.id
    try:
        if uid in user_edit_states:
            vid = user_edit_states.pop(uid)
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute("UPDATE vacancies SET description = ? WHERE id = ?", (message.text.strip(), vid))
                conn.commit()
                backup_db()
            return await message.answer("Описание обновлено.")
        if uid in user_states:
            state = user_states[uids]
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
                    cur.execute("INSERT INTO vacancies (employer_code, city, description) VALUES (?, ?, ?)", (row[0],olf state["city"], message.text.strip()))
                    conn.commit()
                    backup_db()
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
            elif state.get("step") == "confirm_subscription":
                input_text = message.text.strip()
                with sqlite3.connect(DB_PATH) as conn:
                    cur = conn.cursor()
                    if input_text.isdigit():
                        cur.execute("SELECT telegram_id FROM users WHERE telegram_id = ?", (int(input_text),))
                    else:
                        cur.execute("SELECT telegram_id FROM users WHERE employer_code = ?", (input_text,))
                    row = cur.fetchone()
                    if not row:
                        user_states.pop(uid)
                        return await message.answer("Пользователь не найден.")
                    telegram_id = row[0]
                    cur.execute(
                        "UPDATE users SET subscription_active = 1, subscription_start = ? WHERE telegram_id = ?",
                        (datetime.now().strftime("%Y-%m-%d"), telegram_id)
                    )
                    conn.commit()
                    backup_db()
                user_states.pop(uid)
                await message.answer(f"Подписка для пользователя (ID: {telegram_id}) подтверждена.")
                try:
                    await bot.send_message(
                        telegram_id,
                        "✅ Ваша подписка подтверждена! Теперь вы можете размещать вакансии.",
                        reply_markup=ReplyKeyboardBuilder()
                            .button(text="Разместить вакансию")
                            .button(text="Мои вакансии")
                            .button(text="Подписка")
                            .as_markup(resize_keyboard=True)
                    )
                except Exception as e:
                    await message.answer(f"Не удалось уведомить пользователя: {e}")
        else:
            await message.answer("Напиши /start")
    except Exception as e:
        logger.error(f"Ошибка в handle_input: {e}")
        await message.answer("Ошибка. Попробуйте позже.")

if __name__ == "__main__":
    init_db()
    import asyncio
    asyncio.run(dp.start_polling(bot))
