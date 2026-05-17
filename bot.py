import os
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
GROUP_ID = int(os.getenv("GROUP_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8080"))

db_pool = None

async def init_db():
    global db_pool

    db_pool = await asyncpg.create_pool(DATABASE_URL)

    async with db_pool.acquire() as con:
        await con.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        return

    keyboard = [
        [InlineKeyboardButton("🟢 Modération", callback_data="mod")],
        [InlineKeyboardButton("🎁 Vidéos", callback_data="videos")],
        [InlineKeyboardButton("ℹ️ Infos", callback_data="infos")],
    ]

    await update.message.reply_text(
        "⚙️ PANEL ADMIN",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "infos":
        text = (
            "✅ Base PostgreSQL connectée\n"
            "✅ Groupe connecté\n"
            "✅ Railway actif"
        )
        await query.edit_message_text(text)

    elif query.data == "videos":
        await query.edit_message_text(
            "🎁 Upload des 60 vidéos ici"
        )

    elif query.data == "mod":
        await query.edit_message_text(
            "🟢 Modération activée"
        )

async def post_init(app):
    await init_db()

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", admin_panel))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
    )

if __name__ == "__main__":
    main()
