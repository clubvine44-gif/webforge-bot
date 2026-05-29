import asyncio
import aiohttp
import urllib.parse
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage

TOKEN = "8614199367:AAGVfOkdcceDaa58ufWPB1C1XD5v2OeAqmc"

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Кисловодск bbox: south,west,north,east
BBOX = "43.85,42.65,43.97,42.82"

NICHES = {
    "salon": {
        "name": "💅 Салоны красоты",
        "query": '["amenity"="hairdresser"]',
    },
    "beauty": {
        "name": "💄 Салоны красоты (beauty)",
        "query": '["shop"="beauty"]',
    },
    "cafe": {
        "name": "☕ Кафе и рестораны",
        "query": '["amenity"~"cafe|restaurant|bar|fast_food"]',
    },
    "hotel": {
        "name": "🏠 Гостиницы и гостевые дома",
        "query": '["tourism"~"hotel|guest_house|hostel"]',
    },
    "fitness": {
        "name": "💪 Фитнес и спорт",
        "query": '["leisure"~"fitness_centre|sports_centre"]',
    },
    "med": {
        "name": "🦷 Медицина",
        "query": '["amenity"~"dentist|clinic|doctors"]',
    },
    "shop": {
        "name": "🛍️ Магазины",
        "query": '["shop"]',
    },
}

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти клиентов", callback_data="search_menu")],
        [InlineKeyboardButton(text="ℹ️ Как это работает", callback_data="howto")],
    ])

def niche_menu():
    buttons = []
    for key, info in NICHES.items():
        buttons.append([InlineKeyboardButton(text=info["name"], callback_data=f"niche_{key}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_btn():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Искать ещё", callback_data="search_menu")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main")],
    ])

async def search_overpass(osm_filter: str):
    """Ищет организации через Overpass API (OpenStreetMap)"""
    query = f"""
[out:json][timeout:30];
(
  node{osm_filter}({BBOX});
  way{osm_filter}({BBOX});
);
out body;
"""
    url = "https://overpass-api.de/api/interpreter"
    headers = {"User-Agent": "WebForge Scout Bot 1.0 (webforge.ai)"}

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            data={"data": query},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=35)
        ) as r:
            if r.status != 200:
                return None, f"error_{r.status}"
            data = await r.json(content_type=None)
            return data.get("elements", []), "ok"

def parse_element(el):
    tags = el.get("tags", {})
    name = tags.get("name", "Без названия")
    phone = tags.get("phone", tags.get("contact:phone", "нет"))
    site = tags.get("website", tags.get("contact:website", ""))
    addr = tags.get("addr:street", "")
    if tags.get("addr:housenumber"):
        addr += f", {tags.get('addr:housenumber')}"
    return {
        "name": name,
        "phone": phone,
        "site": site,
        "addr": addr or "адрес не указан",
        "has_site": bool(site),
    }

@dp.message(CommandStart())
async def start(msg: types.Message):
    await msg.answer(
        "👋 Привет! Это *WebForge Scout* — бот-разведчик.\n\n"
        "Я нахожу бизнесы в Кисловодске у которых *нет сайта* — "
        "это твои потенциальные клиенты.\n\n"
        "Выбери что делаем:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "back_main")
async def back_main(call: types.CallbackQuery):
    await call.message.edit_text(
        "👋 Главное меню:",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "howto")
async def howto(call: types.CallbackQuery):
    await call.message.edit_text(
        "ℹ️ *Как это работает:*\n\n"
        "1. Выбираешь нишу\n"
        "2. Бот ищет все такие бизнесы в Кисловодске через OpenStreetMap\n"
        "3. Показывает у кого *нет сайта* — это твои клиенты\n"
        "4. Выдаёт список с телефонами для Люды\n\n"
        "Данные из OpenStreetMap — бесплатно и без ограничений 🎯",
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
    niche = NICHES.get(niche_key)

    if not niche:
        await call.answer("Неизвестная ниша")
        return

    await call.message.edit_text(
        f"🔍 Ищу {niche['name']} в Кисловодске...\n⏳ Подожди 15-20 секунд"
    )

    elements, status = await search_overpass(niche["query"])

    if status != "ok" or elements is None:
        await call.message.edit_text(
            f"❌ Ошибка запроса: {status}\nПопробуй ещё раз.",
            reply_markup=back_btn()
        )
        return

    all_orgs = [parse_element(el) for el in elements]
    # Убираем дубли по имени
    seen = set()
    unique = []
    for o in all_orgs:
        if o["name"] not in seen:
            seen.add(o["name"])
            unique.append(o)

    no_site = [o for o in unique if not o["has_site"]]
    with_site = [o for o in unique if o["has_site"]]

    lines = [
        f"📊 *{niche['name']} — результаты:*\n",
        f"Всего найдено: {len(unique)}",
        f"✅ Без сайта (твои клиенты): {len(no_site)}",
        f"❌ Уже есть сайт: {len(with_site)}\n",
    ]

    if no_site:
        lines.append("🎯 *БЕЗ САЙТА:*\n")
        for i, org in enumerate(no_site[:20], 1):
            phone_str = f"📞 {org['phone']}" if org['phone'] != 'нет' else "📞 нет телефона"
            lines.append(
                f"{i}. *{org['name']}*\n"
                f"   📍 {org['addr']}\n"
                f"   {phone_str}\n"
            )
        if len(no_site) > 20:
            lines.append(f"... и ещё {len(no_site) - 20}")
    else:
        lines.append("В этой нише все бизнесы уже имеют сайт, или данных нет в OpenStreetMap.")

    result = "\n".join(lines)
    if len(result) > 4000:
        result = result[:4000] + "\n\n...(обрезано)"

    await call.message.edit_text(result, reply_markup=back_btn(), parse_mode="Markdown")

async def main():
    print("WebForge Scout запущен (OpenStreetMap)")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
