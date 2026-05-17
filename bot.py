
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

APP_VERSION = "SESSION_CLEAN_V6_2026_05_18"

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

    print(f"STARTING BOT VERSION: {APP_VERSION}", flush=True)
    db_pool = await asyncpg.create_pool(DATABASE_URL)

    async with db_pool.acquire() as con:
        await con.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS sessions(
            id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            opened_at TIMESTAMP DEFAULT NOW(),
            closed_at TIMESTAMP
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS messages(
            chat_id BIGINT NOT NULL,
            message_id BIGINT NOT NULL,
            user_id BIGINT,
            session_id INTEGER,
            is_bot BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY(chat_id, message_id)
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS system_messages(
            chat_id BIGINT PRIMARY KEY,
            message_id BIGINT,
            kind TEXT,
            created_at TIMESTAMP DEFAULT NOW()
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
            word TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT NOW()
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

        await con.execute("""
        CREATE TABLE IF NOT EXISTS admin_states(
            user_id BIGINT PRIMARY KEY,
            state TEXT,
            updated_at TIMESTAMP DEFAULT NOW()
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
            "current_session_id": "0",
        }

        for k, v in defaults.items():
            await con.execute(
                "INSERT INTO settings(key,value) VALUES($1,$2) ON CONFLICT(key) DO NOTHING",
                k, v
            )

        rows = await con.fetch("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='public'
        ORDER BY table_name
        """)
        print("TABLES IN DATABASE:", [r["table_name"] for r in rows], flush=True)


async def get_setting(key, default=None):
    async with db_pool.acquire() as con:
        row = await con.fetchrow("SELECT value FROM settings WHERE key=$1", key)
        return row["value"] if row else default


async def set_setting(key, value):
    async with db_pool.acquire() as con:
        await con.execute("""
        INSERT INTO settings(key,value) VALUES($1,$2)
        ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value
        """, key, str(value))


async def count_table(table):
    async with db_pool.acquire() as con:
        return await con.fetchval(f"SELECT COUNT(*) FROM {table}")


async def get_current_session_id():
    sid = await get_setting("current_session_id", "0")
    try:
        return int(sid)
    except Exception:
        return 0


async def create_open_session():
    async with db_pool.acquire() as con:
        sid = await con.fetchval(
            "INSERT INTO sessions(chat_id) VALUES($1) RETURNING id",
            GROUP_ID
        )
    await set_setting("current_session_id", sid)
    return sid


async def close_current_session():
    sid = await get_current_session_id()
    if sid:
        async with db_pool.acquire() as con:
            await con.execute("UPDATE sessions SET closed_at=NOW() WHERE id=$1", sid)
    await set_setting("current_session_id", "0")
    return sid


async def save_message_by_ids(chat_id, message_id, user_id=None, is_bot=False, session_id=None):
    if session_id is None:
        session_id = await get_current_session_id()
    async with db_pool.acquire() as con:
        await con.execute("""
        INSERT INTO messages(chat_id,message_id,user_id,is_bot,session_id)
        VALUES($1,$2,$3,$4,$5)
        ON CONFLICT DO NOTHING
        """, chat_id, message_id, user_id, is_bot, session_id)


async def delete_last_system_message(context: ContextTypes.DEFAULT_TYPE):
    async with db_pool.acquire() as con:
        row = await con.fetchrow("SELECT message_id FROM system_messages WHERE chat_id=$1", GROUP_ID)

    if row and row["message_id"]:
        try:
            await context.bot.delete_message(GROUP_ID, row["message_id"])
            await asyncio.sleep(0.05)
        except Exception as e:
            print(f"OLD SYSTEM DELETE FAILED: {e}", flush=True)

    async with db_pool.acquire() as con:
        await con.execute("DELETE FROM system_messages WHERE chat_id=$1", GROUP_ID)


async def send_system_message(context: ContextTypes.DEFAULT_TYPE, text: str, kind: str, record_in_session=True):
    await delete_last_system_message(context)
    msg = await context.bot.send_message(GROUP_ID, text)

    async with db_pool.acquire() as con:
        await con.execute("""
        INSERT INTO system_messages(chat_id,message_id,kind,created_at)
        VALUES($1,$2,$3,NOW())
        ON CONFLICT(chat_id) DO UPDATE SET message_id=$2, kind=$3, created_at=NOW()
        """, GROUP_ID, msg.message_id, kind)

    if record_in_session:
        await save_message_by_ids(GROUP_ID, msg.message_id, None, True)

    print(f"SYSTEM MESSAGE SAVED: {kind} {msg.message_id}", flush=True)
    return msg


async def set_admin_state(user_id, state):
    async with db_pool.acquire() as con:
        if state is None:
            await con.execute("DELETE FROM admin_states WHERE user_id=$1", user_id)
        else:
            await con.execute("""
            INSERT INTO admin_states(user_id,state,updated_at)
            VALUES($1,$2,NOW())
            ON CONFLICT(user_id) DO UPDATE SET state=$2, updated_at=NOW()
            """, user_id, state)


async def get_admin_state(user_id):
    async with db_pool.acquire() as con:
        row = await con.fetchrow("SELECT state FROM admin_states WHERE user_id=$1", user_id)
        return row["state"] if row else None


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
    videos = await count_table("reward_videos")
    video_led = "✅" if videos >= 60 else "❌"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🛡️ Modération {led(moderation)}", callback_data="toggle:moderation")],
        [InlineKeyboardButton(f"🔗 Anti-liens {led(anti_links)}", callback_data="toggle:anti_links")],
        [InlineKeyboardButton(f"🖼️ Photo mention {led(anti_photo)}", callback_data="toggle:anti_photo_mention")],
        [InlineKeyboardButton(f"♻️ Anti-repost {led(anti_repost)}", callback_data="toggle:anti_repost")],
        [InlineKeyboardButton(f"⏰ Auto horaires {led(auto_schedule)}", callback_data="toggle:auto_schedule")],
        [
            InlineKeyboardButton("🟢 Ouvrir session", callback_data="open_group"),
            InlineKeyboardButton("🔴 Fermer + effacer session", callback_data="close_group"),
        ],
        [InlineKeyboardButton("🚫 Mots interdits", callback_data="words_menu")],
        [InlineKeyboardButton(f"🎁 Vidéos {videos}/60 {video_led}", callback_data="videos_menu")],
        [InlineKeyboardButton("ℹ️ Infos système", callback_data="info")],
    ])


def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Retour", callback_data="info")]])


async def words_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Ajouter un mot", callback_data="word_add"),
            InlineKeyboardButton("➖ Supprimer un mot", callback_data="word_delete"),
        ],
        [InlineKeyboardButton("📋 Voir les mots", callback_data="word_list")],
        [InlineKeyboardButton("⬅️ Retour", callback_data="info")],
    ])


async def build_status_text(extra=""):
    async with db_pool.acquire() as con:
        videos = await con.fetchval("SELECT COUNT(*) FROM reward_videos")
        msg_count = await con.fetchval("SELECT COUNT(*) FROM messages")
        words = await con.fetchval("SELECT COUNT(*) FROM banned_words")
        sessions = await con.fetchval("SELECT COUNT(*) FROM sessions")
        moderation = await con.fetchval("SELECT value FROM settings WHERE key='moderation'")
        anti_links = await con.fetchval("SELECT value FROM settings WHERE key='anti_links'")
        anti_photo = await con.fetchval("SELECT value FROM settings WHERE key='anti_photo_mention'")
        anti_repost = await con.fetchval("SELECT value FROM settings WHERE key='anti_repost'")
        auto_schedule = await con.fetchval("SELECT value FROM settings WHERE key='auto_schedule'")
        group_open = await con.fetchval("SELECT value FROM settings WHERE key='group_open'")

    sid = await get_current_session_id()
    video_ok = "✅" if videos >= 60 else "❌"

    text = (
        "⚙️ PANEL ADMIN\n\n"
        f"🧩 Version : {APP_VERSION}\n"
        "🗄️ Base PostgreSQL : ✅ branchée\n"
        f"👥 Groupe : {'✅' if GROUP_ID else '❌'} branché\n"
        f"🚪 Groupe ouvert : {led(group_open)}\n"
        f"🧾 Session active : {sid if sid else 'aucune'}\n\n"
        f"🛡️ Modération : {led(moderation)}\n"
        f"🔗 Anti-liens : {led(anti_links)}\n"
        f"🖼️ Photo mention : {led(anti_photo)}\n"
        f"♻️ Anti-repost : {led(anti_repost)}\n"
        f"⏰ Auto horaires : {led(auto_schedule)}\n\n"
        f"🎁 Vidéos : {videos}/60 {video_ok}\n"
        f"💬 Messages stockés : {msg_count}\n"
        f"🧾 Sessions : {sessions}\n"
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
    await set_admin_state(update.effective_user.id, None)
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
        await set_admin_state(q.from_user.id, None)
        await show_panel(q, "infos actualisées")
        return

    if data == "open_group":
        await open_group(context)
        await show_panel(q, "session ouverte")
        return

    if data == "close_group":
        deleted = await close_group_and_clean(context)
        await show_panel(q, f"session fermée, {deleted} messages supprimés")
        return

    if data == "words_menu":
        await set_admin_state(q.from_user.id, None)
        await safe_edit(q, "🚫 MOTS INTERDITS\n\nChoisis une action :", reply_markup=await words_keyboard())
        return

    if data == "word_add":
        await set_admin_state(q.from_user.id, "adding_word")
        await safe_edit(q, "➕ AJOUTER UN MOT\n\nEnvoie maintenant le mot interdit en message privé au bot.", reply_markup=back_keyboard())
        return

    if data == "word_delete":
        await set_admin_state(q.from_user.id, "deleting_word")
        await safe_edit(q, "➖ SUPPRIMER UN MOT\n\nEnvoie maintenant le mot à supprimer en message privé au bot.", reply_markup=back_keyboard())
        return

    if data == "word_list":
        async with db_pool.acquire() as con:
            rows = await con.fetch("SELECT word FROM banned_words ORDER BY word")
        words = "\n".join([f"• {r['word']}" for r in rows]) or "Aucun mot interdit."
        await safe_edit(q, f"📋 LISTE DES MOTS INTERDITS\n\n{words}", reply_markup=await words_keyboard())
        return

    if data == "videos_menu":
        videos = await count_table("reward_videos")
        await safe_edit(
            q,
            f"🎁 VIDÉOS RÉCOMPENSES\n\nStatut : {videos}/60 {'✅' if videos >= 60 else '❌'}\n\n"
            "Pour ajouter une vidéo, envoie une vidéo au bot en privé depuis ton compte admin.",
            reply_markup=back_keyboard()
        )
        return


async def open_group(context: ContextTypes.DEFAULT_TYPE):
    # Supprime l'ancien message système fermé/ouvert avant d'ouvrir
    await delete_last_system_message(context)

    sid = await create_open_session()
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

    # Le message d'ouverture est dans la session, donc il sera supprimé à la fermeture.
    await send_system_message(context, "🟢 Groupe ouvert, vous pouvez envoyer.", "open", record_in_session=True)
    print(f"OPEN SESSION: {sid}", flush=True)


async def close_group_and_clean(context: ContextTypes.DEFAULT_TYPE):
    sid = await get_current_session_id()
    await set_setting("group_open", "off")

    perms = ChatPermissions(can_send_messages=False)
    await context.bot.set_chat_permissions(GROUP_ID, perms)

    if sid:
        async with db_pool.acquire() as con:
            rows = await con.fetch("""
            SELECT chat_id, message_id
            FROM messages
            WHERE chat_id=$1 AND session_id=$2
            ORDER BY created_at ASC
            """, GROUP_ID, sid)
    else:
        async with db_pool.acquire() as con:
            rows = await con.fetch("""
            SELECT chat_id, message_id
            FROM messages
            WHERE chat_id=$1
            ORDER BY created_at ASC
            """, GROUP_ID)

    print(f"CLOSING SESSION {sid}. MESSAGES TO DELETE: {len(rows)}", flush=True)

    deleted = 0
    for row in rows:
        try:
            await context.bot.delete_message(row["chat_id"], row["message_id"])
            deleted += 1
            await asyncio.sleep(0.04)
        except Exception as e:
            print(f"DELETE FAILED message_id={row['message_id']} error={e}", flush=True)

    # Sécurité : supprime aussi le dernier message système si Telegram ne l'a pas pris dans la boucle.
    await delete_last_system_message(context)

    async with db_pool.acquire() as con:
        if sid:
            await con.execute("DELETE FROM messages WHERE chat_id=$1 AND session_id=$2", GROUP_ID, sid)
        else:
            await con.execute("DELETE FROM messages WHERE chat_id=$1", GROUP_ID)

    await close_current_session()

    # Le message fermé ne fait PAS partie de la session nettoyée.
    await send_system_message(context, "🔴 Groupe fermé, vous ne pouvez plus envoyer.", "closed", record_in_session=False)
    return deleted


async def save_update_message(update: Update):
    if not update.message:
        return
    # On enregistre seulement les messages envoyés pendant une session ouverte.
    if await get_setting("group_open", "off") != "on":
        return
    sid = await get_current_session_id()
    if not sid:
        return
    await save_message_by_ids(
        update.effective_chat.id,
        update.message.message_id,
        update.effective_user.id if update.effective_user else None,
        False,
        sid
    )


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

    msg = await context.bot.send_message(
        update.effective_chat.id,
        f"🚫 {user.mention_html()} a été banni pour {reason}. Ne faites pas la même erreur.",
        parse_mode="HTML"
    )
    await save_message_by_ids(update.effective_chat.id, msg.message_id, None, True)


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

    msg = await context.bot.send_message(
        update.effective_chat.id,
        f"🚫 {user.mention_html()} sanctionné : {action}. Respectez les règles.",
        parse_mode="HTML"
    )
    await save_message_by_ids(update.effective_chat.id, msg.message_id, None, True)


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
    user_id = update.effective_user.id
    state = await get_admin_state(user_id)

    if msg.video:
        async with db_pool.acquire() as con:
            slot = await con.fetchval("SELECT COALESCE(MAX(slot),0)+1 FROM reward_videos")
            if slot > 60:
                await msg.reply_text("✅ Les 60 vidéos sont déjà uploadées.")
                return
            await con.execute("INSERT INTO reward_videos(slot,file_id) VALUES($1,$2)", slot, msg.video.file_id)
        await msg.reply_text(f"✅ Vidéo ajoutée : {slot}/60")
        return

    text = (msg.text or "").strip()

    if state == "adding_word":
        word = text.lower()
        if not word:
            await msg.reply_text("❌ Envoie un vrai mot.")
            return
        async with db_pool.acquire() as con:
            await con.execute("INSERT INTO banned_words(word) VALUES($1) ON CONFLICT DO NOTHING", word)
        await set_admin_state(user_id, None)
        await msg.reply_text(f"✅ Mot interdit ajouté : {word}")
        return

    if state == "deleting_word":
        word = text.lower()
        async with db_pool.acquire() as con:
            await con.execute("DELETE FROM banned_words WHERE word=$1", word)
        await set_admin_state(user_id, None)
        await msg.reply_text(f"✅ Mot supprimé : {word}")
        return

    await msg.reply_text("Admin prêt. Envoie /start pour ouvrir le panel.")


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID or not update.message:
        return

    await save_update_message(update)

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
        word = row["word"].lower()
        if word and re.search(rf"\b{re.escape(word)}\b", text, re.I):
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
                    warn = await context.bot.send_message(GROUP_ID, "♻️ C’est du vu et déjà vu.")
                    await save_message_by_ids(GROUP_ID, warn.message_id, None, True)
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
            await send_system_message(context, f"⏰ Prochaine ouverture dans {hours} heure(s).", "countdown", record_in_session=False)
        except Exception:
            pass


async def post_init(app):
    await init_db()
    app.job_queue.run_repeating(hourly_job, interval=60, first=10)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"ERROR: {context.error}", flush=True)


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
