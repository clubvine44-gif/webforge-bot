import asyncio
import logging
import sqlite3
import json
from datetime import datetime, date, timedelta
from typing import Optional
from groq import AsyncGroq
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
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

# ─── БАЗА ДАННЫХ ───────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            name        TEXT,
            notify_time TEXT DEFAULT '21:00',
            is_active   INTEGER DEFAULT 1,
            paused_until TEXT,
            registered_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            role        TEXT,
            content     TEXT,
            session_date TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS summaries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            session_date TEXT,
            mood        INTEGER,
            topics      TEXT,
            summary     TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, session_date)
        );
    """)
    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect(DB_PATH)

def get_user(user_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            cols = [d[0] for d in conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).description]
            return dict(zip(cols, row))
    return None

def upsert_user(user_id: int, username: str, name: str, notify_time: str = "21:00"):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (user_id, username, name, notify_time)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, name=excluded.name
        """, (user_id, username or "", name, notify_time))

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
            ON CONFLICT(user_id, session_date) DO UPDATE SET mood=excluded.mood, topics=excluded.topics, summary=excluded.summary
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
            "SELECT MAX(session_date) FROM messages WHERE user_id=?",
            (user_id,)
        ).fetchone()
    if row and row[0]:
        last = date.fromisoformat(row[0])
        return (date.today() - last).days
    return None

# ─── ХАРАКТЕР МИРОНА ───────────────────────────────────────
MIRON_SYSTEM = """Ты — Мирон, друг пользователя в Telegram. Не психолог и не коуч — просто близкий друг.

Правила:
- Отвечай коротко и по-человечески, без занудства
- Юмор когда уместно, сарказм иногда — как настоящий друг
- В конце каждого ответа задавай ОДИН уточняющий вопрос
- Советы только если прямо просят
- Помни что говорил раньше и упоминай естественно
- Не используй эмодзи чаще одного на сообщение
- Не начинай ответ со слова "Привет" если уже общались сегодня
- Пиши на русском, разговорно"""

async def miron_reply(user_id: int, user_text: str, user_name: str) -> str:
    today = date.today().isoformat()
    today_msgs = get_today_messages(user_id)
    recent = get_recent_summaries(user_id, 7)

    # Собираем контекст из резюме прошлых дней
    memory_block = ""
    if recent:
        memory_block = "\n\nПамять о прошлых разговорах:\n"
        for r in recent:
            memory_block += f"- {r['date']}: настроение {r['mood']}/10, темы: {r['topics']}. {r['summary']}\n"

    system = MIRON_SYSTEM + memory_block

    # История сегодняшнего разговора
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
    """Генерируем резюме дня после разговора"""
    msgs = get_day_messages(user_id, session_date)
    if len(msgs) < 2:
        return

    convo = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in msgs])

    prompt = f"""Проанализируй этот разговор и верни JSON:
{{
  "mood": <число 1-10 насколько хорошо прошёл день>,
  "topics": "<3-4 темы через запятую>",
  "summary": "<резюме 50-70 токенов: что случилось, как себя чувствовал>"
}}

Только JSON, никакого текста вокруг.

Разговор:
{convo}"""

    try:
        r = await groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3
        )
        text = r.choices[0].message.content.strip()
        text = text.strip("```json").strip("```").strip()
        data = json.loads(text)
        save_summary(user_id, session_date, data["mood"], data["topics"], data["summary"])
        log.info(f"Summary saved for user {user_id} date {session_date}")
    except Exception as e:
        log.error(f"Summary generation failed: {e}")

# ─── FSM ───────────────────────────────────────────────────
class Onboarding(StatesGroup):
    waiting_name = State()
    waiting_time = State()

# ─── ХЭНДЛЕРЫ ──────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    user = get_user(msg.from_user.id)
    if user:
        await msg.answer(f"Ну привет снова, {user['name']} 🙂\n\nЧё случилось, раз /start нажал?")
        return

    await msg.answer(
        "Привет. Я Мирон — буду писать тебе каждый вечер, спрашивать как прошёл день.\n\n"
        "Не коуч, не психолог — просто друг.\n\n"
        "Как тебя зовут?"
    )
    await state.set_state(Onboarding.waiting_name)

@dp.message(Onboarding.waiting_name)
async def onboarding_name(msg: Message, state: FSMContext):
    name = msg.text.strip()
    await state.update_data(name=name)
    await msg.answer(
        f"Хорошо, {name}.\n\n"
        "В какое время мне писать тебе вечером? (например: 21:00)\n"
        "По умолчанию 21:00 — просто напиши + если ок."
    )
    await state.set_state(Onboarding.waiting_time)

@dp.message(Onboarding.waiting_time)
async def onboarding_time(msg: Message, state: FSMContext):
    data = await state.get_data()
    name = data["name"]
    text = msg.text.strip()

    notify_time = "21:00"
    if text != "+" and ":" in text:
        notify_time = text[:5]

    upsert_user(msg.from_user.id, msg.from_user.username, name, notify_time)
    await state.clear()

    await msg.answer(
        f"Договорились. Буду писать в {notify_time}.\n\n"
        f"Ну, {name}, как сегодня прошёл день?"
    )

@dp.message(Command("stats"))
async def cmd_stats(msg: Message):
    user = get_user(msg.from_user.id)
    if not user:
        await msg.answer("Сначала /start")
        return

    summaries = get_all_summaries(msg.from_user.id)
    streak = count_streak(msg.from_user.id)

    if not summaries:
        await msg.answer("Пока нет данных — поговори со мной хотя бы пару дней 🙂")
        return

    moods = [s["mood"] for s in summaries if s["mood"]]
    avg_mood = sum(moods) / len(moods) if moods else 0
    best = max(summaries, key=lambda x: x["mood"] or 0)
    worst = min(summaries, key=lambda x: x["mood"] or 10)

    # Топ темы
    all_topics = []
    for s in summaries:
        if s["topics"]:
            all_topics.extend([t.strip() for t in s["topics"].split(",")])
    from collections import Counter
    top_topics = Counter(all_topics).most_common(3)
    topics_str = ", ".join([t[0] for t in top_topics]) if top_topics else "—"

    text = (
        f"📊 Статистика за всё время\n\n"
        f"💬 Разговоров: {len(summaries)}\n"
        f"🔥 Стрик: {streak} дней подряд\n"
        f"😐 Среднее настроение: {avg_mood:.1f}/10\n\n"
        f"😊 Лучший день: {best['date']} ({best['mood']}/10)\n"
        f"😔 Тяжёлый день: {worst['date']} ({worst['mood']}/10)\n\n"
        f"🏷 Топ темы: {topics_str}"
    )
    await msg.answer(text)

@dp.message(Command("time"))
async def cmd_time(msg: Message):
    parts = msg.text.split()
    if len(parts) < 2 or ":" not in parts[1]:
        await msg.answer("Укажи время: /time 21:30")
        return

    new_time = parts[1][:5]
    with get_conn() as conn:
        conn.execute("UPDATE users SET notify_time=? WHERE user_id=?", (new_time, msg.from_user.id))
    await msg.answer(f"Ок, буду писать в {new_time} 👍")

@dp.message(Command("pause"))
async def cmd_pause(msg: Message):
    until = (date.today() + timedelta(days=7)).isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE users SET paused_until=? WHERE user_id=?", (until, msg.from_user.id))
    await msg.answer("Хорошо, неделю не беспокою. Если раньше захочешь — просто напиши мне.")

@dp.message(Command("mood"))
async def cmd_mood(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="😫 1", callback_data="mood_1"),
            InlineKeyboardButton(text="😔 3", callback_data="mood_3"),
            InlineKeyboardButton(text="😐 5", callback_data="mood_5"),
            InlineKeyboardButton(text="🙂 7", callback_data="mood_7"),
            InlineKeyboardButton(text="😊 9", callback_data="mood_9"),
        ]
    ])
    await msg.answer("Как день в целом, по ощущениям?", reply_markup=kb)

@dp.callback_query(F.data.startswith("mood_"))
async def mood_cb(cb: CallbackQuery):
    mood = int(cb.data.split("_")[1])
    today = date.today().isoformat()
    # Сохраняем как краткий summary если нет разговора
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

@dp.message(F.text)
async def handle_message(msg: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        return  # FSM обрабатывает

    user = get_user(msg.from_user.id)
    if not user:
        await msg.answer("Напиши /start чтобы познакомиться.")
        return

    # Сохраняем сообщение пользователя
    save_message(msg.from_user.id, "user", msg.text)

    # Получаем ответ Мирона
    await bot.send_chat_action(msg.chat.id, "typing")
    try:
        reply = await miron_reply(msg.from_user.id, msg.text, user["name"])
    except Exception as e:
        log.error(f"Groq error: {e}")
        reply = "Что-то у меня завис мозг. Повтори?"

    # Сохраняем ответ
    save_message(msg.from_user.id, "assistant", reply)

    await msg.answer(reply)

# ─── НОЧНОЙ ПЛАНИРОВЩИК ────────────────────────────────────
async def evening_notifier():
    """Каждую минуту проверяем кому пора написать"""
    while True:
        now = datetime.now().strftime("%H:%M")
        today = date.today().isoformat()

        with get_conn() as conn:
            users = conn.execute(
                "SELECT user_id, name, notify_time, paused_until FROM users WHERE is_active=1",
            ).fetchall()

        for user_id, name, notify_time, paused_until in users:
            # Пауза
            if paused_until and date.today() <= date.fromisoformat(paused_until):
                continue

            if notify_time != now:
                continue

            # Уже писали сегодня?
            with get_conn() as conn:
                already = conn.execute(
                    "SELECT id FROM messages WHERE user_id=? AND session_date=? AND role='assistant'",
                    (user_id, today)
                ).fetchone()
            if already:
                continue

            # Генерируем резюме вчерашнего дня
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            asyncio.create_task(generate_summary(user_id, yesterday))

            # Проверяем давно ли не общались
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
                import random
                greeting = random.choice(greetings)

            try:
                await bot.send_message(user_id, greeting)
                save_message(user_id, "assistant", greeting)
                log.info(f"Evening notification sent to {user_id}")
            except Exception as e:
                log.error(f"Failed to notify {user_id}: {e}")

        await asyncio.sleep(60)

# ─── ЗАПУСК ────────────────────────────────────────────────
async def main():
    init_db()
    log.info("Miron bot starting...")
    asyncio.create_task(evening_notifier())
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
