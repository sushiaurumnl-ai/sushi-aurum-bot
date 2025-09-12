# bot.py — PTB v20+

import os
import json
import logging
from typing import Dict, Any

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------- Config ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # строка или пусто
TZ = os.getenv("TZ", "Europe/Amsterdam")
MENU_FILE = os.getenv("MENU_FILE", "menu.json")

if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN env var")

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("sushi-bot")

# ---------- Load Menu ----------
with open(MENU_FILE, "r", encoding="utf-8") as f:
    MENU = json.load(f)

# Быстрые индексы
CATS: Dict[str, Dict[str, Any]] = {}
ITEMS: Dict[str, Dict[str, Any]] = {}
for cat in MENU.get("categories", []):
    CATS[cat["id"]] = cat
    for it in cat.get("items", []):
        ITEMS[it["id"]] = it

# ---------- i18n ----------
I18N = {
    "start": {
        "ru": "Привет! Это магазин *Sushi Aurum*. Выберите раздел:",
        "nl": "Hoi! Dit is *Sushi Aurum*. Kies een categorie:",
    },
    "browse": {"ru": "🍱 Меню", "nl": "🍱 Menu"},
    "sets": {"ru": "Сеты", "nl": "Sets"},
    "rolls": {"ru": "Роллы", "nl": "Rollen"},
    "cart": {"ru": "🛒 Корзина", "nl": "🛒 Winkelmand"},
    "back": {"ru": "🔙 Назад", "nl": "🔙 Terug"},
    "choose_cat": {"ru": "Выберите раздел:", "nl": "Kies sectie:"},
    "choose_item": {"ru": "Выберите позицию:", "nl": "Kies item:"},
    "added": {"ru": "✅ Добавлено", "nl": "✅ Toegevoegd"},
    "empty_cart": {"ru": "Корзина пуста.", "nl": "De mandje is leeg."},
    "your_cart": {"ru": "Ваша корзина:", "nl": "Uw mand:"},
}

# ---------- State ----------
# carts: user_id -> {item_id: qty}
CARTS: Dict[int, Dict[str, int]] = {}

# pending flow (язык и пр.), сейчас только язык
PENDING: Dict[int, Dict[str, Any]] = {}


# ---------- Helpers ----------
def lang_of_user(update: Update) -> str:
    uid = update.effective_user.id
    if uid in PENDING and "lang" in PENDING[uid]:
        return PENDING[uid]["lang"]
    return "ru"

def money(x: float) -> str:
    return f"{x:.2f}"

def build_main_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(I18N["sets"][lang], callback_data="cat:sets"),
         InlineKeyboardButton(I18N["rolls"][lang], callback_data="cat:rolls")],
        [InlineKeyboardButton(I18N["cart"][lang], callback_data="cart")],
    ])

def categories_kb(lang: str) -> InlineKeyboardMarkup:
    btns = []
    for c in MENU.get("categories", []):
        title = c.get("title_ru") if lang == "ru" else c.get("title_nl", c.get("title_ru"))
        btns.append([InlineKeyboardButton(title, callback_data=f"cat:{c['id']}")])
    btns.append([InlineKeyboardButton(I18N["back"][lang], callback_data="back:main")])
    return InlineKeyboardMarkup(btns)

def items_kb(cat_id: str, lang: str) -> InlineKeyboardMarkup:
    cat = CATS.get(cat_id)
    btns = []
    if not cat:
        return InlineKeyboardMarkup([[InlineKeyboardButton(I18N["back"][lang], callback_data="back:main")]])
    for it in cat.get("items", []):
        title = it.get("title_ru") if lang == "ru" else it.get("title_nl", it.get("title_ru"))
        btns.append([InlineKeyboardButton(title, callback_data=f"item:{it['id']}")])
    btns.append([InlineKeyboardButton(I18N["back"][lang], callback_data="back:cats")])
    return InlineKeyboardMarkup(btns)

def item_kb(item_id: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить" if lang == "ru" else "➕ Toevoegen", callback_data=f"add:{item_id}")],
        [InlineKeyboardButton(I18N["back"][lang], callback_data="back:items")],
    ])

def cart_text(uid: int, lang: str) -> str:
    cart = CARTS.get(uid, {})
    if not cart:
        return I18N["empty_cart"][lang]
    lines = [I18N["your_cart"][lang], ""]
    total = 0.0
    for item_id, qty in cart.items():
        it = ITEMS.get(item_id)
        if not it:
            continue
        title = it.get("title_ru") if lang == "ru" else it.get("title_nl", it.get("title_ru"))
        price = float(it.get("price", 0))
        sum_ = price * qty
        total += sum_
        lines.append(f"{title} × {qty} = €{money(sum_)}")
    lines.append("")
    lines.append(f"Итого: €{money(total)}" if lang == "ru" else f"Totaal: €{money(total)}")
    return "\n".join(lines)


# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = lang_of_user(update)
    await update.message.reply_text(
        I18N["start"][lang],
        reply_markup=build_main_kb(lang),
        parse_mode="Markdown",
    )

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = lang_of_user(update)
    data = query.data or ""
    chat_id = update.effective_chat.id
    uid = update.effective_user.id

    # показать корзину
    if data == "cart":
        await query.edit_message_text(
            cart_text(uid, lang),
            reply_markup=build_main_kb(lang),
        )
        return

    # список категорий (если захочешь отдельной кнопкой)
    if data == "browse":
        await query.edit_message_text(
            I18N["choose_cat"][lang],
            reply_markup=categories_kb(lang),
        )
        return

    # показать товары категории
    if data.startswith("cat:"):
        cat_id = data.split(":", 1)[1]
        cat = CATS.get(cat_id)
        if not cat:
            return
        title = cat.get("title_ru") if lang == "ru" else cat.get("title_nl", cat.get("title_ru"))
        await query.edit_message_text(
            f"{I18N['choose_item'][lang]}",
            reply_markup=items_kb(cat_id, lang),
        )
        return

    # карточка товара
    if data.startswith("item:"):
        item_id = data.split(":", 1)[1]
        it = ITEMS.get(item_id)
        if not it:
            return
        title = it.get("title_ru") if lang == "ru" else it.get("title_nl", it.get("title_ru"))
        price = float(it.get("price", 0))
        text = f"*{title}*\n€{money(price)}"
        await query.edit_message_text(
            text,
            reply_markup=item_kb(item_id, lang),
            parse_mode="Markdown",
        )
        return

    # добавить в корзину
    if data.startswith("add:"):
        item_id = data.split(":", 1)[1]
        CARTS.setdefault(uid, {})
        CARTS[uid][item_id] = CARTS[uid].get(item_id, 0) + 1
        await context.bot.send_message(chat_id=chat_id, text=I18N["added"][lang])
        return

    # навигация назад
    if data.startswith("back:"):
        where = data.split(":", 1)[1]
        if where == "main":
            await query.edit_message_text(
                I18N["start"][lang],
                reply_markup=build_main_kb(lang),
                parse_mode="Markdown",
            )
        elif where == "cats":
            await query.edit_message_text(
                I18N["choose_cat"][lang],
                reply_markup=categories_kb(lang),
            )
        elif where == "items":
            # вернуться к списку категорий
            await query.edit_message_text(
                I18N["choose_cat"][lang],
                reply_markup=categories_kb(lang),
            )
        return

async def echo_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # На любой текст без команды просто покажем главное меню
    lang = lang_of_user(update)
    await update.message.reply_text(
        I18N["start"][lang],
        reply_markup=build_main_kb(lang),
        parse_mode="Markdown",
    )


# ---------- Main ----------
def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_unknown))

    return app

def main():
    app = build_app()
    log.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
