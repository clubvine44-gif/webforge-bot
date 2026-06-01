import asyncio
import logging
import sqlite3
import json
import random
from collections import Counter
from datetime import datetime, date, timedelta
from typing import Optional
from groq import AsyncGroq
from aiogram import Bot, Dispatcher, F
from aiogram.types import (Message, CallbackQuery,
                           InlineKeyboardMarkup, InlineKeyboardButton,
                           ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ─── КОНФИГ ───────────────────────────────────────────────
BOT_TOKEN = "8791691025:AAEBDYEUo2QgqU19Sr_Is2wEjSeG9NUjwz0"
GROQ_API_KEY = "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"
GROQ_MODEL = "llama-3.3-70b-versatile"
DB_PATH = "/root/miron.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
groq_client = AsyncGroq(api_key=GROQ_API_KEY)

# ─── КЛАВИАТУРЫ ───────────────────────────────────────────
def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="😊 Оценить день")],
            [KeyboardButton(text="⏰ Время уведомлений"), KeyboardButton(text="⏸ Пауза")],
            [KeyboardButton(text="🔞 Режим 18+")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Напиши что-нибудь..."
    )

def mood_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="😫 1", callback_data="mood_1"),
        InlineKeyboardButton(text="😔 3", callback_data="mood_3"),
        InlineKeyboardButton(text="😐 5", callback_data="mood_5"),
        InlineKeyboardButton(text="🙂 7", callback_data="mood_7"),
        InlineKeyboardButton(text="😊 9", callback_data="mood_9"),
    ]])

def time_kb():
    times = ["19:00", "20:00", "21:00", "22:00", "23:00"]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=f"settime_{t}") for t in times[:3]],
        [InlineKeyboardButton(text=t, callback_data=f"settime_{t}") for t in times[3:]],
        [InlineKeyboardButton(text="✏️ Своё время", callback_data="settime_custom")],
    ])

def pause_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="3 дня", callback_data="pause_3"),
            InlineKeyboardButton(text="7 дней", callback_data="pause_7"),
            InlineKeyboardButton(text="14 дней", callback_data="pause_14"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="pause_cancel")],
    ])

def gender_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Парень", callback_data="gender_male"),
        InlineKeyboardButton(text="Девушка", callback_data="gender_female"),
        InlineKeyboardButton(text="Не скажу", callback_data="gender_none"),
    ]])

# ─── БАЗА ДАННЫХ ───────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id      INTEGER PRIMARY KEY,
            username     TEXT,
            name         TEXT,
            age          INTEGER,
            gender       TEXT,
            notify_time  TEXT DEFAULT '21:00',
            is_active    INTEGER DEFAULT 1,
            paused_until TEXT,
            registered_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER,
            role         TEXT,
            content      TEXT,
            session_date TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS summaries (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER,
            session_date TEXT,
            mood         INTEGER,
            topics       TEXT,
            summary      TEXT,
            created_at   TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, session_date)
        );
    """)
    # Добавляем колонки если их нет (для старых баз)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN age INTEGER")
    except:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN gender TEXT")
    except:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN adult_mode INTEGER DEFAULT 0")
    except:
        pass
    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect(DB_PATH)

def get_user(user_id: int):
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row:
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
    return None

def upsert_user(user_id: int, username: str, name: str, age: int, gender: str, notify_time: str = "21:00"):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (user_id, username, name, age, gender, notify_time)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username, name=excluded.name,
                age=excluded.age, gender=excluded.gender
        """, (user_id, username or "", name, age, gender, notify_time))

def save_message(user_id: int, role: str, content: str, session_date: str = None):
    if session_date is None:
        session_date = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (user_id, role, content, session_date) VALUES (?,?,?,?)",
            (user_id, role, content, session_date)
        )

def get_today_messages(user_id: int, session_date: str = None) -> list:
    if session_date is None:
        session_date = date.today().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE user_id=? AND session_date=? ORDER BY id",
            (user_id, session_date)
        ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in rows]

def get_recent_summaries(user_id: int, days: int = 7) -> list:
    since = (date.today() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT session_date, mood, topics, summary FROM summaries WHERE user_id=? AND session_date>=? ORDER BY session_date DESC",
            (user_id, since)
        ).fetchall()
    return [{"date": r[0], "mood": r[1], "topics": r[2], "summary": r[3]} for r in rows]

def get_day_messages(user_id: int, session_date: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE user_id=? AND session_date=? ORDER BY id",
            (user_id, session_date)
        ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in rows]

def save_summary(user_id: int, session_date: str, mood: int, topics: str, summary: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO summaries (user_id, session_date, mood, topics, summary)
            VALUES (?,?,?,?,?)
            ON CONFLICT(user_id, session_date) DO UPDATE SET
                mood=excluded.mood, topics=excluded.topics, summary=excluded.summary
        """, (user_id, session_date, mood, topics, summary))

def get_all_summaries(user_id: int) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT session_date, mood, topics, summary FROM summaries WHERE user_id=? ORDER BY session_date DESC",
            (user_id,)
        ).fetchall()
    return [{"date": r[0], "mood": r[1], "topics": r[2], "summary": r[3]} for r in rows]

def count_streak(user_id: int) -> int:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT session_date FROM messages WHERE user_id=? ORDER BY session_date DESC",
            (user_id,)
        ).fetchall()
    if not rows:
        return 0
    streak = 0
    check = date.today()
    for row in rows:
        d = date.fromisoformat(row[0])
        if d == check or d == check - timedelta(days=1):
            streak += 1
            check = d - timedelta(days=1)
        else:
            break
    return streak

def days_since_last_message(user_id: int) -> Optional[int]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(session_date) FROM messages WHERE user_id=?", (user_id,)
        ).fetchone()
    if row and row[0]:
        return (date.today() - date.fromisoformat(row[0])).days
    return None

# ─── СТИЛЬ ОБЩЕНИЯ ПО ВОЗРАСТУ/ПОЛУ ──────────────────────
def build_system_prompt(user: dict, current_time: str = "") -> str:
    age = user.get("age") or 0
    gender = user.get("gender") or "none"
    name = user.get("name", "")
    adult_mode = user.get("adult_mode", 0)
    mat_rule = "иногда используй матерные слова — только по ситуации, не в каждом сообщении. Как нормальный друг в неформальной обстановке." if adult_mode else "мат не используй никогда."

    # Стиль по возрасту
    if age <= 17:
        age_style = (
            "Пользователь подросток. Общайся на молодёжном языке, можно слэнг. "
            "Короткие фразы, понимаешь тему учёбы, родителей, первых отношений. "
            "Не поучай и не занудствуй ни в коем случае."
        )
    elif age <= 25:
        age_style = (
            "Пользователь молодой человек (студент/начало карьеры). "
            "Общайся как ровесник — по-простому, с юмором, понимаешь темы универа, "
            "тусовок, первой работы, отношений. Можно немного слэнга."
        )
    elif age <= 35:
        age_style = (
            "Пользователь взрослый (работает, возможно семья). "
            "Общайся уважительно но без официоза. Понимаешь темы карьеры, "
            "денег, отношений, усталости. Юмор уместен."
        )
    elif age <= 50:
        age_style = (
            "Пользователь зрелый человек. Общайся спокойно и по-человечески. "
            "Понимаешь темы семьи, здоровья, работы, детей. "
            "Без молодёжного слэнга, но и без занудства."
        )
    else:
        age_style = (
            "Пользователь старшего возраста. Общайся уважительно, тепло, без сленга. "
            "Понимаешь темы здоровья, детей/внуков, воспоминаний. "
            "Будь особенно внимателен и терпелив."
        )

    # Стиль по полу
    if gender == "male":
        gender_style = "Пользователь — парень/мужчина. Общайся как друг с другом, по-мужски."
    elif gender == "female":
        gender_style = "Пользователь — девушка/женщина. Будь внимательным и чутким, но не слащавым."
    else:
        gender_style = "Пол неизвестен — общайся нейтрально."

    base = f"""Ты — Мирон, друг пользователя {name} в Telegram. Не психолог и не коуч — просто близкий друг.

{age_style}
{gender_style}

Общие правила:
- Отвечай коротко и по-человечески, без занудства
- Юмор когда уместно, сарказм иногда — как настоящий друг
- В конце каждого ответа задавай ОДИН уточняющий вопрос
- Советы только если прямо просят
- Помни что говорил раньше и упоминай естественно
- Не используй эмодзи чаще одного на сообщение
- Не начинай ответ со слова "Привет" если уже общались сегодня
- Пиши на русском, разговорно
- Мат: {mat_rule}"""


    return base

# ─── ИИ ───────────────────────────────────────────────────
async def miron_reply(user_id: int, user_text: str) -> str:
    user = get_user(user_id)
    today_msgs = get_today_messages(user_id)
    recent = get_recent_summaries(user_id, 7)
    current_time = datetime.now().strftime("%H:%M")

    memory_block = ""
    if recent:
        memory_block = "\n\nПамять о прошлых разговорах:\n"
        for r in recent:
            memory_block += f"- {r['date']}: настроение {r['mood']}/10, темы: {r['topics']}. {r['summary']}\n"

    system = build_system_prompt(user, current_time) + memory_block
    history = today_msgs.copy()
    history.append({"role": "user", "content": user_text})

    response = await groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "system", "content": system}] + history,
        max_tokens=300,
        temperature=0.85
    )
    return response.choices[0].message.content.strip()

async def generate_summary(user_id: int, session_date: str):
    msgs = get_day_messages(user_id, session_date)
    if len(msgs) < 2:
        return
    convo = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in msgs])
    prompt = f"""Проанализируй разговор и верни только JSON без лишнего текста:
{{"mood": <1-10>, "topics": "<темы через запятую>", "summary": "<резюме 50-70 слов>"}}

Разговор:
{convo}"""
    try:
        r = await groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200, temperature=0.3
        )
        text = r.choices[0].message.content.strip().strip("```json").strip("```").strip()
        data = json.loads(text)
        save_summary(user_id, session_date, data["mood"], data["topics"], data["summary"])
    except Exception as e:
        log.error(f"Summary error: {e}")

# ─── FSM ───────────────────────────────────────────────────
class Onboarding(StatesGroup):
    waiting_name = State()
    waiting_age  = State()
    waiting_gender = State()
    waiting_time = State()

class Settings(StatesGroup):
    waiting_custom_time = State()

# ─── ХЭНДЛЕРЫ: ОНБОРДИНГ ──────────────────────────────────

@dp.message(Command("reset"))
async def cmd_reset(msg: Message, state: FSMContext):
    """Сброс профиля — начать заново"""
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE user_id=?", (msg.from_user.id,))
    await state.clear()
    await msg.answer(
        "Профиль сброшен. Начнём заново!\n\n"
        "Привет. Я Мирон.\n\n"
        "Буду писать тебе каждый вечер — спрашивать как прошёл день, "
        "слушать, иногда шутить. Не коуч и не психолог — просто друг.\n\n"
        "Как тебя зовут?",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Onboarding.waiting_name)

@dp.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    user = get_user(msg.from_user.id)
    if user:
        await msg.answer(
            f"Привет снова, {user['name']} 🙂\n\nЧё случилось, раз /start нажал?",
            reply_markup=main_kb()
        )
        return
    await msg.answer(
        "Привет. Я Мирон.\n\n"
        "Буду писать тебе каждый вечер — спрашивать как прошёл день, "
        "слушать, иногда шутить. Не коуч и не психолог — просто друг.\n\n"
        "Как тебя зовут?",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Onboarding.waiting_name)

@dp.message(Onboarding.waiting_name)
async def onboarding_name(msg: Message, state: FSMContext):
    name = msg.text.strip()
    await state.update_data(name=name)
    await msg.answer(f"Хорошо, {name}. Сколько тебе лет?")
    await state.set_state(Onboarding.waiting_age)

@dp.message(Onboarding.waiting_age)
async def onboarding_age(msg: Message, state: FSMContext):
    text = msg.text.strip()
    # Пробуем извлечь число
    age = None
    for word in text.split():
        if word.isdigit():
            age = int(word)
            break

    if not age or age < 10 or age > 100:
        await msg.answer("Напиши просто число, например: 24")
        return

    await state.update_data(age=age)

    # Подбираем приветствие под возраст
    if age <= 17:
        reaction = "Понял, молодой 😄"
    elif age <= 25:
        reaction = "Ок, свои люди."
    elif age <= 35:
        reaction = "Норм возраст."
    else:
        reaction = "Хорошо."

    await msg.answer(f"{reaction}\n\nТы парень или девушка?", reply_markup=gender_kb())
    await state.set_state(Onboarding.waiting_gender)

@dp.callback_query(Onboarding.waiting_gender, F.data.startswith("gender_"))
async def onboarding_gender(cb: CallbackQuery, state: FSMContext):
    gender = cb.data.replace("gender_", "")
    await state.update_data(gender=gender)
    data = await state.get_data()

    await cb.message.edit_text(
        f"Отлично. В какое время писать тебе вечером?"
    )
    await cb.message.answer("Выбери время:", reply_markup=time_kb())
    await state.set_state(Onboarding.waiting_time)
    await cb.answer()

@dp.callback_query(Onboarding.waiting_time, F.data.startswith("settime_"))
async def onboarding_time_cb(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    val = cb.data.replace("settime_", "")

    if val == "custom":
        await cb.message.edit_text("Напиши время в формате ЧЧ:ММ, например 22:30")
        await state.set_state(Onboarding.waiting_time)
        await state.update_data(waiting_custom=True)
        await cb.answer()
        return

    upsert_user(
        cb.from_user.id,
        cb.from_user.username,
        data["name"],
        data["age"],
        data["gender"],
        val
    )
    await state.clear()

    name = data["name"]
    age = data["age"]
    gender = data["gender"]

    if gender == "male":
        g_text = "парень"
    elif gender == "female":
        g_text = "девушка"
    else:
        g_text = ""

    await cb.message.edit_text(f"Буду писать в {val}. Всё запомнил.")
    await cb.message.answer(
        f"Ну и отлично, {name}. Теперь я знаю что тебе {age} лет{', ты ' + g_text if g_text else ''}.\n\n"
        f"Как сегодня прошёл день?",
        reply_markup=main_kb()
    )
    await cb.answer()

@dp.message(Onboarding.waiting_time)
async def onboarding_time_text(msg: Message, state: FSMContext):
    data = await state.get_data()
    text = msg.text.strip()
    if ":" not in text:
        await msg.answer("Формат: ЧЧ:ММ, например 22:30")
        return
    notify_time = text[:5]
    upsert_user(
        msg.from_user.id,
        msg.from_user.username,
        data.get("name", ""),
        data.get("age", 0),
        data.get("gender", "none"),
        notify_time
    )
    await state.clear()
    name = data.get("name", "")
    await msg.answer(
        f"Буду в {notify_time}. Как сегодня прошёл день, {name}?",
        reply_markup=main_kb()
    )

# ─── ХЭНДЛЕРЫ: КНОПКИ МЕНЮ ────────────────────────────────
@dp.message(F.text == "📊 Статистика")
async def btn_stats(msg: Message):
    summaries = get_all_summaries(msg.from_user.id)
    streak = count_streak(msg.from_user.id)

    if not summaries:
        await msg.answer("Пока нет данных — поговори со мной хотя бы пару дней 🙂")
        return

    moods = [s["mood"] for s in summaries if s["mood"]]
    avg_mood = sum(moods) / len(moods) if moods else 0
    best = max(summaries, key=lambda x: x["mood"] or 0)
    worst = min(summaries, key=lambda x: x["mood"] or 10)

    all_topics = []
    for s in summaries:
        if s["topics"]:
            all_topics.extend([t.strip() for t in s["topics"].split(",")])
    top_topics = Counter(all_topics).most_common(3)
    topics_str = ", ".join([t[0] for t in top_topics]) if top_topics else "—"

    user = get_user(msg.from_user.id)
    paused = ""
    if user and user.get("paused_until"):
        paused = f"\n⏸ Пауза до: {user['paused_until']}"

    await msg.answer(
        f"📊 Статистика\n\n"
        f"💬 Разговоров: {len(summaries)}\n"
        f"🔥 Стрик: {streak} дней подряд\n"
        f"😐 Среднее настроение: {avg_mood:.1f}/10\n\n"
        f"😊 Лучший день: {best['date']} ({best['mood']}/10)\n"
        f"😔 Тяжёлый день: {worst['date']} ({worst['mood']}/10)\n\n"
        f"🏷 Топ темы: {topics_str}"
        f"{paused}"
    )

@dp.message(F.text == "😊 Оценить день")
async def btn_mood(msg: Message):
    hour = datetime.now().hour
    if hour < 14:
        prefix = f"Сейчас только {datetime.now().strftime('%H:%M')}, день ещё не закончился — но ладно, как настроение пока?"
    elif hour < 18:
        prefix = "День ещё идёт, но уже можно прикинуть — как ощущения?"
    else:
        prefix = "Как день в целом?"
    await msg.answer(prefix, reply_markup=mood_kb())

@dp.message(F.text == "⏰ Время уведомлений")
async def btn_time(msg: Message):
    user = get_user(msg.from_user.id)
    current = user["notify_time"] if user else "21:00"
    await msg.answer(f"Сейчас стоит {current}. Выбери новое время:", reply_markup=time_kb())

@dp.message(F.text == "⏸ Пауза")
async def btn_pause(msg: Message):
    await msg.answer("На сколько дней поставить паузу?", reply_markup=pause_kb())

# ─── КОЛБЭКИ ──────────────────────────────────────────────
@dp.callback_query(F.data.startswith("mood_"))
async def mood_cb(cb: CallbackQuery):
    mood = int(cb.data.split("_")[1])
    today = date.today().isoformat()
    existing = get_day_messages(cb.from_user.id, today)
    if not existing:
        save_message(cb.from_user.id, "user", f"Быстрая оценка дня: {mood}/10", today)
    phrases = {
        1: "Понял. Тяжёло. Что случилось?",
        3: "Не лучший день. Что-то конкретное или просто так?",
        5: "Серединка. Ничего особого или что-то не то?",
        7: "Неплохо. Что порадовало?",
        9: "О, хороший день! Что было?",
    }
    await cb.message.edit_text(f"Настроение {mood}/10\n\n{phrases.get(mood, 'Понял.')}")
    await cb.answer()

@dp.callback_query(F.data.startswith("settime_"))
async def settime_cb(cb: CallbackQuery, state: FSMContext):
    val = cb.data.replace("settime_", "")
    if val == "custom":
        await cb.message.edit_text("Напиши время в формате ЧЧ:ММ, например 22:30")
        await state.set_state(Settings.waiting_custom_time)
        await cb.answer()
        return
    with get_conn() as conn:
        conn.execute("UPDATE users SET notify_time=? WHERE user_id=?", (val, cb.from_user.id))
    await cb.message.edit_text(f"Готово, буду писать в {val} 👍")
    await cb.answer()

@dp.message(Settings.waiting_custom_time)
async def custom_time_input(msg: Message, state: FSMContext):
    text = msg.text.strip()
    if ":" not in text or len(text) < 4:
        await msg.answer("Формат: ЧЧ:ММ, например 22:30")
        return
    new_time = text[:5]
    with get_conn() as conn:
        conn.execute("UPDATE users SET notify_time=? WHERE user_id=?", (new_time, msg.from_user.id))
    await state.clear()
    await msg.answer(f"Готово, буду писать в {new_time} 👍", reply_markup=main_kb())

@dp.callback_query(F.data.startswith("pause_"))
async def pause_cb(cb: CallbackQuery):
    val = cb.data.replace("pause_", "")
    if val == "cancel":
        await cb.message.edit_text("Ок, пауза не нужна.")
        await cb.answer()
        return
    days = int(val)
    until = (date.today() + timedelta(days=days)).isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE users SET paused_until=? WHERE user_id=?", (until, cb.from_user.id))
    await cb.message.edit_text(f"Хорошо, {days} дней не беспокою. Если захочешь раньше — просто напиши.")
    await cb.answer()


# ─── РЕЖИМ 18+ ────────────────────────────────────────────
def adult_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, мне есть 18 лет", callback_data="adult_confirm"),
            InlineKeyboardButton(text="❌ Нет", callback_data="adult_cancel"),
        ]
    ])

@dp.message(F.text == "🔞 Режим 18+")
async def btn_adult(msg: Message):
    user = get_user(msg.from_user.id)
    if not user:
        return
    if user.get("adult_mode"):
        # Выключаем без подтверждения
        with get_conn() as conn:
            conn.execute("UPDATE users SET adult_mode=0 WHERE user_id=?", (msg.from_user.id,))
        await msg.answer("Режим 18+ выключен. Мат убран.")
    else:
        await msg.answer(
            "Режим 18+ добавляет нецензурную лексику в общение — по ситуации, не в каждом сообщении.\n\n"
            "Подтверди что тебе есть 18 лет:",
            reply_markup=adult_confirm_kb()
        )

@dp.callback_query(F.data == "adult_confirm")
async def adult_confirm_cb(cb: CallbackQuery):
    with get_conn() as conn:
        conn.execute("UPDATE users SET adult_mode=1 WHERE user_id=?", (cb.from_user.id,))
    await cb.message.edit_text("Режим 18+ включён. Мирон будет материться иногда, как нормальный друг 😄")
    await cb.answer()

@dp.callback_query(F.data == "adult_cancel")
async def adult_cancel_cb(cb: CallbackQuery):
    await cb.message.edit_text("Понял, режим не включаем.")
    await cb.answer()

# ─── ОСНОВНОЙ ХЭНДЛЕР ─────────────────────────────────────
@dp.message(F.text)
async def handle_message(msg: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        return

    user = get_user(msg.from_user.id)
    if not user:
        await msg.answer("Напиши /start чтобы познакомиться.")
        return

    save_message(msg.from_user.id, "user", msg.text)
    await bot.send_chat_action(msg.chat.id, "typing")

    try:
        reply = await miron_reply(msg.from_user.id, msg.text)
    except Exception as e:
        log.error(f"Groq error: {e}")
        reply = "Что-то у меня завис мозг. Повтори?"

    save_message(msg.from_user.id, "assistant", reply)
    await msg.answer(reply)

# ─── ВЕЧЕРНИЙ ПЛАНИРОВЩИК ─────────────────────────────────
async def evening_notifier():
    while True:
        now = datetime.now().strftime("%H:%M")
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        with get_conn() as conn:
            users = conn.execute(
                "SELECT user_id, name, notify_time, paused_until FROM users WHERE is_active=1"
            ).fetchall()

        for user_id, name, notify_time, paused_until in users:
            if paused_until and date.today() <= date.fromisoformat(paused_until):
                continue
            if notify_time != now:
                continue
            with get_conn() as conn:
                already = conn.execute(
                    "SELECT id FROM messages WHERE user_id=? AND session_date=? AND role='assistant'",
                    (user_id, today)
                ).fetchone()
            if already:
                continue

            asyncio.create_task(generate_summary(user_id, yesterday))

            days_absent = days_since_last_message(user_id)
            if days_absent and days_absent >= 2:
                greeting = f"{name}, всё норм? Уже {days_absent} дня не пишешь."
            else:
                greetings = [
                    f"Эй, {name}. Как прошёл день?",
                    f"{name}, ну как там?",
                    f"Привет. Чё сегодня было?",
                    f"{name}, день закончился — расскажи.",
                ]
                greeting = random.choice(greetings)

            try:
                await bot.send_message(user_id, greeting)
                save_message(user_id, "assistant", greeting)
                log.info(f"Notified {user_id}")
            except Exception as e:
                log.error(f"Notify failed {user_id}: {e}")

        await asyncio.sleep(60)

# ─── ЗАПУСК ────────────────────────────────────────────────
async def main():
    init_db()
    log.info("Miron bot starting...")
    asyncio.create_task(evening_notifier())
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
