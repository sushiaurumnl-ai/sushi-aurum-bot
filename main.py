import os
from pyrogram import Client, filters
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID = int(os.environ.get("API_ID", "12345"))
API_HASH = os.environ.get("API_HASH", "your_api_hash")

app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("start") & filters.private)
async def start_handler(_, message):
    await message.reply_text("Бот запущен ✅")

@app.on_message(filters.command("ping"))
async def ping_handler(_, message):
    await message.reply_text("pong")

if __name__ == "__main__":
    app.run()

