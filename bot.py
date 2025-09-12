# bot.py — PTB v20+

import os
import json
import logging
from typing import Dict, Any, List, Optional

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

# ======= ENV =======
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")  # строка ок
TZ = os.getenv("TZ", "Europe/Amsterdam")
MENU_FILE = os.getenv("MENU_FILE", "menu.json")

if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN env var")

# ======= LOGGING =======
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("sushi-bot")

# ======= MENU =======
# ожидаемый формат menu.json:
# {
#   "categories": [
#     {"id":"sets","title_ru":"Сеты","title_nl":"Sets"},
#     {"id":"rolls","title_ru":"Роллы","title_nl":"Rollen"}
#   ],
#   "items": [
#     {"id":"r1","cat":"rolls","title_ru":"Калифорния","title_nl":"California","price":8.5},
#     ...
#   ]
# }
with open(MENU_FILE, "r", encoding="utf-8") as f:
    MENU: Dict[str, Any] = json.load(f)

CATEGORIES: List[Dict[str, Any]] = MENU.get("categories", [])
ITEMS: List[Dict[str, Any]] = MENU.get("items", [])

# ======= i18n (минимальный) =======
I18N = {
    "start": {
        "ru": "Привет! Это магазин *Sushi Aurum*.\nВыберите раздел:",
        "nl": "Hoi! Dit is *Sushi Aurum*.\nKies een categorie:",
    },
    "browse": {"ru": "📁 Меню", "nl": "📁 Menu"},
    "cart": {"ru": "🛒 Корзина", "nl": "🛒 Winkelmand"},
    "back": {"ru": "◀️ Назад", "nl": "◀️ Terug"},
    "empty_cart": {"ru": "🟦 Корзина пуста.", "nl": "🟦 Je mandje is leeg."},
    "choose_cat": {"ru": "Выберите раздел:", "nl": "Kies een categorie:"},
    "choose_item": {"ru": "Выберите позицию:", "nl": "Kies een artikel:"},
    "added": {"ru": "✅ Добавлено в корзину.", "nl": "✅ Toegevoegd aan mandje."},
}

# ======= STATE =======
# user_id -> {item_id: qty}
CARTS: Dict[int, Dict[str, int]] = {}


# ======= helpers =======
def lang_of_user(update: Update) -> str:
    # простое правило: если в PENDING нет данных, дефолт "ru"
    return "ru"

def t(key: str, lang: str) -> str:
    return I18N.get(key, {}).get(lang, I18N.get(key, {}).get("ru", key))

def title_of(obj: Dict[str, Any], lang: str) -> str:
    if lang == "nl":
        return obj.get("title_nl") or obj.get("title_ru") or "—"
    return obj.get("title_ru") or obj.get("title_nl") or "—"

def categories_kb(lang: str) -> InlineKeyboardMarkup:
    rows = []
    row: List[InlineKeyboardButton] = []
    for cat in CATEGORIES:
        row.append(
            InlineKeyboardButton(
                title_of(cat, lang), callback_data=f"cat:{cat['id']}"
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    # низ — кнопка корзины
    rows.append([InlineKeyboardButton(t("cart", lang), callback_data="cart")])
    return InlineKeyboardMarkup(rows)

def items_kb(cat_id: str, lang: str) -> InlineKeyboardMarkup:
    rows = []
    for it in [x for x in ITEMS if x.get("cat") == cat_id]:
        title = f"{title_of(it, lang)} — {it.get('price', 0):.2f}"
        rows.append(
            [InlineKeyboardButton(title, callback_data=f"add:{it['id']}:{cat_id}")]
        )
    rows.append([InlineKeyboardButton(t("back", lang), callback_data="browse")])
    rows.append([InlineKeyboardButton(t("cart", lang), callback_data="cart")])
    return InlineKeyboardMarkup(rows)

def cart_text(uid: int, lang: str) -> str:
    cart = CARTS.get(uid, {})
    if not cart:
        return t("empty_cart", lang)
    lines = []
    total = 0.0
    for item_id, qty in cart.items():
        it = next((x for x in ITEMS if x["id"] == item_id), None)
        if not it:
            continue
        price = float(it.get("price", 0.0))
        total += price * qty
        lines.append(f"• {title_of(it, lang)} × {qty} = {price*qty:.2f}")
    lines.append(f"\nИтого: {total:.2f}" if lang == "ru" else f"\nTotaal: {total:.2f}")
    return "\n".join(lines)

def cart_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("back", lang), callback_data="browse")],
        ]
    )


# ======= handlers =======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = lang_of_user(update)
    await update.message.reply_text(
        t("start", lang), reply_markup=categories_kb(lang), parse_mode="Markdown"
    )

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query is not None
    await query.answer()
    lang = lang_of_user(update)
    data = query.data or ""

    # показать категории
    if data == "browse":
        await query.edit_message_text(
            t("choose_cat", lang), reply_markup=categories_kb(lang)
        )
        return

    # корзина
    if data == "cart":
        uid = update.effective_user.id
        await query.edit_message_text(
            cart_text(uid, lang), reply_markup=cart_kb(lang)
        )
        return

    # открыть категорию
    if data.startswith("cat:"):
        cat_id = data.split(":", 1)[1]
        await query.edit_message_text(
            t("choose_item", lang), reply_markup=items_kb(cat_id, lang)
        )
        return

    # добавить товар
    if data.startswith("add:"):
        # формат add:<item_id>:<cat_id>
        parts = data.split(":")
        if len(parts) >= 3:
            item_id, cat_id = parts[1], parts[2]
        else:
            item_id, cat_id = parts[1], ""
        uid = update.effective_user.id
        CARTS.setdefault(uid, {})
        CARTS[uid][item_id] = CARTS[uid].get(item_id, 0) + 1
        # показать подтверждение и снова список позиций
        await query.edit_message_text(
            t("added", lang), reply_markup=items_kb(cat_id, lang)
        )
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # на любой текст показываем главное меню
    lang = lang_of_user(update)
    await update.message.reply_text(
        t("start", lang), reply_markup=categories_kb(lang), parse_mode="Markdown"
    )


# ======= MAIN =======
def main() -> None:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
