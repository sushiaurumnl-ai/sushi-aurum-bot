# bot.py — PTB v20+
import os
import json
import logging
from typing import Dict, Any

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --------- ENV ---------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # можно не использовать сейчас
TZ = os.getenv("TZ", "Europe/Amsterdam")
MENU_FILE = os.getenv("MENU_FILE", "menu.json")

if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN env var")

# --------- LOGGING ---------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
log = logging.getLogger("sushi-bot")

# --------- DATA ---------
# menu.json формат:
# {
#   "categories":[
#     {"id":"sets","title_ru":"Сеты","title_nl":"Sets"},
#     {"id":"rolls","title_ru":"Роллы","title_nl":"Rollen"}
#   ],
#   "items":[
#     {"id":"s1","cat":"sets","title_ru":"Сет #1","title_nl":"Set #1","price":12.5},
#     {"id":"r1","cat":"rolls","title_ru":"Филадельфия","title_nl":"Philadelphia","price":8.0}
#   ]
# }
with open(MENU_FILE, "r", encoding="utf-8") as f:
    MENU: Dict[str, Any] = json.load(f)

CATS = {c["id"]: c for c in MENU.get("categories", [])}
ITEMS = {i["id"]: i for i in MENU.get("items", [])}

# user_id -> { item_id -> qty }
CARTS: Dict[int, Dict[str, int]] = {}

# simple i18n
I18N = {
    "start": {
        "ru": "Привет! Это магазин *Sushi Aurum*. Выберите раздел:",
        "nl": "Hoi! Dit is *Sushi Aurum*. Kies een sectie:",
    },
    "browse": {"ru": "Меню", "nl": "Menu"},
    "cart": {"ru": "Корзина", "nl": "Winkelmand"},
    "back": {"ru": "⬅️ Назад", "nl": "⬅️ Terug"},
    "checkout": {"ru": "✅ Оформить", "nl": "✅ Afrekenen"},
    "empty_cart": {"ru": "🧺 Корзина пуста.", "nl": "🧺 Je mandje is leeg."},
    "choose_item": {"ru": "Выберите позицию:", "nl": "Kies item:"},
    "added": {"ru": "✅ Добавлено", "nl": "✅ Toegevoegd"},
}


def user_lang(update: Update) -> str:
    # по умолчанию RU, если хочешь — расширим позже
    return "ru"


def t(key: str, lang: str) -> str:
    return I18N.get(key, {}).get(lang, I18N.get(key, {}).get("ru", key))


def main_kb(lang: str) -> InlineKeyboardMarkup:
    # две кнопки категорий + корзина
    btns = []
    for cat_id, cat in CATS.items():
        title = cat.get("title_ru") if lang == "ru" else cat.get("title_nl", cat.get("title_ru"))
        btns.append([InlineKeyboardButton(title, callback_data=f"cat:{cat_id}")])
    btns.append([InlineKeyboardButton(f"🛒 {t('cart', lang)}", callback_data="cart")])
    return InlineKeyboardMarkup(btns)


def items_kb(cat_id: str, lang: str) -> InlineKeyboardMarkup:
    rows = []
    for it in MENU.get("items", []):
        if it.get("cat") != cat_id:
            continue
        title = it.get("title_ru") if lang == "ru" else it.get("title_nl", it.get("title_ru"))
        price = it.get("price", 0)
        rows.append(
            [InlineKeyboardButton(f"{title} • €{price:.2f}", callback_data=f"item:{it['id']}")]
        )
    rows.append(
        [
            InlineKeyboardButton(t("back", lang), callback_data="back"),
            InlineKeyboardButton(f"🛒 {t('cart', lang)}", callback_data="cart"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def item_kb(item_id: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Добавить" if lang == "ru" else "➕ Toevoegen", callback_data=f"add:{item_id}")],
            [InlineKeyboardButton(t("back", lang), callback_data="back")],
        ]
    )


def render_cart(uid: int, lang: str) -> str:
    if uid not in CARTS or not CARTS[uid]:
        return I18N["empty_cart"][lang]
    lines = ["🧾 Заказ:" if lang == "ru" else "🧾 Bestelling:"]
    total = 0.0
    for item_id, qty in CARTS[uid].items():
        it = ITEMS.get(item_id)
        if not it:
            continue
        title = it.get("title_ru") if lang == "ru" else it.get("title_nl", it.get("title_ru"))
        price = float(it.get("price", 0))
        lines.append(f"• {title} × {qty} = €{price*qty:.2f}")
        total += price * qty
    lines.append("")
    lines.append(f"Итого: €{total:.2f}" if lang == "ru" else f"Totaal: €{total:.2f}")
    return "\n".join(lines)


# --------- HANDLERS ---------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = user_lang(update)
    await update.message.reply_text(
        t("start", lang), reply_markup=main_kb(lang), parse_mode="Markdown"
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = user_lang(update)
    data = query.data or ""

    if data.startswith("cat:"):
        cat_id = data.split(":", 1)[1]
        cat = CATS.get(cat_id)
        if not cat:
            return
        title = cat.get("title_ru") if lang == "ru" else cat.get("title_nl", cat.get("title_ru"))
        await query.edit_message_text(
            f"{title}:\n{t('choose_item', lang)}",
            reply_markup=items_kb(cat_id, lang),
        )
        return

    if data.startswith("item:"):
        item_id = data.split(":", 1)[1]
        it = ITEMS.get(item_id)
        if not it:
            return
        title = it.get("title_ru") if lang == "ru" else it.get("title_nl", it.get("title_ru"))
        price = float(it.get("price", 0))
        await query.edit_message_text(
            f"{title}\n€{price:.2f}",
            reply_markup=item_kb(item_id, lang),
        )
        return

    if data.startswith("add:"):
        item_id = data.split(":", 1)[1]
        uid = query.from_user.id
        CARTS.setdefault(uid, {})
        CARTS[uid][item_id] = CARTS[uid].get(item_id, 0) + 1
        await query.edit_message_reply_markup(reply_markup=item_kb(item_id, lang))
        await context.bot.send_message(uid, t("added", lang))
        return

    if data == "cart":
        uid = query.from_user.id
        await query.edit_message_text(
            render_cart(uid, lang),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(t("back", lang), callback_data="back")]]
            ),
        )
        return

    if data == "back":
        await query.edit_message_text(
            t("start", lang), reply_markup=main_kb(lang), parse_mode="Markdown"
        )
        return


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # скрываем любые лишние сообщения
    await update.message.reply_text("Используйте кнопки ниже 👇", reply_markup=ReplyKeyboardRemove())


def main() -> None:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))

    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
