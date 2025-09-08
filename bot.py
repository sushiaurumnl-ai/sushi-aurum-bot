import os
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Tuple

from sqlalchemy import create_engine, Integer, String, Float, DateTime, Text, Enum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

import pytz

# ---------- Config ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # string ok
TIMEZONE = os.getenv("TZ", "Europe/Amsterdam")

if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN env var")

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger("sushi-bot")

# ---------- DB ----------
class Base(DeclarativeBase):
    pass

from enum import Enum as PyEnum
class OrderStatus(PyEnum):
    NEW = "NEW"
    COOKING = "COOKING"
    ON_THE_WAY = "ON_THE_WAY"
    DONE = "DONE"
    CANCELLED = "CANCELLED"

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    username: Mapped[str] = mapped_column(String(255), default="")
    lang: Mapped[str] = mapped_column(String(2), default="ru")
    items_json: Mapped[str] = mapped_column(Text)
    total: Mapped[float] = mapped_column(Float)
    delivery_type: Mapped[str] = mapped_column(String(16))  # delivery/pickup
    address: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    comment: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default=OrderStatus.NEW.value)
    created_at: Mapped[datetime] = mapped_column(DateTime)

DB_URL = os.getenv("DB_URL", "sqlite:///db.sqlite3")
engine = create_engine(DB_URL, echo=False)
Base.metadata.create_all(engine)

# ---------- Menu ----------
with open(os.getenv("MENU_FILE", "menu.json"), "r", encoding="utf-8") as f:
    MENU = json.load(f)

# ---------- Simple i18n ----------
I18N = {
    "start": {
        "ru": "Привет! Это магазин *Sushi Aurum*. Выберите язык / Kies taal:",
        "nl": "Hoi! Dit is *Sushi Aurum*. Kies taal / Choose language:"
    },
    "choose_lang": {"ru":"🇷🇺 Русский", "nl":"🇳🇱 Nederlands"},
    "browse": {"ru":"🛍 Меню", "nl":"🛍 Menu"},
    "cart": {"ru":"🧺 Корзина", "nl":"🧺 Winkelmand"},
    "checkout": {"ru":"✅ Оформить", "nl":"✅ Afrekenen"},
    "back": {"ru":"⬅️ Назад", "nl":"⬅️ Terug"},
    "add_to_cart": {"ru":"Добавить", "nl":"Toevoegen"},
    "empty_cart": {"ru":"Корзина пуста.", "nl":"Je mandje is leeg."},
    "ask_delivery_type":{"ru":"Доставка или самовывоз?","nl":"Bezorgen of afhalen?"},
    "delivery":{"ru":"🚚 Доставка","nl":"🚚 Bezorgen"},
    "pickup":{"ru":"🏪 Самовывоз","nl":"🏪 Afhalen"},
    "ask_address":{"ru":"Введите адрес доставки:","nl":"Voer het bezorgadres in:"},
    "ask_phone":{"ru":"Оставьте номер телефона:","nl":"Laat uw telefoonnummer achter:"},
    "ask_comment":{"ru":"Комментарий к заказу (или - пропустить):","nl":"Opmerking bij bestelling (of - overslaan):"},
    "order_ok":{"ru":"Спасибо! Заказ принят. Номер #{id}.",
                "nl":"Bedankt! Bestelling geplaatst. Nummer #{id}."},
}

# ---------- State ----------
# carts: user_id -> {item_id: qty}
CARTS: Dict[int, Dict[str, int]] = {}
# pending user flow
PENDING: Dict[int, Dict[str, Any]] = {}

def lang_of_user(update: Update) -> str:
    # read from PENDING or default ru
    uid = update.effective_user.id
    if uid in PENDING and "lang" in PENDING[uid]:
        return PENDING[uid]["lang"]
    return "ru"

def money(x: float) -> str:
    return f"€{x:.2f}"

def build_main_kb(lang: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(I18N["browse"][lang], callback_data=f"browse")],
        [InlineKeyboardButton(I18N["cart"][lang], callback_data=f"cart")]
    ])

def build_lang_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru"),
         InlineKeyboardButton("🇳🇱 Nederlands", callback_data="lang:nl")]
    ])

def build_categories_kb(lang: str):
    rows = []
    for cat in MENU["categories"]:
        label = cat["name_ru"] if lang=="ru" else cat["name_nl"]
        rows.append([InlineKeyboardButton(label, callback_data=f"cat:{cat['id']}")])
    rows.append([InlineKeyboardButton(I18N["cart"][lang], callback_data="cart")])
    rows.append([InlineKeyboardButton(I18N["back"][lang], callback_data="home")])
    return InlineKeyboardMarkup(rows)

def build_items_kb(cat: Dict[str, Any], lang: str):
    rows = []
    for it in cat["items"]:
        label = (it["name_ru"] if lang=="ru" else it["name_nl"]) + f" • {money(it['price'])}"
        rows.append([InlineKeyboardButton(label, callback_data=f"item:{it['id']}")])
    rows.append([InlineKeyboardButton(I18N["back"][lang], callback_data="browse")])
    return InlineKeyboardMarkup(rows)

def build_item_kb(item: Dict[str, Any], lang: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"+ {I18N['add_to_cart'][lang]}", callback_data=f"add:{item['id']}")],
        [InlineKeyboardButton(I18N["back"][lang], callback_data=f"catback")]
    ])

def build_cart_kb(lang: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(I18N["checkout"][lang], callback_data="checkout")],
        [InlineKeyboardButton(I18N["back"][lang], callback_data="browse")]
    ])

def find_item(item_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    for cat in MENU["categories"]:
        for it in cat["items"]:
            if it["id"] == item_id:
                return it, cat
    return None, None

def cart_text(uid: int, lang: str) -> Tuple[str, float]:
    cart = CARTS.get(uid, {})
    if not cart:
        return I18N["empty_cart"][lang], 0.0
    lines = []
    total = 0.0
    for iid, qty in cart.items():
        it, _ = find_item(iid)
        if not it: 
            continue
        name = it["name_ru"] if lang=="ru" else it["name_nl"]
        price = it["price"] * qty
        total += price
        lines.append(f"{name} × {qty} — {money(price)}")
    # delivery fee logic
    fee = MENU["delivery"]["delivery_fee"]
    free_from = MENU["delivery"]["free_from"]
    if total < free_from:
        total_with = total + fee
        lines.append(f"Доставка: {money(fee)}" if lang=="ru" else f"Bezorging: {money(fee)}")
    else:
        total_with = total
        lines.append("Доставка: бесплатно" if lang=="ru" else "Bezorging: gratis")
    lines.append(f"Итого: {money(total_with)}" if lang=="ru" else f"Totaal: {money(total_with)}")
    return "\n".join(lines), total_with

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    PENDING.setdefault(uid, {})
    await update.message.reply_text(
        I18N["start"]["ru"],
        reply_markup=build_lang_kb(),
        parse_mode="Markdown"
    )

async def home(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str, message_obj):
    await message_obj.edit_text(
        I18N["start"][lang],
        reply_markup=build_main_kb(lang),
        parse_mode="Markdown"
    )

async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    PENDING.setdefault(uid, {})
    data = query.data

    # language
    if data.startswith("lang:"):
        lang = data.split(":")[1]
        PENDING[uid]["lang"] = lang
        await home(update, context, lang, query.message)
        return

    lang = lang_of_user(update)

    if data == "home":
        await home(update, context, lang, query.message)
        return

    if data == "browse":
        kb = build_categories_kb(lang)
        title = "Выберите категорию:" if lang=="ru" else "Kies een categorie:"
        await query.message.edit_text(title, reply_markup=kb)
        return

    if data.startswith("cat:"):
        cat_id = data.split(":")[1]
        cat = next(c for c in MENU["categories"] if c["id"] == cat_id)
        kb = build_items_kb(cat, lang)
        title = cat["name_ru"] if lang=="ru" else cat["name_nl"]
        await query.message.edit_text(title, reply_markup=kb)
        PENDING[uid]["last_cat"] = cat_id
        return

    if data == "catback":
        cat_id = PENDING[uid].get("last_cat")
        if not cat_id:
            await cb_to_browse(query, lang)
            return
        cat = next(c for c in MENU["categories"] if c["id"] == cat_id)
        kb = build_items_kb(cat, lang)
        title = cat["name_ru"] if lang=="ru" else cat["name_nl"]
        await query.message.edit_text(title, reply_markup=kb)
        return

    if data.startswith("item:"):
        item_id = data.split(":")[1]
        item, cat = find_item(item_id)
        if not item:
            await query.message.edit_text("Item not found")
            return
        name = item["name_ru"] if lang=="ru" else item["name_nl"]
        desc = item["desc_ru"] if lang=="ru" else item["desc_nl"]
        text = f"*{name}* — {money(item['price'])}\n{desc}"
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=build_item_kb(item, lang))
        PENDING[uid]["last_cat"] = cat["id"]
        return

    if data.startswith("add:"):
        item_id = data.split(":")[1]
        cart = CARTS.setdefault(uid, {})
        cart[item_id] = cart.get(item_id, 0) + 1
        await query.answer("Добавлено" if lang=="ru" else "Toegevoegd", show_alert=False)
        return

    if data == "cart":
        text, _ = cart_text(uid, lang)
        await query.message.edit_text(text, reply_markup=build_cart_kb(lang))
        return

    if data == "checkout":
        cart = CARTS.get(uid, {})
        if not cart:
            await query.message.edit_text(I18N["empty_cart"][lang], reply_markup=build_main_kb(lang))
            return
        # ask delivery or pickup
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(I18N["delivery"][lang], callback_data="deliver:delivery"),
            InlineKeyboardButton(I18N["pickup"][lang], callback_data="deliver:pickup")
        ]])
        await query.message.edit_text(I18N["ask_delivery_type"][lang], reply_markup=kb)
        return

    if data.startswith("deliver:"):
        choice = data.split(":")[1]
        PENDING[uid]["delivery_type"] = choice
        if choice == "delivery":
            await query.message.edit_text(I18N["ask_address"][lang])
            PENDING[uid]["stage"] = "address"
        else:
            await query.message.edit_text(I18N["ask_phone"][lang])
            PENDING[uid]["stage"] = "phone"
        return


async def cb_to_browse(message, lang):
    kb = build_categories_kb(lang)
    title = "Выберите категорию:" if lang=="ru" else "Kies een categorie:"
    await message.edit_text(title, reply_markup=kb)

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    lang = lang_of_user(update)
    st = PENDING.get(uid, {}).get("stage")

    if st == "address":
        PENDING[uid]["address"] = text
        PENDING[uid]["stage"] = "phone"
        await update.message.reply_text(I18N["ask_phone"][lang])
        return
    if st == "phone":
        PENDING[uid]["phone"] = text
        PENDING[uid]["stage"] = "comment"
        await update.message.reply_text(I18N["ask_comment"][lang])
        return
    if st == "comment":
        PENDING[uid]["comment"] = ("" if text == "-" else text)
        # create order
        await create_order_and_confirm(update, context, lang)
        # reset stage
        PENDING[uid]["stage"] = None
        return

    # default: show main
    await update.message.reply_text(I18N["start"][lang], parse_mode="Markdown", reply_markup=build_main_kb(lang))

async def create_order_and_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    uid = update.effective_user.id
    user = update.effective_user
    cart = CARTS.get(uid, {})
    if not cart:
        await update.message.reply_text(I18N["empty_cart"][lang])
        return

    items_repr = []
    total = 0.0
    for iid, qty in cart.items():
        it, _ = find_item(iid)
        if not it: 
            continue
        items_repr.append({"id": iid, "qty": qty, "price": it["price"]})
        total += it["price"] * qty

    fee = MENU["delivery"]["delivery_fee"]
    free_from = MENU["delivery"]["free_from"]
    if total < free_from:
        total += fee

    delivery_type = PENDING[uid].get("delivery_type", "delivery")
    address = PENDING[uid].get("address", "") if delivery_type == "delivery" else "Pickup"
    phone = PENDING[uid].get("phone", "")
    comment = PENDING[uid].get("comment", "")
    tz = pytz.timezone(TIMEZONE)

    with Session(engine) as s:
        order = Order(
            user_id=uid,
            username=user.username or "",
            lang=lang,
            items_json=json.dumps(items_repr, ensure_ascii=False),
            total=round(total,2),
            delivery_type=delivery_type,
            address=address,
            phone=phone,
            comment=comment,
            status="NEW",
            created_at=datetime.now(tz)
        )
        s.add(order)
        s.commit()
        order_id = order.id

    # notify admin
    summary_lines = [f"🆕 Новый заказ #{order_id}",
                     f"Пользователь: @{user.username} ({uid})",
                     f"Тип: {'Доставка' if delivery_type=='delivery' else 'Самовывоз'}",
                     f"Адрес: {address}",
                     f"Телефон: {phone}",
                     f"Комментарий: {comment}",
                     "Состав:"]
    for x in items_repr:
        it, _ = find_item(x["id"])
        name = it["name_ru"] if lang=="ru" else it["name_nl"]
        summary_lines.append(f" - {name} × {x['qty']}")
    summary_lines.append(f"Итого к оплате: €{total:.2f}")
    admin_text = "\n".join(summary_lines)

    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=admin_text)
        except Exception as e:
            log.warning("Failed to notify admin: %s", e)

    # clear cart
    CARTS[uid] = {}

    ok_text = I18N["order_ok"][lang].format(id=order_id)
    await update.message.reply_text(ok_text)

# ---------- Admin ----------
async def orders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != (ADMIN_CHAT_ID or ""):
        return
    # last 20
    with Session(engine) as s:
        rows = s.query(Order).order_by(Order.id.desc()).limit(20).all()
    if not rows:
        await update.message.reply_text("Нет заказов.")
        return
    lines = []
    for o in rows:
        lines.append(f"#{o.id} | {o.status} | €{o.total:.2f} | {o.delivery_type} | {o.address} | {o.phone} | @{o.username}")
    await update.message.reply_text("\n".join(lines))

async def setstatus_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != (ADMIN_CHAT_ID or ""):
        return
    try:
        oid = int(context.args[0])
        status = context.args[1].upper()
        if status not in {"NEW","COOKING","ON_THE_WAY","DONE","CANCELLED"}:
            await update.message.reply_text("Статусы: NEW | COOKING | ON_THE_WAY | DONE | CANCELLED")
            return
    except Exception:
        await update.message.reply_text("Использование: /setstatus <id> <STATUS>")
        return

    with Session(engine) as s:
        o = s.get(Order, oid)
        if not o:
            await update.message.reply_text("Заказ не найден")
            return
        o.status = status
        s.commit()
    await update.message.reply_text(f"OK: #{oid} → {status}")

# ---------- Main ----------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("orders", orders_cmd))
    app.add_handler(CommandHandler("setstatus", setstatus_cmd))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    # choose between polling and webhook by presence of WEBHOOK_URL
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        port = int(os.getenv("PORT", "8080"))
        log.info("Starting webhook on port %s", port)
        app.run_webhook(listen="0.0.0.0", port=port, url_path=BOT_TOKEN, webhook_url=f"{webhook_url}/{BOT_TOKEN}")
    else:
        log.info("Starting polling")
        app.run_polling()

if __name__ == "__main__":
    main()