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

# ======== ENV ========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
TZ = os.getenv("TZ", "Europe/Amsterdam")
MENU_FILE = os.getenv("MENU_FILE", "menu.json")

if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN env var")

# ======== LOGGING ========
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("sushi-bot")

# ======== DATA ========
def load_menu(path: str) -> Dict[str, Any]:
    """Load menu.json. Minimal shape:
    {
      "categories":[{"id":"sets","title_ru":"Сеты","title_nl":"Sets"}],
      "items":[{"id":"r1","cat_id":"sets","title_ru":"Калифорния","title_nl":"California","price":6.5}]
    }
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log.error("Cannot read %s: %s", path, e)
        data = {"categories": [], "items": []}
    # normalize
    data.setdefault("categories", [])
    data.setdefault("items", [])
    return data

MENU = load_menu(MENU_FILE)
CATS: List[Dict[str, Any]] = MENU["categories"]
ITEMS: List[Dict[str, Any]] = MENU["items"]

# ======== I18N ========
I18N = {
    "start": {
        "ru": "Привет! Это магазин *Sushi Aurum*. Выберите раздел:",
        "nl": "Hoi! Dit is *Sushi Aurum*. Kies rubriek:",
    },
    "browse": {"ru": "📂 Меню", "nl": "📂 Menu"},
    "cart": {"ru": "🛒 Корзина", "nl": "🛒 Winkelmand"},
    "empty_cart": {"ru": "🫙 Корзина пуста.", "nl": "🫙 Je mandje is leeg."},
    "choose_cat": {"ru": "Выберите категорию:", "nl": "Kies categorie:"},
    "choose_item": {"ru": "Выберите позицию:", "nl": "Kies item:"},
    "add": {"ru": "➕ Добавить", "nl": "➕ Toevoegen"},
    "added": {"ru": "✅ Добавлено", "nl": "✅ Toegevoegd"},
    "back": {"ru": "⬅️ Назад", "nl": "⬅️ Terug"},
    "sum": {"ru": "Итого", "nl": "Totaal"},
}

def t(key: str, lang: str) -> str:
    return I18N.get(key, {}).get(lang, I18N.get(key, {}).get("ru", key))

# ======== STATE ========
# carts: user_id -> {item_id: qty}
CARTS: Dict[int, Dict[str, int]] = {}
# pending simple per-user prefs
PENDING: Dict[int, Dict[str, Any]] = {}

def user_lang(update: Update) -> str:
    uid = update.effective_user.id if update.effective_user else 0
    if uid in PENDING and "lang" in PENDING[uid]:
        return PENDING[uid]["lang"]
    # heuristic from Telegram locale
    loc = (update.effective_user.language_code or "ru").lower() if update.effective_user else "ru"
    return "nl" if loc.startswith("nl") else "ru"

def money(x: float) -> str:
    return f"{x:.2f}"

# ======== KEYBOARDS ========
def main_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("browse", lang), callback_data="browse")],
        [InlineKeyboardButton(t("cart", lang), callback_data="cart")],
    ])

def cats_kb(lang: str) -> InlineKeyboardMarkup:
    rows = []
    row: List[InlineKeyboardButton] = []
    for c in CATS:
        title = c.get("title_ru") if lang == "ru" else c.get("title_nl", c.get("title_ru", ""))
        row.append(InlineKeyboardButton(title, callback_data=f"cat:{c['id']}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(t("back", lang), callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def items_kb(cat_id: str, lang: str) -> InlineKeyboardMarkup:
    rows = []
    items = [x for x in ITEMS if x.get("cat_id") == cat_id]
    row: List[InlineKeyboardButton] = []
    for it in items:
        title = it.get("title_ru") if lang == "ru" else it.get("title_nl", it.get("title_ru", ""))
        price = it.get("price", 0.0)
        text = f"{title} · €{money(float(price))}"
        row.append(InlineKeyboardButton(text, callback_data=f"item:{it['id']}"))
        if len(row) == 1:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(t("back", lang), callback_data="browse")])
    return InlineKeyboardMarkup(rows)

def item_kb(item_id: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("add", lang), callback_data=f"add:{item_id}")],
        [InlineKeyboardButton(t("back", lang), callback_data=f"back_to_cat:{item_id}")],
    ])

# ======== HELPERS ========
def find_cat(cat_id: str) -> Optional[Dict[str, Any]]:
    return next((c for c in CATS if c.get("id") == cat_id), None)

def find_item(item_id: str) -> Optional[Dict[str, Any]]:
    return next((i for i in ITEMS if i.get("id") == item_id), None)

def item_cat_id(item_id: str) -> Optional[str]:
    it = find_item(item_id)
    return it.get("cat_id") if it else None

async def show_cart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = user_lang(update)
    uid = update.effective_user.id
    cart = CARTS.get(uid, {})
    if not cart:
        await update.callback_query.edit_message_text(t("empty_cart", lang), reply_markup=main_kb(lang))
        return
    lines = []
    total = 0.0
    for iid, qty in cart.items():
        it = find_item(iid)
        if not it:
            continue
        title = it.get("title_ru") if lang == "ru" else it.get("title_nl", it.get("title_ru", ""))
        price = float(it.get("price", 0.0))
        lines.append(f"• {title} × {qty} = €{money(price * qty)}")
        total += price * qty
    lines.append("")
    lines.append(f"{t('sum', lang)}: €{money(total)}")
    await update.callback_query.edit_message_text("\n".join(lines), reply_markup=main_kb(lang))

# ======== HANDLERS ========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = user_lang(update)
    await update.message.reply_text(t("start", lang), reply_markup=main_kb(lang), parse_mode="Markdown")

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    lang = user_lang(update)

    data = q.data or ""

    if data == "back_main":
        await q.edit_message_text(t("start", lang), reply_markup=main_kb(lang), parse_mode="Markdown")
        return

    if data == "browse":
        # list categories
        await q.edit_message_text(t("choose_cat", lang), reply_markup=cats_kb(lang))
        return

    if data.startswith("cat:"):
        cat_id = data.split(":", 1)[1]
        c = find_cat(cat_id)
        if not c:
            return
        title = c.get("title_ru") if lang == "ru" else c.get("title_nl", c.get("title_ru", ""))
        await q.edit_message_text(title, reply_markup=items_kb(cat_id, lang))
        return

    if data.startswith("item:"):
        item_id = data.split(":", 1)[1]
        it = find_item(item_id)
        if not it:
            return
        title = it.get("title_ru") if lang == "ru" else it.get("title_nl", it.get("title_ru", ""))
        price = float(it.get("price", 0.0))
        text = f"{title}\n€{money(price)}"
        await q.edit_message_text(text, reply_markup=item_kb(item_id, lang))
        return

    if data.startswith("back_to_cat:"):
        item_id = data.split(":", 1)[1]
        cat_id = item_cat_id(item_id)
        if not cat_id:
            return
        c = find_cat(cat_id)
        title = c.get("title_ru") if lang == "ru" else c.get("title_nl", c.get("title_ru", ""))
        await q.edit_message_text(title, reply_markup=items_kb(cat_id, lang))
        return

    if data == "cart":
        await show_cart(update, context)
        return

    if data.startswith("add:"):
        uid = update.effective_user.id
        item_id = data.split(":", 1)[1]
        CARTS.setdefault(uid, {})
        CARTS[uid][item_id] = CARTS[uid].get(item_id, 0) + 1
        await q.edit_message_text(t("added", lang), reply_markup=main_kb(lang))
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # простой ответ — отправляем главное меню
    lang = user_lang(update)
    await update.message.reply_text(t("start", lang), reply_markup=main_kb(lang), parse_mode="Markdown")

# ======== MAIN ========
def main() -> None:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
