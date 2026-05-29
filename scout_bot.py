import asyncio
import aiohttp
import urllib.parse
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage

TOKEN = "8678852008:AAGZeO7cKJWT1vNugKy8wkuII-wotKDZe70"
YANDEX_KEY = "42c18755-11ca-49ba-9326-0fd8e077f428"
NIKITA_ID = None  # заполнится при первом /start

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

NICHES = {
    "salon": "салон красоты Кисловодск",
    "cafe": "кафе ресторан Кисловодск",
    "hotel": "гостевой дом отель Кисловодск",
    "master": "частный мастер услуги Кисловодск",
    "med": "стоматология клиника Кисловодск",
    "fitness": "фитнес спортзал йога Кисловодск",
}

NICHE_NAMES = {
    "salon": "💅 Салоны красоты",
    "cafe": "☕ Кафе и рестораны",
    "hotel": "🏠 Гостевые дома",
    "master": "🔧 Частные мастера",
    "med": "🦷 Медицина",
    "fitness": "💪 Фитнес",
}

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти клиентов", callback_data="search_menu")],
        [InlineKeyboardButton(text="ℹ️ Как это работает", callback_data="howto")],
    ])

def niche_menu():
    buttons = []
    for key, name in NICHE_NAMES.items():
        buttons.append([InlineKeyboardButton(text=name, callback_data=f"niche_{key}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_btn():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Искать ещё", callback_data="search_menu")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main")],
    ])

async def search_organizations(query: str, results: int = 20):
    """Ищет организации через Яндекс API"""
    encoded = urllib.parse.quote(query)
    url = (
        f"https://search-maps.yandex.ru/v1/"
        f"?text={encoded}&type=biz&lang=ru_RU&results={results}&apikey={YANDEX_KEY}"
    )
    headers = {"User-Agent": "Mozilla/5.0"}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 403:
                return None, "limit"
            if r.status != 200:
                return None, f"error_{r.status}"
            data = await r.json()
            return data.get("features", []), "ok"

def parse_org(feature):
    """Разбирает одну организацию из ответа Яндекса"""
    props = feature.get("properties", {})
    meta = props.get("CompanyMetaData", {})
    
    name = props.get("name", "Без названия")
    address = props.get("description", "адрес не указан")
    
    phones = meta.get("Phones", [])
    phone = phones[0].get("formatted", "нет") if phones else "нет"
    
    site = meta.get("url", "")
    
    return {
        "name": name,
        "address": address,
        "phone": phone,
        "site": site,
        "has_site": bool(site),
    }

@dp.message(CommandStart())
async def start(msg: types.Message):
    global NIKITA_ID
    NIKITA_ID = msg.from_user.id
    await msg.answer(
        "👋 Привет! Это бот-разведчик WebForge.\n\n"
        "Я нахожу бизнесы в Кисловодске у которых **нет сайта** — "
        "это твои потенциальные клиенты.\n\n"
        "Выбери что делаем:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "back_main")
async def back_main(call: types.CallbackQuery):
    await call.message.edit_text(
        "👋 Главное меню — выбери действие:",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "howto")
async def howto(call: types.CallbackQuery):
    await call.message.edit_text(
        "ℹ️ *Как это работает:*\n\n"
        "1. Выбираешь нишу (салоны, кафе, гостиницы и т.д.)\n"
        "2. Бот ищет все такие бизнесы в Кисловодске через Яндекс\n"
        "3. Отфильтровывает тех у кого *нет сайта*\n"
        "4. Выдаёт список с телефонами — это твои клиенты\n\n"
        "Люда звонит или пишет — предлагает сайт за 5000 руб 🎯",
        reply_markup=back_btn(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "search_menu")
async def search_menu(call: types.CallbackQuery):
    await call.message.edit_text(
        "🔍 Выбери нишу для поиска:",
        reply_markup=niche_menu()
    )

@dp.callback_query(F.data.startswith("niche_"))
async def search_niche(call: types.CallbackQuery):
    niche_key = call.data.replace("niche_", "")
    query = NICHES.get(niche_key)
    niche_name = NICHE_NAMES.get(niche_key, "")
    
    if not query:
        await call.answer("Неизвестная ниша")
        return
    
    await call.message.edit_text(f"🔍 Ищу {niche_name} в Кисловодске...\nПодожди 10-15 секунд ⏳")
    
    features, status = await search_organizations(query, results=50)
    
    if status == "limit":
        await call.message.edit_text(
            "⚠️ Яндекс API исчерпал суточный лимит (500 запросов/день).\n\n"
            "Попробуй завтра — лимит сбрасывается в полночь по МСК.",
            reply_markup=back_btn()
        )
        return
    
    if status != "ok" or features is None:
        await call.message.edit_text(
            f"❌ Ошибка при запросе к Яндексу: {status}\n\nПопробуй позже.",
            reply_markup=back_btn()
        )
        return
    
    # Парсим и фильтруем
    all_orgs = [parse_org(f) for f in features]
    no_site = [o for o in all_orgs if not o["has_site"]]
    with_site = [o for o in all_orgs if o["has_site"]]
    
    # Формируем сообщение
    lines = [
        f"📊 *{niche_name} — результаты:*\n",
        f"Всего найдено: {len(all_orgs)}",
        f"✅ Без сайта (потенциальные клиенты): {len(no_site)}",
        f"❌ Уже есть сайт: {len(with_site)}\n",
        "─" * 25,
        "\n🎯 *БЕЗ САЙТА — твои клиенты:*\n",
    ]
    
    if no_site:
        for i, org in enumerate(no_site[:15], 1):
            lines.append(
                f"{i}. *{org['name']}*\n"
                f"   📍 {org['address']}\n"
                f"   📞 {org['phone']}\n"
            )
        if len(no_site) > 15:
            lines.append(f"... и ещё {len(no_site) - 15} организаций")
    else:
        lines.append("Не найдено организаций без сайта в этой нише.")
    
    result_text = "\n".join(lines)
    
    # Телеграм ограничивает 4096 символов
    if len(result_text) > 4000:
        result_text = result_text[:4000] + "\n\n... (список обрезан)"
    
    await call.message.edit_text(result_text, reply_markup=back_btn(), parse_mode="Markdown")

async def main():
    print("Бот-разведчик запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
