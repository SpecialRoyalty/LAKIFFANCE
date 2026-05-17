
import os
import re
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8080"))
TIMEZONE = os.getenv("TIMEZONE", "Europe/Paris")

TZ = ZoneInfo(TIMEZONE)
db_pool = None

URL_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/|discord\.gg/)", re.I)


async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)

    async with db_pool.acquire() as con:
        await con.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS messages(
            chat_id BIGINT NOT NULL,
            message_id BIGINT NOT NULL,
            user_id BIGINT,
            created_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY(chat_id, message_id)
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS media_hashes(
            id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            file_unique_id TEXT NOT NULL,
            message_id BIGINT,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS banned_words(
            word TEXT PRIMARY KEY
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS user_violations(
            user_id BIGINT PRIMARY KEY,
            count INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS reward_videos(
            slot INTEGER PRIMARY KEY,
            file_id TEXT NOT NULL,
            uploaded_at TIMESTAMP DEFAULT NOW()
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS referrals(
            referrer_id BIGINT NOT NULL,
            invited_user_id BIGINT NOT NULL,
            joined_at TIMESTAMP DEFAULT NOW(),
            validated_at TIMESTAMP,
            rewarded BOOLEAN DEFAULT FALSE,
            PRIMARY KEY(referrer_id, invited_user_id)
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS pending_joins(
            user_id BIGINT PRIMARY KEY,
            referrer_id BIGINT,
            joined_at TIMESTAMP DEFAULT NOW()
        )
        """)

        defaults = {
            "moderation": "on",
            "anti_links": "on",
            "anti_photo_mention": "on",
            "anti_repost": "on",
            "auto_schedule": "on",
            "group_open": "off",
            "open_hour": "23",
            "close_hour": "1",
        }

        for k, v in defaults.items():
            await con.execute(
                "INSERT INTO settings(key,value) VALUES($1,$2) ON CONFLICT(key) DO NOTHING",
                k, v
            )


async def get_setting(key, default=None):
    async with db_pool.acquire() as con:
        row = await con.fetchrow("SELECT value FROM settings WHERE key=$1", key)
        return row["value"] if row else default


async def set_setting(key, value):
    async with db_pool.acquire() as con:
        await con.execute("""
        INSERT INTO settings(key,value) VALUES($1,$2)
        ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value
        """, key, value)


async def count_table(table):
    async with db_pool.acquire() as con:
        return await con.fetchval(f"SELECT COUNT(*) FROM {table}")


def is_admin_user(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def led(value):
    return "🟢 ON" if value == "on" else "🔴 OFF"


async def main_panel_keyboard():
    moderation = await get_setting("moderation", "off")
    anti_links = await get_setting("anti_links", "off")
    anti_photo = await get_setting("anti_photo_mention", "off")
    anti_repost = await get_setting("anti_repost", "off")
    auto_schedule = await get_setting("auto_schedule", "off")
    group_open = await get_setting("group_open", "off")

    videos = await count_table("reward_videos")
    video_led = "✅" if videos >= 60 else "❌"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"Modération {led(moderation)}", callback_data="toggle:moderation"),
        ],
        [
            InlineKeyboardButton(f"🔗 Anti-liens {led(anti_links)}", callback_data="toggle:anti_links"),
        ],
        [
            InlineKeyboardButton(f"🖼️ Photo mention {led(anti_photo)}", callback_data="toggle:anti_photo_mention"),
        ],
        [
            InlineKeyboardButton(f"♻️ Anti-repost {led(anti_repost)}", callback_data="toggle:anti_repost"),
        ],
        [
            InlineKeyboardButton(f"⏰ Auto horaires {led(auto_schedule)}", callback_data="toggle:auto_schedule"),
        ],
        [
            InlineKeyboardButton("🟢 Ouvrir maintenant", callback_data="open_group"),
            InlineKeyboardButton("🔴 Fermer + effacer", callback_data="close_group"),
        ],
        [
            InlineKeyboardButton("🚫 Mots interdits", callback_data="words"),
        ],
        [
            InlineKeyboardButton(f"🎁 Vidéos {videos}/60 {video_led}", callback_data="videos"),
        ],
        [
            InlineKeyboardButton("ℹ️ Infos système", callback_data="info"),
        ],
    ])


async def build_status_text(extra=""):
    async with db_pool.acquire() as con:
        videos = await con.fetchval("SELECT COUNT(*) FROM reward_videos")
        msg_count = await con.fetchval("SELECT COUNT(*) FROM messages")
        words = await con.fetchval("SELECT COUNT(*) FROM banned_words")
        moderation = await con.fetchval("SELECT value FROM settings WHERE key='moderation'")
        anti_links = await con.fetchval("SELECT value FROM settings WHERE key='anti_links'")
        anti_photo = await con.fetchval("SELECT value FROM settings WHERE key='anti_photo_mention'")
        anti_repost = await con.fetchval("SELECT value FROM settings WHERE key='anti_repost'")
        auto_schedule = await con.fetchval("SELECT value FROM settings WHERE key='auto_schedule'")
        group_open = await con.fetchval("SELECT value FROM settings WHERE key='group_open'")

    video_ok = "✅" if videos >= 60 else "❌"
    text = (
        "⚙️ PANEL ADMIN\n\n"
        "🗄️ Base PostgreSQL : ✅ branchée\n"
        f"👥 Groupe : {'✅' if GROUP_ID else '❌'} branché\n"
        f"🚪 Groupe ouvert : {led(group_open)}\n\n"
        f"🛡️ Modération : {led(moderation)}\n"
        f"🔗 Anti-liens : {led(anti_links)}\n"
        f"🖼️ Photo mention : {led(anti_photo)}\n"
        f"♻️ Anti-repost : {led(anti_repost)}\n"
        f"⏰ Auto horaires : {led(auto_schedule)}\n\n"
        f"🎁 Vidéos : {videos}/60 {video_ok}\n"
        f"💬 Messages stockés : {msg_count}\n"
        f"🚫 Mots interdits : {words}\n"
    )
    if extra:
        text += f"\n✅ Dernière action : {extra}\n"
    return text


async def safe_edit(query, text, reply_markup=None):
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            await query.answer("Déjà à jour ✅", show_alert=False)
        else:
            raise


async def show_panel(query, extra=""):
    await safe_edit(query, await build_status_text(extra), reply_markup=await main_panel_keyboard())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin_user(update.effective_user.id):
        return
    await update.message.reply_text(await build_status_text(), reply_markup=await main_panel_keyboard())


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not q.from_user or not is_admin_user(q.from_user.id):
        return

    data = q.data

    if data.startswith("toggle:"):
        key = data.split(":", 1)[1]
        current = await get_setting(key, "off")
        new = "off" if current == "on" else "on"
        await set_setting(key, new)
        await show_panel(q, f"{key} = {new.upper()}")
        return

    if data == "info":
        await show_panel(q, "infos actualisées")
        return

    if data == "open_group":
        await open_group(context)
        await show_panel(q, "groupe ouvert")
        return

    if data == "close_group":
        deleted = await close_group_and_clean(context)
        await show_panel(q, f"groupe fermé, {deleted} messages supprimés")
        return

    if data == "videos":
        videos = await count_table("reward_videos")
        await safe_edit(
            q,
            f"🎁 VIDÉOS RÉCOMPENSES\n\nStatut : {videos}/60\n\n"
            "Pour ajouter une vidéo : envoie une vidéo au bot en privé depuis ton compte admin.\n"
            "Le bot la met automatiquement dans le prochain slot libre.\n\n"
            "Objectif : 60 vidéos.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="info")]])
        )
        return

    if data == "words":
        async with db_pool.acquire() as con:
            rows = await con.fetch("SELECT word FROM banned_words ORDER BY word")
        words = "\n".join([f"- {r['word']}" for r in rows]) or "Aucun mot interdit."
        await safe_edit(
            q,
            "🚫 MOTS INTERDITS\n\n"
            f"{words}\n\n"
            "Ajouter : envoie au bot en privé `mot:exemple`\n"
            "Supprimer : envoie `delmot:exemple`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="info")]])
        )
        return


async def open_group(context: ContextTypes.DEFAULT_TYPE):
    await set_setting("group_open", "on")
    perms = ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
    )
    await context.bot.set_chat_permissions(GROUP_ID, perms)
    await context.bot.send_message(GROUP_ID, "🟢 Groupe ouvert, vous pouvez envoyer.")


async def close_group_and_clean(context: ContextTypes.DEFAULT_TYPE):
    await set_setting("group_open", "off")
    perms = ChatPermissions(can_send_messages=False)
    await context.bot.set_chat_permissions(GROUP_ID, perms)

    deleted = 0
    async with db_pool.acquire() as con:
        rows = await con.fetch("SELECT chat_id, message_id FROM messages WHERE chat_id=$1", GROUP_ID)

    for row in rows:
        try:
            await context.bot.delete_message(row["chat_id"], row["message_id"])
            deleted += 1
            await asyncio.sleep(0.03)
        except Exception:
            pass

    async with db_pool.acquire() as con:
        await con.execute("DELETE FROM messages WHERE chat_id=$1", GROUP_ID)

    await context.bot.send_message(GROUP_ID, "🔴 Groupe fermé, vous ne pouvez plus envoyer.")
    return deleted


async def save_message(update: Update):
    if not update.message:
        return
    async with db_pool.acquire() as con:
        await con.execute("""
        INSERT INTO messages(chat_id,message_id,user_id)
        VALUES($1,$2,$3)
        ON CONFLICT DO NOTHING
        """, update.effective_chat.id, update.message.message_id, update.effective_user.id if update.effective_user else None)


async def punish_ban(update: Update, context: ContextTypes.DEFAULT_TYPE, reason: str):
    user = update.effective_user
    if not user:
        return
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
    except Exception:
        pass
    try:
        await update.message.delete()
    except Exception:
        pass
    await context.bot.send_message(
        update.effective_chat.id,
        f"🚫 {user.mention_html()} a été banni pour {reason}. Ne faites pas la même erreur.",
        parse_mode="HTML"
    )


async def punish_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    async with db_pool.acquire() as con:
        row = await con.fetchrow("SELECT count FROM user_violations WHERE user_id=$1", user.id)
        count = (row["count"] if row else 0) + 1
        await con.execute("""
        INSERT INTO user_violations(user_id,count,updated_at)
        VALUES($1,$2,NOW())
        ON CONFLICT(user_id) DO UPDATE SET count=$2, updated_at=NOW()
        """, user.id, count)

    try:
        await update.message.delete()
    except Exception:
        pass

    if count == 1:
        until = datetime.now(TZ) + timedelta(days=1)
        await context.bot.restrict_chat_member(update.effective_chat.id, user.id, ChatPermissions(can_send_messages=False), until_date=until)
        action = "mute 1 jour"
    elif count == 2:
        until = datetime.now(TZ) + timedelta(days=7)
        await context.bot.restrict_chat_member(update.effective_chat.id, user.id, ChatPermissions(can_send_messages=False), until_date=until)
        action = "mute 1 semaine"
    else:
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
        action = "ban"

    await context.bot.send_message(update.effective_chat.id, f"🚫 {user.mention_html()} sanctionné : {action}. Respectez les règles.", parse_mode="HTML")


def message_file_unique_id(msg):
    if msg.photo:
        return msg.photo[-1].file_unique_id
    if msg.video:
        return msg.video.file_unique_id
    if msg.animation:
        return msg.animation.file_unique_id
    if msg.document:
        return msg.document.file_unique_id
    return None


async def handle_private_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin_user(update.effective_user.id):
        return

    msg = update.message
    if msg.video:
        async with db_pool.acquire() as con:
            slot = await con.fetchval("SELECT COALESCE(MAX(slot),0)+1 FROM reward_videos")
            if slot > 60:
                await msg.reply_text("✅ Les 60 vidéos sont déjà uploadées.")
                return
            await con.execute("INSERT INTO reward_videos(slot,file_id) VALUES($1,$2)", slot, msg.video.file_id)
        await msg.reply_text(f"✅ Vidéo ajoutée : {slot}/60")
        return

    text = msg.text or ""
    if text.startswith("mot:"):
        word = text.split(":", 1)[1].strip().lower()
        async with db_pool.acquire() as con:
            await con.execute("INSERT INTO banned_words(word) VALUES($1) ON CONFLICT DO NOTHING", word)
        await msg.reply_text(f"✅ Mot interdit ajouté : {word}")
        return

    if text.startswith("delmot:"):
        word = text.split(":", 1)[1].strip().lower()
        async with db_pool.acquire() as con:
            await con.execute("DELETE FROM banned_words WHERE word=$1", word)
        await msg.reply_text(f"✅ Mot supprimé : {word}")
        return


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID or not update.message:
        return

    await save_message(update)

    moderation = await get_setting("moderation", "on")
    if moderation != "on":
        return

    msg = update.message
    text = (msg.text or msg.caption or "").lower()

    if await get_setting("anti_links", "on") == "on" and URL_RE.search(text):
        await punish_ban(update, context, "envoi de lien")
        return

    if await get_setting("anti_photo_mention", "on") == "on":
        has_photo = bool(msg.photo)
        has_mention = bool(msg.caption_entities and any(e.type in ("mention", "text_mention") for e in msg.caption_entities))
        if has_photo and has_mention:
            await punish_ban(update, context, "photo avec identification")
            return

    async with db_pool.acquire() as con:
        words = await con.fetch("SELECT word FROM banned_words")
    for row in words:
        if row["word"] and row["word"].lower() in text:
            await punish_word(update, context)
            return

    if await get_setting("anti_repost", "on") == "on":
        fid = message_file_unique_id(msg)
        if fid:
            async with db_pool.acquire() as con:
                old = await con.fetchrow("""
                SELECT id FROM media_hashes
                WHERE chat_id=$1 AND file_unique_id=$2 AND created_at > NOW() - INTERVAL '4 days'
                LIMIT 1
                """, GROUP_ID, fid)

                if old:
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    await context.bot.send_message(GROUP_ID, "♻️ C’est du vu et déjà vu.")
                    return

                await con.execute("""
                INSERT INTO media_hashes(chat_id,file_unique_id,message_id)
                VALUES($1,$2,$3)
                """, GROUP_ID, fid, msg.message_id)


async def hourly_job(context: ContextTypes.DEFAULT_TYPE):
    if await get_setting("auto_schedule", "on") != "on":
        return

    now = datetime.now(TZ)
    open_hour = int(await get_setting("open_hour", "23"))
    close_hour = int(await get_setting("close_hour", "1"))

    if now.minute != 0:
        return

    if now.hour == open_hour:
        await open_group(context)
    elif now.hour == close_hour:
        await close_group_and_clean(context)
    else:
        target = now.replace(hour=open_hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        hours = int((target - now).total_seconds() // 3600)
        try:
            await context.bot.send_message(GROUP_ID, f"⏰ Prochaine ouverture dans {hours} heure(s).")
        except Exception:
            pass


async def post_init(app):
    await init_db()
    app.job_queue.run_repeating(hourly_job, interval=60, first=10)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"ERROR: {context.error}")


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE, handle_private_admin))
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & ~filters.COMMAND, handle_group_message))
    app.add_error_handler(error_handler)

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
    )


if __name__ == "__main__":
    main()
