import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import os

TOKEN = os.environ.get("BOT_TOKEN", "8678852008:AAGZeO7cKJWT1vNugKy8wkuII-wotKDZe70")
GROQ_KEY = os.environ.get("GROQ_KEY", "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")
MODEL = "llama-3.3-70b-versatile"
LYUDA_ID = 5679074450

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
dialog_history = {}

# ===== СОСТОЯНИЯ =====
class Order(StatesGroup):
    name = State()
    service = State()
    budget = State()

class TZ(StatesGroup):
    q1_business = State()    # Что за бизнес
    q2_product = State()     # Что нужно
    q3_goal = State()        # Цель сайта/бота
    q4_functions = State()   # Функции (запись, оплата, каталог и тд)
    q5_payment = State()     # Нужна онлайн-оплата
    q6_content = State()     # Есть ли тексты/фото/логотип
    q7_examples = State()    # Примеры сайтов которые нравятся
    q8_deadline = State()    # Сроки
    q9_budget = State()      # Бюджет
    q10_contacts = State()   # Контакт для связи
    q11_extra = State()      # Дополнительно — файлы, ссылки, пожелания

# ===== МЕНЮ =====
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Сайты", callback_data="info_sites"),
         InlineKeyboardButton(text="🤖 Боты с ИИ", callback_data="info_bots")],
        [InlineKeyboardButton(text="💰 Цены", callback_data="prices"),
         InlineKeyboardButton(text="📂 Примеры работ", callback_data="portfolio")],
        [InlineKeyboardButton(text="💬 Спросить ИИ-консультанта", callback_data="ask_ai")],
        [InlineKeyboardButton(text="📋 Составить ТЗ", callback_data="tz_start")],
        [InlineKeyboardButton(text="📝 Оставить заявку", callback_data="order")],
        [InlineKeyboardButton(text="👩 Менеджер Люда", url="https://t.me/LyudmilaVadimovna1")]
    ])

def back_btn():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Главное меню", callback_data="back_main")]
    ])

def after_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Составить ТЗ", callback_data="tz_start")],
        [InlineKeyboardButton(text="📝 Оставить заявку", callback_data="order")],
        [InlineKeyboardButton(text="💬 Спросить ИИ-консультанта", callback_data="ask_ai")],
        [InlineKeyboardButton(text="⬅ Главное меню", callback_data="back_main")]
    ])

def yes_no_btn(yes_cb, no_cb):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data=yes_cb),
         InlineKeyboardButton(text="❌ Нет", callback_data=no_cb)]
    ])

def cancel_btn():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="back_main")]
    ])

# ===== СИСТЕМНЫЙ ПРОМПТ =====
SYSTEM_PROMPT = (
    "Ты продающий консультант компании WebForge AI из Кисловодска. "
    "Твоя задача — заинтересовать клиента и подвести его к заявке. "
    "Отвечай конкретно, дружелюбно, по делу. Помни предыдущие сообщения и продолжай диалог.\n\n"
    "ЧТО МЫ ДЕЛАЕМ:\n"
    "- Лендинг от 5000 руб, срок 3 дня\n"
    "- Сайт-визитка от 5000 руб\n"
    "- Telegram-бот с ИИ от 10000 руб, срок 7-10 дней\n"
    "- Абонентка 1500-2500 руб/мес\n\n"
    "ПРИМЕРЫ НАШИХ РАБОТ:\n"
    "- Сайт салона красоты: https://clubvine44-gif.github.io/demo-salon-1\n"
    "- Сайт мастера маникюра: https://clubvine44-gif.github.io/salon-demo2/\n\n"
    "ПРАВИЛА — СОБЛЮДАЙ СТРОГО:\n"
    "1. НИКОГДА не используй * ** _ ` # — только обычный текст\n"
    "2. НИКОГДА не выдумывай клиентов, отзывы, названия компаний, кейсы. "
    "Если спрашивают про отзывы — скажи: мы молодая компания, наши работы можно посмотреть по ссылкам выше\n"
    "3. НИКОГДА не выдумывай телефоны, email, адреса, соцсети\n"
    "4. НИКОГДА не придумывай услуги которых нет в списке выше\n"
    "5. Если клиент интересуется — предлагай составить ТЗ или оставить заявку\n"
    "6. Если не знаешь ответа — направь к менеджеру @LyudmilaVadimovna1\n"
    "7. Отвечай коротко — максимум 5-6 предложений\n"
    "8. ТОЛЬКО русский язык. Никаких английских слов, иероглифов, странных символов. Пиши как живой человек, просто и тепло"
)

TZ_PROMPT = (
    "Ты технический менеджер компании WebForge AI. "
    "Тебе дали ответы клиента на вопросы для составления технического задания. "
    "Составь чёткое, структурированное ТЗ на разработку сайта или бота. "
    "Используй только факты из ответов клиента — ничего не выдумывай. "
    "Если информации не хватает по какому-то пункту — напиши 'уточнить у клиента'. "
    "Структура ТЗ:\n"
    "1. О бизнесе клиента\n"
    "2. Что нужно разработать\n"
    "3. Цель и задачи\n"
    "4. Функциональные требования\n"
    "5. Наличие материалов (тексты, фото, логотип)\n"
    "6. Примеры и референсы\n"
    "7. Сроки и бюджет\n"
    "8. Контакт клиента\n"
    "9. Дополнительные пожелания\n\n"
    "Пиши чётко, без воды. Только русский язык."
)

# ===== ИИ =====
async def call_ai(user_id: int, question: str) -> str:
    if user_id not in dialog_history:
        dialog_history[user_id] = []
    dialog_history[user_id].append({"role": "user", "content": question})
    if len(dialog_history[user_id]) > 10:
        dialog_history[user_id] = dialog_history[user_id][-10:]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
                json={
                    "model": MODEL,
                    "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + dialog_history[user_id],
                    "max_tokens": 400
                },
                timeout=aiohttp.ClientTimeout(total=25)
            ) as r:
                data = await r.json()
                answer = data["choices"][0]["message"]["content"]
                for ch in ["*", "_", "`", "#"]:
                    answer = answer.replace(ch, "")
                answer = answer.strip()
                dialog_history[user_id].append({"role": "assistant", "content": answer})
                return answer
    except Exception:
        return "Не удалось получить ответ. Напишите менеджеру: @LyudmilaVadimovna1"

async def generate_tz(answers: dict) -> str:
    text = "Ответы клиента на вопросы для ТЗ:\n\n"
    labels = {
        "business": "Бизнес клиента",
        "product": "Что нужно разработать",
        "goal": "Цель",
        "functions": "Необходимые функции",
        "payment": "Онлайн-оплата",
        "content": "Наличие материалов",
        "examples": "Примеры/референсы",
        "deadline": "Сроки",
        "budget": "Бюджет",
        "contacts": "Контакт",
        "extra": "Дополнительно",
    }
    for key, label in labels.items():
        val = answers.get(key, "не указано")
        text += f"{label}: {val}\n"

    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": TZ_PROMPT},
                        {"role": "user", "content": text}
                    ],
                    "max_tokens": 1000
                },
                timeout=aiohttp.ClientTimeout(total=40)
            ) as r:
                data = await r.json()
                result = data["choices"][0]["message"]["content"]
                for ch in ["*", "_", "`", "#"]:
                    result = result.replace(ch, "")
                return result.strip()
    except Exception:
        return text

# ===== ОСНОВНЫЕ ХЕНДЛЕРЫ =====
@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    dialog_history.pop(message.from_user.id, None)
    await message.answer(
        "Привет! Я бот компании WebForge AI.\n\n"
        "Мы из Кисловодска и делаем сайты и Telegram-ботов для малого бизнеса под ключ.\n\n"
        "Выберите раздел или задайте любой вопрос нашему ИИ-консультанту:",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "back_main")
async def back_main(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("Главное меню:", reply_markup=main_menu())
    await call.answer()

@dp.callback_query(F.data == "info_sites")
async def info_sites(call: types.CallbackQuery):
    await call.message.answer(
        "Сайты под ключ:\n\n"
        "Лендинг — одностраничный продающий сайт, от 5000 руб, 3 дня\n"
        "Сайт-визитка — многостраничный сайт, от 5000 руб\n\n"
        "Все сайты адаптированы под мобильные. Делаем для салонов, кафе, гостевых домов, мастеров.",
        reply_markup=after_menu()
    )
    await call.answer()

@dp.callback_query(F.data == "info_bots")
async def info_bots(call: types.CallbackQuery):
    await call.message.answer(
        "Telegram-боты с ИИ:\n\n"
        "Бот работает 24/7 — отвечает на вопросы, принимает заявки, консультирует клиентов.\n\n"
        "Стоимость от 10000 руб, срок 7-10 дней.",
        reply_markup=after_menu()
    )
    await call.answer()

@dp.callback_query(F.data == "prices")
async def prices(call: types.CallbackQuery):
    await call.message.answer(
        "Наши цены:\n\n"
        "Лендинг — от 5000 руб, срок 3 дня\n"
        "Сайт-визитка — от 5000 руб\n"
        "Бот с ИИ — от 10000 руб, срок 7-10 дней\n\n"
        "Абонентское обслуживание: 1500-2500 руб/мес",
        reply_markup=after_menu()
    )
    await call.answer()

@dp.callback_query(F.data == "portfolio")
async def portfolio(call: types.CallbackQuery):
    await call.message.answer(
        "Примеры наших работ:\n\n"
        "Демо-сайт для салона красоты 1:\nhttps://clubvine44-gif.github.io/demo-salon-1\n\n"
        "Демо-сайт для мастера маникюра:\nhttps://clubvine44-gif.github.io/salon-demo2/",
        reply_markup=after_menu()
    )
    await call.answer()

@dp.callback_query(F.data == "ask_ai")
async def ask_ai_prompt(call: types.CallbackQuery):
    await call.message.answer(
        "Задайте любой вопрос — ИИ-консультант ответит:",
        reply_markup=back_btn()
    )
    await call.answer()

# ===== ЗАЯВКА =====
@dp.callback_query(F.data == "order")
async def order_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(Order.name)
    await call.message.answer(
        "Оставьте заявку. Шаг 1 из 3:\n\nКак вас зовут?",
        reply_markup=cancel_btn()
    )
    await call.answer()

@dp.message(Order.name)
async def order_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(Order.service)
    await message.answer(
        f"Отлично, {message.text}! Шаг 2 из 3:\n\nЧто вас интересует?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Сайт", callback_data="svc_site")],
            [InlineKeyboardButton(text="Бот с ИИ", callback_data="svc_bot")],
            [InlineKeyboardButton(text="Сайт + бот", callback_data="svc_both")]
        ])
    )

@dp.callback_query(F.data.startswith("svc_"), Order.service)
async def order_service(call: types.CallbackQuery, state: FSMContext):
    svc_map = {"svc_site": "Сайт", "svc_bot": "Бот с ИИ", "svc_both": "Сайт + бот"}
    await state.update_data(service=svc_map.get(call.data, call.data))
    await state.set_state(Order.budget)
    await call.message.answer(
        "Шаг 3 из 3:\n\nКакой примерный бюджет?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="до 5000 руб", callback_data="bgt_5k")],
            [InlineKeyboardButton(text="5000-15000 руб", callback_data="bgt_15k")],
            [InlineKeyboardButton(text="более 15000 руб", callback_data="bgt_top")]
        ])
    )
    await call.answer()

@dp.callback_query(F.data.startswith("bgt_"), Order.budget)
async def order_budget(call: types.CallbackQuery, state: FSMContext):
    bgt_map = {"bgt_5k": "до 5000 руб", "bgt_15k": "5000-15000 руб", "bgt_top": "более 15000 руб"}
    data = await state.get_data()
    budget = bgt_map.get(call.data, call.data)
    await state.clear()

    user = call.from_user
    username = f"@{user.username}" if user.username else "без юзернейма"
    user_link = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'

    summary = (
        "📩 Новая заявка!\n\n"
        f"Имя: {data.get('name')}\n"
        f"Услуга: {data.get('service')}\n"
        f"Бюджет: {budget}\n\n"
        f"👤 Telegram: {username}\n"
        f"🔗 Написать: {user_link}"
    )
    try:
        await bot.send_message(LYUDA_ID, summary, parse_mode="HTML")
    except Exception:
        pass
    await call.message.answer(
        "Заявка принята! Менеджер Люда свяжется с вами в ближайшее время.\n\nИли напишите сразу: @LyudmilaVadimovna1",
        reply_markup=main_menu()
    )
    await call.answer()

# ===== ТЗ =====
@dp.callback_query(F.data == "tz_start")
async def tz_start(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(TZ.q1_business)
    await call.message.answer(
        "Отлично! Составим техническое задание вместе.\n\n"
        "Это займёт 5-7 минут. По итогу я пришлю готовое ТЗ менеджеру и вам.\n\n"
        "Вопрос 1 из 11:\n\nРасскажите о вашем бизнесе. Что вы делаете, в каком городе, как называется?",
        reply_markup=cancel_btn()
    )
    await call.answer()

@dp.message(TZ.q1_business)
async def tz_q1(message: types.Message, state: FSMContext):
    await state.update_data(business=message.text)
    await state.set_state(TZ.q2_product)
    await message.answer(
        "Вопрос 2 из 11:\n\nЧто нужно разработать?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Сайт", callback_data="tz_p_site")],
            [InlineKeyboardButton(text="Telegram-бот", callback_data="tz_p_bot")],
            [InlineKeyboardButton(text="Сайт + бот", callback_data="tz_p_both")],
            [InlineKeyboardButton(text="Пока не знаю", callback_data="tz_p_unknown")]
        ])
    )

@dp.callback_query(F.data.startswith("tz_p_"), TZ.q2_product)
async def tz_q2(call: types.CallbackQuery, state: FSMContext):
    mp = {"tz_p_site": "Сайт", "tz_p_bot": "Telegram-бот", "tz_p_both": "Сайт + бот", "tz_p_unknown": "Пока не определились"}
    await state.update_data(product=mp.get(call.data, call.data))
    await state.set_state(TZ.q3_goal)
    await call.message.answer(
        "Вопрос 3 из 11:\n\nКакая главная цель? Что должны делать клиенты на сайте/в боте?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Записываться на услугу", callback_data="tz_g_booking")],
            [InlineKeyboardButton(text="Узнать о бизнесе и связаться", callback_data="tz_g_info")],
            [InlineKeyboardButton(text="Заказывать товары/услуги", callback_data="tz_g_order")],
            [InlineKeyboardButton(text="Несколько целей — напишу сам", callback_data="tz_g_custom")]
        ])
    )
    await call.answer()

@dp.callback_query(F.data.startswith("tz_g_"), TZ.q3_goal)
async def tz_q3_btn(call: types.CallbackQuery, state: FSMContext):
    mp = {
        "tz_g_booking": "Запись на услугу",
        "tz_g_info": "Информация о бизнесе и контакт",
        "tz_g_order": "Заказ товаров/услуг",
        "tz_g_custom": "Несколько целей — уточнить"
    }
    if call.data == "tz_g_custom":
        await call.message.answer("Опишите своими словами что должны делать клиенты:")
        await call.answer()
        return
    await state.update_data(goal=mp.get(call.data))
    await state.set_state(TZ.q4_functions)
    await call.message.answer(
        "Вопрос 4 из 11:\n\nКакие функции нужны? Выберите всё подходящее и напишите одним сообщением.\n\n"
        "Например: онлайн-запись, каталог услуг с ценами, галерея фото, отзывы, форма обратной связи, чат-бот, корзина и оплата, личный кабинет, другое.",
        reply_markup=cancel_btn()
    )
    await call.answer()

@dp.message(TZ.q3_goal)
async def tz_q3_text(message: types.Message, state: FSMContext):
    await state.update_data(goal=message.text)
    await state.set_state(TZ.q4_functions)
    await message.answer(
        "Вопрос 4 из 11:\n\nКакие функции нужны? Напишите всё что важно.\n\n"
        "Например: онлайн-запись, каталог услуг с ценами, галерея фото, отзывы, форма обратной связи, чат-бот, корзина и оплата, личный кабинет.",
        reply_markup=cancel_btn()
    )

@dp.message(TZ.q4_functions)
async def tz_q4(message: types.Message, state: FSMContext):
    await state.update_data(functions=message.text)
    await state.set_state(TZ.q5_payment)
    await message.answer(
        "Вопрос 5 из 11:\n\nНужна ли онлайн-оплата прямо на сайте/в боте?",
        reply_markup=yes_no_btn("tz_pay_yes", "tz_pay_no")
    )

@dp.callback_query(F.data.in_({"tz_pay_yes", "tz_pay_no"}), TZ.q5_payment)
async def tz_q5(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(payment="Да" if call.data == "tz_pay_yes" else "Нет")
    await state.set_state(TZ.q6_content)
    await call.message.answer(
        "Вопрос 6 из 11:\n\nЕсть ли у вас готовые материалы?\n\n"
        "Напишите что есть: тексты, фото, логотип, прайс-лист. Или скажите что нужно сделать с нуля.",
        reply_markup=cancel_btn()
    )
    await call.answer()

@dp.message(TZ.q6_content)
async def tz_q6(message: types.Message, state: FSMContext):
    # Принимаем текст, фото, документы, ссылки
    if message.photo:
        await state.update_data(content=f"Прикрепил фото (file_id: {message.photo[-1].file_id})")
    elif message.document:
        await state.update_data(content=f"Прикрепил файл: {message.document.file_name}")
    else:
        await state.update_data(content=message.text)
    await state.set_state(TZ.q7_examples)
    await message.answer(
        "Вопрос 7 из 11:\n\nЕсть ли сайты или примеры которые вам нравятся?\n\n"
        "Скиньте ссылки или опишите стиль (строгий, яркий, минимализм). Если нет — так и напишите.",
        reply_markup=cancel_btn()
    )

@dp.message(TZ.q7_examples)
async def tz_q7(message: types.Message, state: FSMContext):
    await state.update_data(examples=message.text or "Не указано")
    await state.set_state(TZ.q8_deadline)
    await message.answer(
        "Вопрос 8 из 11:\n\nКакие сроки?\n\nКогда нужно запустить проект?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Как можно быстрее", callback_data="tz_d_asap")],
            [InlineKeyboardButton(text="В течение недели", callback_data="tz_d_week")],
            [InlineKeyboardButton(text="В течение месяца", callback_data="tz_d_month")],
            [InlineKeyboardButton(text="Сроки гибкие", callback_data="tz_d_flex")]
        ])
    )

@dp.callback_query(F.data.startswith("tz_d_"), TZ.q8_deadline)
async def tz_q8(call: types.CallbackQuery, state: FSMContext):
    mp = {"tz_d_asap": "Как можно быстрее", "tz_d_week": "В течение недели", "tz_d_month": "В течение месяца", "tz_d_flex": "Сроки гибкие"}
    await state.update_data(deadline=mp.get(call.data))
    await state.set_state(TZ.q9_budget)
    await call.message.answer(
        "Вопрос 9 из 11:\n\nКакой бюджет на разработку?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="до 5000 руб", callback_data="tz_b_5k")],
            [InlineKeyboardButton(text="5000-10000 руб", callback_data="tz_b_10k")],
            [InlineKeyboardButton(text="10000-20000 руб", callback_data="tz_b_20k")],
            [InlineKeyboardButton(text="более 20000 руб", callback_data="tz_b_top")],
            [InlineKeyboardButton(text="Обсудим", callback_data="tz_b_discuss")]
        ])
    )
    await call.answer()

@dp.callback_query(F.data.startswith("tz_b_"), TZ.q9_budget)
async def tz_q9(call: types.CallbackQuery, state: FSMContext):
    mp = {"tz_b_5k": "до 5000 руб", "tz_b_10k": "5000-10000 руб", "tz_b_20k": "10000-20000 руб", "tz_b_top": "более 20000 руб", "tz_b_discuss": "Обсудим"}
    await state.update_data(budget=mp.get(call.data))
    await state.set_state(TZ.q10_contacts)
    await call.message.answer(
        "Вопрос 10 из 11:\n\nКак с вами связаться? Укажите телефон, Telegram или другой удобный способ.",
        reply_markup=cancel_btn()
    )
    await call.answer()

@dp.message(TZ.q10_contacts)
async def tz_q10(message: types.Message, state: FSMContext):
    await state.update_data(contacts=message.text)
    await state.set_state(TZ.q11_extra)
    await message.answer(
        "Вопрос 11 из 11:\n\nЕсть ли дополнительные пожелания, файлы, ссылки или что-то важное что хотите добавить?\n\n"
        "Можете прикрепить фото, документы, ссылки. Если нечего — напишите 'нет'.",
        reply_markup=cancel_btn()
    )

@dp.message(TZ.q11_extra)
async def tz_q11(message: types.Message, state: FSMContext):
    # Принимаем любой тип контента
    if message.photo:
        extra = f"Прикрепил фото (file_id: {message.photo[-1].file_id})"
    elif message.document:
        extra = f"Прикрепил файл: {message.document.file_name}"
    elif message.text and message.text.lower() in ["нет", "не", "-", "."]:
        extra = "Нет дополнений"
    else:
        extra = message.text or "Нет дополнений"

    await state.update_data(extra=extra)
    data = await state.get_data()
    await state.clear()

    await message.answer("Отлично! Генерирую ТЗ, подождите 10-15 секунд... ⏳")

    # Генерируем ТЗ через ИИ
    tz_text = await generate_tz(data)

    user = message.from_user
    username = f"@{user.username}" if user.username else "без юзернейма"
    user_link = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'

    # Отправляем Люде
    lyuda_msg = (
        f"📋 Новое ТЗ от клиента!\n\n"
        f"👤 Telegram: {username}\n"
        f"🔗 Написать: {user_link}\n\n"
        f"{tz_text}"
    )
    try:
        # Разбиваем если слишком длинное
        if len(lyuda_msg) > 4000:
            await bot.send_message(LYUDA_ID, lyuda_msg[:4000], parse_mode="HTML")
            await bot.send_message(LYUDA_ID, lyuda_msg[4000:])
        else:
            await bot.send_message(LYUDA_ID, lyuda_msg, parse_mode="HTML")
    except Exception:
        pass

    # Отправляем клиенту
    client_msg = f"Ваше техническое задание готово:\n\n{tz_text}\n\nМенеджер Люда свяжется с вами в ближайшее время. Или напишите сразу: @LyudmilaVadimovna1"
    if len(client_msg) > 4000:
        await message.answer(client_msg[:4000])
        await message.answer(client_msg[4000:], reply_markup=main_menu())
    else:
        await message.answer(client_msg, reply_markup=main_menu())

# ===== СВОБОДНЫЙ ТЕКСТ =====
@dp.message()
async def free_text(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        return
    await message.answer("Ищу ответ, подождите секунду...")
    answer = await call_ai(message.from_user.id, message.text)
    await message.answer(
        answer,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Составить ТЗ", callback_data="tz_start")],
            [InlineKeyboardButton(text="📝 Оставить заявку", callback_data="order")],
            [InlineKeyboardButton(text="Главное меню", callback_data="back_main")]
        ])
    )

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
