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
    ContextTypes,
    MessageHandler,
    filters,
)

# ====== ENV ======
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
TZ = os.getenv("TZ", "Europe/Amsterdam")
MENU_FILE = os.getenv("MENU_FILE", "menu.json")

if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN env var")

# ====== LOGGING ======
logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("sushi-bot")

# ====== MENU / DATA ======
# Ожидается menu.json вида:
# {
#   "categories": [
#     {"id": "sets", "title_ru": "Сеты", "title_nl": "Sets"},
#     {"id": "rolls", "title_ru": "Роллы", "title_nl": "Rollen"}
#   ],
#   "items": [
#     {"id":"101","cat":"sets","title_ru":"Сет Самурай","title_nl":"Samurai Set","price":24.90},
#     {"id":"201","cat":"rolls","title_ru":"Филадельфия","title_nl":"Philadelphia","price":8.90}
#   ]
# }
with open(MENU_FILE, "r", encoding="utf-8") as f:
    MENU = json.load(f)

CATEGORIES = {c["id"]: c for c in MENU.get("categories", [])}
ITEMS: Dict[str, Dict[str, Any]] = {i["id"]: i for i in MENU.get("items", [])}

# ====== i18n ======
I18N = {
    "start": {
        "ru": "Привет! Это магазин *Sushi Aurum*. Выберите раздел:",
        "nl": "Hoi! Dit is *Sushi Aurum*. Kies een categorie:",
    },
    "browse": {"ru": "Меню", "nl": "Menu"},
    "cart": {"ru": "🛒 Корзина", "nl": "🛒 Winkelmand"},
    "back": {"ru": "⬅️ Назад", "nl": "⬅️ Terug"},
    "choose_cat": {
        "ru": "Выберите раздел:",
        "nl": "Kies een categorie:",
    },
    "choose_item": {
        "ru": "Выберите позицию:",
        "nl": "Kies een item:",
    },
    "added": {"ru": "Добавлено в корзину.", "nl": "Toegevoegd aan mandje."},
    "empty_cart": {"ru": "Корзина пуста.", "nl": "Je mandje is leeg."},
    "cart_title": {"ru": "В вашей корзине:", "nl": "In je mandje:"},
    "add": {"ru": "Добавить", "nl": "Toevoegen"},
    "price": {"ru": "Цена", "nl": "Prijs"},
}

DEFAULT_LANG = "ru"  # можно переключить на "nl" при желании

# ====== STATE (in-memory) ======
# carts: user_id -> {item_id: qty}
CARTS: Dict[int, Dict[str, int]] = {}


# ====== HELPERS ======
def lang_of_user(update: Update) -> str:
    # простая логика — всегда ru. При желании можно читать язык из профиля.
    return DEFAULT_LANG


def money(x: float) -> str:
    return f"{x:.2f}"


def main_kb(lang: str) -> InlineKeyboardMarkup:
    # Две категории из menu.json + кнопка корзины
    buttons = []
    # Если в меню много категорий — покажем первые 2 рядом
    row = []
    for cat in MENU.get("categories", []):
        row.append(InlineKeyboardButton(
            text=cat.get(f"title_{lang}", cat.get("title_ru", "Menu")),
            callback_data=f"browse:{cat['id']}",
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # Корзина отдельной строкой
    buttons.append([
        InlineKeyboardButton(I18N["cart"][lang], callback_data="cart")
    ])
    return InlineKeyboardMarkup(buttons)


def items_kb(cat_id: str, lang: str) -> InlineKeyboardMarkup:
    buttons = []
    for it in (x for x in ITEMS.values() if x.get("cat") == cat_id):
        title = it.get(f"title_{lang}", it.get("title_ru", "Item"))
        buttons.append([InlineKeyboardButton(title, callback_data=f"item:{it['id']}")])
    buttons.append([InlineKeyboardButton(I18N["back"][lang], callback_data="home")])
    return InlineKeyboardMarkup(buttons)


def item_kb(item_id: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(I18N["add"][lang], callback_data=f"add:{item_id}")],
        [InlineKeyboardButton(I18N["back"][lang], callback_data=f"browse:{ITEMS[item_id]['cat']}")],
    ])


# ====== HANDLERS ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = lang_of_user(update)
    await update.message.reply_text(
        I18N["start"][lang],
        reply_markup=main_kb(lang),
        parse_mode="Markdown",
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = lang_of_user(update)
    query = update.callback_query
    await query.answer()

    data = query.data or ""

    # Домой (главное меню)
    if data == "home":
        await query.edit_message_text(
            I18N["choose_cat"][lang],
            reply_markup=main_kb(lang),
        )
        return

    # Открыть корзину
    if data == "cart":
        uid = update.effective_user.id
        cart = CARTS.get(uid, {})
        if not cart:
            await query.edit_message_text(I18N["empty_cart"][lang], reply_markup=main_kb(lang))
            return
        lines = [I18N["cart_title"][lang], ""]
        total = 0.0
        for item_id, qty in cart.items():
            it = ITEMS.get(item_id)
            if not it:
                continue
            price = float(it.get("price", 0))
            subtotal = price * qty
            total += subtotal
            title = it.get(f"title_{lang}", it.get("title_ru", "Item"))
            lines.append(f"• {title} × {qty} — € {money(subtotal)}")
        lines.append("")
        lines.append(f"Итого: € {money(total)}")
        await query.edit_message_text("\n".join(lines), reply_markup=main_kb(lang))
        return

    # Просмотр категории
    if data.startswith("browse:"):
        cat_id = data.split(":", 1)[1]
        cat = CATEGORIES.get(cat_id)
        if not cat:
            await query.edit_message_text("Категория не найдена.", reply_markup=main_kb(lang))
            return
        await query.edit_message_text(
            I18N["choose_item"][lang],
            reply_markup=items_kb(cat_id, lang),
        )
        return

    # Просмотр конкретного товара
    if data.startswith("item:"):
        item_id = data.split(":", 1)[1]
        it = ITEMS.get(item_id)
        if not it:
            await query.edit_message_text("Позиция не найдена.", reply_markup=main_kb(lang))
            return
        title = it.get(f"title_{lang}", it.get("title_ru", "Item"))
        price = it.get("price", 0)
        text = f"*{title}*\n{I18N['price'][lang]}: € {money(float(price))}"
        await query.edit_message_text(
            text,
            reply_markup=item_kb(item_id, lang),
            parse_mode="Markdown",
        )
        return

    # Добавление в корзину
    if data.startswith("add:"):
        item_id = data.split(":", 1)[1]
        uid = update.effective_user.id
        CARTS.setdefault(uid, {})
        CARTS[uid][item_id] = CARTS[uid].get(item_id, 0) + 1
        await query.answer(I18N["added"][lang], show_alert=False)

        # После добавления покажем карточку товара снова
        it = ITEMS.get(item_id)
        if it:
            title = it.get(f"title_{lang}", it.get("title_ru", "Item"))
            price = it.get("price", 0)
            text = f"*{title}*\n{I18N['price'][lang]}: € {money(float(price))}"
            await query.edit_message_text(
                text,
                reply_markup=item_kb(item_id, lang),
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text(I18N["choose_cat"][lang], reply_markup=main_kb(lang))


# На всякий случай — ответ «/menu» тем же, что и /start
async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # тихо игнорим любые тексты: показываем меню
    lang = lang_of_user(update)
    await update.message.reply_text(I18N["start"][lang], reply_markup=main_kb(lang), parse_mode="Markdown")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))
    # любое сообщение — показать меню
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))

    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
