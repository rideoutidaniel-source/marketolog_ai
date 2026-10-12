import asyncio
import json
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

import ai  # после load_dotenv, чтобы подхватить ключ

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # куда приходят заявки

DATA = json.loads((Path(__file__).parent / "catalog.json").read_text(encoding="utf-8"))
SHOP = DATA["shop"]
CATEGORIES = DATA["categories"]

router = Router()

# ---------- Клавиатуры ----------
def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🛋 Каталог", callback_data="catalog")
    kb.button(text="📝 Оставить заявку", callback_data="order")
    kb.button(text="🚚 Доставка и оплата", callback_data="faq")
    kb.button(text="📞 Контакты", callback_data="contacts")
    kb.adjust(1, 1, 2)
    return kb.as_markup()


def back_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В меню", callback_data="menu")
    return kb.as_markup()


WELCOME = (
    f"Здравствуйте! 👋 Я помощник магазина «{SHOP['name']}».\n\n"
    "Покажу каталог, помогу подобрать мебель под вашу комнату и бюджет "
    "или передам заявку менеджеру. Просто напишите, что ищете, "
    "например: «диван в небольшую гостиную до 8 млн»."
)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(WELCOME, reply_markup=main_menu())


@router.message(Command("menu"))
async def menu_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню:", reply_markup=main_menu())


@router.callback_query(F.data == "menu")
async def menu_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Главное меню:", reply_markup=main_menu())
    await cb.answer()


# ---------- Каталог ----------
@router.callback_query(F.data == "catalog")
async def catalog(cb: CallbackQuery):
    kb = InlineKeyboardBuilder()
    for i, c in enumerate(CATEGORIES):
        kb.button(text=c["title"], callback_data=f"cat:{i}")
    kb.button(text="⬅️ В меню", callback_data="menu")
    kb.adjust(2)
    await cb.message.answer("Выберите категорию:", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("cat:"))
async def category(cb: CallbackQuery):
    ci = int(cb.data.split(":")[1])
    cat = CATEGORIES[ci]
    kb = InlineKeyboardBuilder()
    for ii, it in enumerate(cat["items"]):
        kb.button(text=f"{it['name']} — {it['price']:,} {SHOP['currency']}".replace(",", " "),
                  callback_data=f"item:{ci}:{ii}")
    kb.button(text="⬅️ Категории", callback_data="catalog")
    kb.adjust(1)
    await cb.message.answer(f"{cat['title']}:", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("item:"))
async def item(cb: CallbackQuery):
    _, ci, ii = cb.data.split(":")
    cat = CATEGORIES[int(ci)]
    it = cat["items"][int(ii)]
    text = (
        f"<b>{it['name']}</b>\n"
        f"💰 {it['price']:,} {SHOP['currency']}\n\n{it['desc']}".replace(",", " ")
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Заказать", callback_data=f"order:{ci}:{ii}")
    kb.button(text="⬅️ Назад", callback_data=f"cat:{ci}")
    kb.adjust(1)
    if it.get("photo"):
        await cb.message.answer_photo(it["photo"], caption=text, parse_mode="HTML",
                                      reply_markup=kb.as_markup())
    else:
        await cb.message.answer(text, parse_mode="HTML", reply_markup=kb.as_markup())
    await cb.answer()


# ---------- FAQ / Контакты ----------
@router.callback_query(F.data == "faq")
async def faq(cb: CallbackQuery):
    text = (
        f"🚚 <b>Доставка:</b> {SHOP['delivery']}\n\n"
        f"💳 <b>Оплата:</b> {SHOP['payment']}\n\n"
        f"🛡 <b>Гарантия:</b> {SHOP['warranty']}"
    )
    await cb.message.answer(text, parse_mode="HTML", reply_markup=back_menu())
    await cb.answer()


@router.callback_query(F.data == "contacts")
async def contacts(cb: CallbackQuery):
    text = (
        f"📍 {SHOP['address']}\n"
        f"📞 {SHOP['phone']}\n"
        f"🕘 {SHOP['hours']}"
    )
    await cb.message.answer(text, reply_markup=back_menu())
    await cb.answer()


# ---------- Заявка ----------
class Order(StatesGroup):
    name = State()
    phone = State()
    comment = State()


@router.callback_query(F.data.startswith("order"))
async def order_start(cb: CallbackQuery, state: FSMContext):
    product = ""
    parts = cb.data.split(":")
    if len(parts) == 3:
        it = CATEGORIES[int(parts[1])]["items"][int(parts[2])]
        product = it["name"]
    await state.update_data(product=product)
    await state.set_state(Order.name)
    await cb.message.answer("Как к вам обращаться?")
    await cb.answer()


@router.message(Order.name, F.text)
async def order_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(Order.phone)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )
    await message.answer("Оставьте номер телефона (кнопкой или текстом):", reply_markup=kb)


@router.message(Order.phone)
async def order_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else (message.text or "").strip()
    if len(phone) < 7:
        await message.answer("Не похоже на номер телефона, попробуйте ещё раз.")
        return
    await state.update_data(phone=phone)
    await state.set_state(Order.comment)
    await message.answer("Добавьте комментарий (размеры, цвет, адрес) или напишите «-».",
                         reply_markup=ReplyKeyboardRemove())


@router.message(Order.comment, F.text)
async def order_done(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    user = message.from_user
    uname = f"@{user.username}" if user.username else f"id {user.id}"
    text = (
        "🆕 <b>Новая заявка</b>\n"
        f"Товар: {data.get('product') or 'не указан'}\n"
        f"Имя: {data['name']}\n"
        f"Телефон: {data['phone']}\n"
        f"Комментарий: {message.text}\n"
        f"Telegram: {uname}"
    )
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, text, parse_mode="HTML")
    await message.answer("Спасибо! Заявка принята, менеджер свяжется с вами в ближайшее время. 🙌",
                         reply_markup=main_menu())


# ---------- Свободный текст и фото -> AI ----------
AI_FAIL = "Сейчас не получается ответить. Попробуйте меню или оставьте заявку."


async def _answer_ai(message: Message, text: str, image_b64: str | None = None):
    if not ai.enabled:
        await message.answer("Выберите действие в меню:", reply_markup=main_menu())
        return
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        answer = await ai.ask(message, SHOP, text, image_b64)
    except Exception:
        logging.exception("AI error")
        await message.answer(AI_FAIL, reply_markup=main_menu())
        return
    await message.answer(answer, reply_markup=main_menu())


@router.message(F.photo)
async def photo_msg(message: Message):
    if not ai.enabled:
        await message.answer("Фото получено. Менеджер свяжется с вами, оставьте заявку:", reply_markup=main_menu())
        return
    try:
        file = await message.bot.get_file(message.photo[-1].file_id)
        data = (await message.bot.download_file(file.file_path)).read()
        b64 = ai.prepare_image(data)
    except Exception:
        logging.exception("photo error")
        await message.answer("Не удалось открыть фото, пришлите ещё раз.")
        return
    await _answer_ai(message, message.caption or "", b64)


@router.message(F.text)
async def free_text(message: Message):
    await _answer_ai(message, message.text)


async def main():
    if not BOT_TOKEN:
        raise SystemExit("Задайте BOT_TOKEN в файле .env")
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
