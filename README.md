# Sushi Aurum — Telegram Shop Bot

Минимально‑рабочий бот‑магазин на **python-telegram-bot 20** + **SQLite (SQLAlchemy)**.
Функции MVP:
- Выбор языка (RU/NL)
- Просмотр категорий и позиций из `menu.json`
- Корзина: добавить/удалить/очистить
- Оформление заказа: доставка или самовывоз, адрес, телефон, комментарий
- Сохранение заказов в SQLite, уведомление администратора
- Админ-команды: /orders, /setstatus <id> <NEW|COOKING|ON_THE_WAY|DONE|CANCELLED>

## Быстрый старт

1) Установите зависимости:
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

2) Создайте бота у @BotFather — возьмите **BOT_TOKEN**. Узнайте свой **ADMIN_CHAT_ID** (напишите боту @userinfobot).

3) Создайте файл `.env` в корне:
```
BOT_TOKEN=123456:ABC...yourtoken
ADMIN_CHAT_ID=123456789
```
(или задайте эти переменные окружения иным способом)

4) Запустите локально (long polling):
```
python bot.py
```

5) Развернуть на сервере можно на любой платформе (Railway/Render/Docker). Для вебхука используйте переменную `WEBHOOK_URL`.
Пример:
```
WEBHOOK_URL=https://your-domain.com/telegram webhook secret path
```

## Платежи
Сейчас включена «оплата при получении». Интеграцию с Telegram Payments (Stripe) можно добавить позже.

## Структура
- `bot.py` — код бота
- `menu.json` — меню
- `db.sqlite3` — база (создастся автоматически)