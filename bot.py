
import os
import re
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

APP_VERSION = "FINAL_COMPLETE_V10"

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "").replace("@", "")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8080"))
TIMEZONE = os.getenv("TIMEZONE", "Europe/Paris")
TZ = ZoneInfo(TIMEZONE)

db_pool = None
URL_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/|discord\.gg/|bit\.ly/|tinyurl\.com/)", re.I)


# ---------------- DATABASE ----------------

async def init_db():
    global db_pool

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN manquant")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL manquant")
    if not WEBHOOK_URL:
        raise RuntimeError("WEBHOOK_URL manquant")

    print(f"STARTING {APP_VERSION}", flush=True)
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
        CREATE TABLE IF NOT EXISTS media_hashes(
            id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            file_unique_id TEXT NOT NULL,
            message_id BIGINT,
            created_at TIMESTAMP DEFAULT NOW()
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
        CREATE TABLE IF NOT EXISTS referral_links(
            user_id BIGINT PRIMARY KEY,
            invite_link TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """)
        await con.execute("""
        CREATE TABLE IF NOT EXISTS pending_joins(
            invited_user_id BIGINT PRIMARY KEY,
            referrer_id BIGINT NOT NULL,
            invite_link TEXT,
            joined_at TIMESTAMP DEFAULT NOW()
        )
        """)
        await con.execute("""
        CREATE TABLE IF NOT EXISTS referrals(
            referrer_id BIGINT NOT NULL,
            invited_user_id BIGINT NOT NULL,
            invite_link TEXT,
            joined_at TIMESTAMP DEFAULT NOW(),
            validated_at TIMESTAMP,
            rewarded BOOLEAN DEFAULT FALSE,
            PRIMARY KEY(referrer_id, invited_user_id)
        )
        """)
        await con.execute("""
        CREATE TABLE IF NOT EXISTS user_rewards(
            user_id BIGINT PRIMARY KEY,
            max_videos_sent INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW()
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
            "ad_message_id": "0",
        }

        for k, v in defaults.items():
            await con.execute(
                "INSERT INTO settings(key,value) VALUES($1,$2) ON CONFLICT(key) DO NOTHING",
                k, v,
            )

        tables = await con.fetch("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='public'
        ORDER BY table_name
        """)
        print("TABLES:", [r["table_name"] for r in tables], flush=True)


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


async def current_session_id():
    try:
        return int(await get_setting("current_session_id", "0"))
    except Exception:
        return 0


async def create_session():
    async with db_pool.acquire() as con:
        sid = await con.fetchval("INSERT INTO sessions(chat_id) VALUES($1) RETURNING id", GROUP_ID)
    await set_setting("current_session_id", sid)
    return sid


async def close_session():
    sid = await current_session_id()
    if sid:
        async with db_pool.acquire() as con:
            await con.execute("UPDATE sessions SET closed_at=NOW() WHERE id=$1", sid)
    await set_setting("current_session_id", "0")
    return sid


async def save_message(chat_id, message_id, user_id=None, is_bot=False, session_id=None):
    if session_id is None:
        session_id = await current_session_id()
    async with db_pool.acquire() as con:
        await con.execute("""
        INSERT INTO messages(chat_id,message_id,user_id,is_bot,session_id)
        VALUES($1,$2,$3,$4,$5)
        ON CONFLICT DO NOTHING
        """, chat_id, message_id, user_id, is_bot, session_id)


# ---------------- HELPERS ----------------

def is_admin(user_id):
    return user_id in ADMIN_IDS


async def is_group_admin(context, user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    try:
        member = await context.bot.get_chat_member(GROUP_ID, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


def led(value):
    return "🟢 ON" if value == "on" else "🔴 OFF"


def reward_count(valid_count):
    if valid_count >= 40:
        return 60
    if valid_count >= 30:
        return 50
    if valid_count >= 5:
        return 10
    if valid_count >= 1:
        return 1
    return 0


def bot_start_url():
    if BOT_USERNAME:
        return f"https://t.me/{BOT_USERNAME}?start=getlink"
    return "https://t.me/"


async def delete_message_safe(context, chat_id, message_id):
    try:
        await context.bot.delete_message(chat_id, message_id)
        return True
    except Exception as e:
        print(f"DELETE FAILED {message_id}: {e}", flush=True)
        return False


async def delete_last_system_message(context):
    async with db_pool.acquire() as con:
        row = await con.fetchrow("SELECT message_id FROM system_messages WHERE chat_id=$1", GROUP_ID)

    if row and row["message_id"]:
        await delete_message_safe(context, GROUP_ID, row["message_id"])

    async with db_pool.acquire() as con:
        await con.execute("DELETE FROM system_messages WHERE chat_id=$1", GROUP_ID)


async def send_system_message(context, text, kind, record_in_session=True, reply_markup=None):
    await delete_last_system_message(context)
    msg = await context.bot.send_message(GROUP_ID, text, reply_markup=reply_markup)

    async with db_pool.acquire() as con:
        await con.execute("""
        INSERT INTO system_messages(chat_id,message_id,kind,created_at)
        VALUES($1,$2,$3,NOW())
        ON CONFLICT(chat_id) DO UPDATE SET message_id=$2, kind=$3, created_at=NOW()
        """, GROUP_ID, msg.message_id, kind)

    if record_in_session:
        await save_message(GROUP_ID, msg.message_id, None, True)

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


# ---------------- ADMIN UI ----------------

async def main_keyboard():
    videos = await count_table("reward_videos")
    moderation = await get_setting("moderation", "off")
    anti_links = await get_setting("anti_links", "off")
    anti_photo = await get_setting("anti_photo_mention", "off")
    anti_repost = await get_setting("anti_repost", "off")
    auto_schedule = await get_setting("auto_schedule", "off")
    video_led = "✅" if videos >= 60 else "❌"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🛡️ Modération {led(moderation)}", callback_data="toggle:moderation")],
        [InlineKeyboardButton(f"🔗 Anti-liens {led(anti_links)}", callback_data="toggle:anti_links")],
        [InlineKeyboardButton(f"🖼️ Photo mention {led(anti_photo)}", callback_data="toggle:anti_photo_mention")],
        [InlineKeyboardButton(f"♻️ Anti-repost {led(anti_repost)}", callback_data="toggle:anti_repost")],
        [InlineKeyboardButton(f"⏰ Auto horaires {led(auto_schedule)}", callback_data="toggle:auto_schedule")],
        [
            InlineKeyboardButton("🟢 Ouvrir session", callback_data="open_group"),
            InlineKeyboardButton("🔴 Fermer + effacer", callback_data="close_group"),
        ],
        [InlineKeyboardButton("🚫 Mots interdits", callback_data="words_menu")],
        [InlineKeyboardButton(f"🎁 Vidéos {videos}/60 {video_led}", callback_data="videos_menu")],
        [InlineKeyboardButton(
            "📢 Publier publicité" if videos >= 60 else "📢 Publicité bloquée : 60 vidéos requises",
            callback_data="publish_ad" if videos >= 60 else "publish_ad_locked",
        )],
        [InlineKeyboardButton("📊 Stats parrainage", callback_data="ref_stats")],
        [InlineKeyboardButton("ℹ️ Info système", callback_data="info")],
    ])


async def words_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Ajouter un mot", callback_data="word_add"),
            InlineKeyboardButton("➖ Supprimer un mot", callback_data="word_delete"),
        ],
        [InlineKeyboardButton("📋 Voir les mots", callback_data="word_list")],
        [InlineKeyboardButton("⬅️ Retour", callback_data="info")],
    ])


def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Retour", callback_data="info")]])


async def panel_text(extra=""):
    async with db_pool.acquire() as con:
        videos = await con.fetchval("SELECT COUNT(*) FROM reward_videos")
        msg_count = await con.fetchval("SELECT COUNT(*) FROM messages")
        words = await con.fetchval("SELECT COUNT(*) FROM banned_words")
        valid_refs = await con.fetchval("SELECT COUNT(*) FROM referrals WHERE validated_at IS NOT NULL")
        links = await con.fetchval("SELECT COUNT(*) FROM referral_links")
        group_open = await con.fetchval("SELECT value FROM settings WHERE key='group_open'")
        moderation = await con.fetchval("SELECT value FROM settings WHERE key='moderation'")
        anti_links = await con.fetchval("SELECT value FROM settings WHERE key='anti_links'")
        anti_photo = await con.fetchval("SELECT value FROM settings WHERE key='anti_photo_mention'")
        anti_repost = await con.fetchval("SELECT value FROM settings WHERE key='anti_repost'")
        auto_schedule = await con.fetchval("SELECT value FROM settings WHERE key='auto_schedule'")

    sid = await current_session_id()
    text = (
        "⚙️ PANEL ADMIN\n\n"
        f"🧩 Version : {APP_VERSION}\n"
        "🗄️ PostgreSQL : ✅ branchée\n"
        f"👥 Groupe : {'✅' if GROUP_ID else '❌'} branché\n"
        f"🚪 Groupe ouvert : {led(group_open)}\n"
        f"🧾 Session active : {sid if sid else 'aucune'}\n\n"
        f"🛡️ Modération : {led(moderation)}\n"
        f"🔗 Anti-liens : {led(anti_links)}\n"
        f"🖼️ Photo mention : {led(anti_photo)}\n"
        f"♻️ Anti-repost : {led(anti_repost)}\n"
        f"⏰ Auto horaires : {led(auto_schedule)}\n\n"
        f"🎁 Vidéos : {videos}/60 {'✅' if videos >= 60 else '❌'}\n"
        f"💬 Messages session stockés : {msg_count}\n"
        f"🚫 Mots interdits : {words}\n"
        f"🔗 Liens privés : {links}\n"
        f"✅ Parrainages validés : {valid_refs}\n"
    )
    if extra:
        text += f"\n✅ Dernière action : {extra}"
    return text


async def safe_edit(query, text, reply_markup=None):
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            await query.answer("Déjà à jour ✅")
        else:
            raise


async def show_panel(query, extra=""):
    await safe_edit(query, await panel_text(extra), reply_markup=await main_keyboard())


# ---------------- START / CALLBACKS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    args = context.args or []

    if args and args[0] == "getlink":
        await send_referral_link_private(update, context)
        return

    if is_admin(user.id):
        await set_admin_state(user.id, None)
        await update.message.reply_text(await panel_text(), reply_markup=await main_keyboard())
    else:
        await update.message.reply_text("Clique sur le bouton dans le groupe pour recevoir ton lien privé.")


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not q.from_user or not is_admin(q.from_user.id):
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

    if data == "publish_ad_locked":
        await q.answer("Il faut d'abord uploader 60 vidéos.", show_alert=True)
        return

    if data == "publish_ad":
        ok = await publish_ad(context)
        await show_panel(q, "publicité publiée" if ok else "60 vidéos requises")
        return

    if data == "words_menu":
        await safe_edit(q, "🚫 MOTS INTERDITS\n\nChoisis une action :", reply_markup=await words_keyboard())
        return

    if data == "word_add":
        await set_admin_state(q.from_user.id, "adding_word")
        await safe_edit(q, "➕ Envoie maintenant le mot à interdire en privé.", reply_markup=back_keyboard())
        return

    if data == "word_delete":
        await set_admin_state(q.from_user.id, "deleting_word")
        await safe_edit(q, "➖ Envoie maintenant le mot à supprimer en privé.", reply_markup=back_keyboard())
        return

    if data == "word_list":
        async with db_pool.acquire() as con:
            rows = await con.fetch("SELECT word FROM banned_words ORDER BY word")
        words = "\n".join([f"• {r['word']}" for r in rows]) or "Aucun mot interdit."
        await safe_edit(q, f"📋 MOTS INTERDITS\n\n{words}", reply_markup=await words_keyboard())
        return

    if data == "videos_menu":
        videos = await count_table("reward_videos")
        await safe_edit(
            q,
            f"🎁 VIDÉOS\n\nStatut : {videos}/60 {'✅' if videos >= 60 else '❌'}\n\n"
            "Pour ajouter une vidéo : envoie une vidéo au bot en privé depuis le compte admin.",
            reply_markup=back_keyboard(),
        )
        return

    if data == "ref_stats":
        async with db_pool.acquire() as con:
            rows = await con.fetch("""
            SELECT referrer_id, COUNT(*) AS total
            FROM referrals
            WHERE validated_at IS NOT NULL
            GROUP BY referrer_id
            ORDER BY total DESC
            LIMIT 20
            """)
        if not rows:
            txt = "📊 STATS PARRAINAGE\n\nAucun parrainage validé."
        else:
            txt = "📊 STATS PARRAINAGE\n\n" + "\n".join([f"• {r['referrer_id']} : {r['total']}" for r in rows])
        await safe_edit(q, txt, reply_markup=back_keyboard())
        return


# ---------------- GROUP OPEN / CLOSE ----------------

async def open_group(context: ContextTypes.DEFAULT_TYPE):
    await delete_last_system_message(context)

    sid = await create_session()
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
    await send_system_message(context, "🟢 Groupe ouvert, vous pouvez envoyer tous vos médias.", "open", record_in_session=True)
    print(f"SESSION OPEN {sid}", flush=True)


async def close_group_and_clean(context: ContextTypes.DEFAULT_TYPE):
    sid = await current_session_id()
    await set_setting("group_open", "off")

    try:
        await context.bot.set_chat_permissions(GROUP_ID, ChatPermissions(can_send_messages=False))
    except Exception as e:
        print(f"SET PERMS CLOSE ERROR: {e}", flush=True)

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

    deleted = 0
    for r in rows:
        ok = await delete_message_safe(context, r["chat_id"], r["message_id"])
        if ok:
            deleted += 1
        await asyncio.sleep(0.04)

    await delete_last_system_message(context)

    async with db_pool.acquire() as con:
        if sid:
            await con.execute("DELETE FROM messages WHERE chat_id=$1 AND session_id=$2", GROUP_ID, sid)
        else:
            await con.execute("DELETE FROM messages WHERE chat_id=$1", GROUP_ID)

    await close_session()

    await send_system_message(
        context,
        "🔴 Groupe fermé, vous ne pouvez plus envoyer.",
        "closed",
        record_in_session=False,
    )
    return deleted


# ---------------- PUBLICITY / REFERRAL ----------------

async def publish_ad(context: ContextTypes.DEFAULT_TYPE):
    videos = await count_table("reward_videos")
    if videos < 60:
        return False

    old_id = int(await get_setting("ad_message_id", "0") or "0")
    if old_id:
        await delete_message_safe(context, GROUP_ID, old_id)

    text = (
        "🎁 Partagez le lien du groupe pour recevoir des vidéos.\n\n"
        "1 personne valide = 1 vidéo\n"
        "5 personnes valides = 10 vidéos\n"
        "30 personnes valides = 50 vidéos\n"
        "40 personnes valides = 60 vidéos\n\n"
        "Cliquez ci-dessous pour recevoir votre lien privé."
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Recevoir mon lien privé", url=bot_start_url())]
    ])

    msg = await context.bot.send_message(GROUP_ID, text, reply_markup=keyboard)
    await set_setting("ad_message_id", msg.message_id)
    return True


async def send_referral_link_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    async with db_pool.acquire() as con:
        row = await con.fetchrow("SELECT invite_link FROM referral_links WHERE user_id=$1", user.id)

    if row:
        invite_link = row["invite_link"]
    else:
        try:
            link = await context.bot.create_chat_invite_link(
                chat_id=GROUP_ID,
                name=f"ref_{user.id}",
                creates_join_request=False,
            )
            invite_link = link.invite_link
        except Exception as e:
            print(f"CREATE INVITE LINK ERROR: {e}", flush=True)
            await update.message.reply_text("❌ Impossible de créer ton lien. Le bot doit avoir le droit d'inviter des utilisateurs.")
            return

        async with db_pool.acquire() as con:
            await con.execute("""
            INSERT INTO referral_links(user_id,invite_link)
            VALUES($1,$2)
            ON CONFLICT(user_id) DO UPDATE SET invite_link=$2
            """, user.id, invite_link)

    async with db_pool.acquire() as con:
        valid = await con.fetchval(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id=$1 AND validated_at IS NOT NULL",
            user.id,
        )

    unlocked = reward_count(valid)

    await update.message.reply_text(
        "🎁 Ton lien privé :\n\n"
        f"{invite_link}\n\n"
        "Règles :\n"
        "1 personne valide = 1 vidéo\n"
        "5 personnes valides = 10 vidéos\n"
        "30 personnes valides = 50 vidéos\n"
        "40 personnes valides = 60 vidéos\n\n"
        f"✅ Personnes validées : {valid}\n"
        f"🎬 Vidéos débloquées : {unlocked}/60"
    )


async def validate_join_later(context: ContextTypes.DEFAULT_TYPE, invited_user_id: int):
    await asyncio.sleep(300)

    async with db_pool.acquire() as con:
        row = await con.fetchrow(
            "SELECT referrer_id, invite_link FROM pending_joins WHERE invited_user_id=$1",
            invited_user_id,
        )

    if not row:
        return

    try:
        member = await context.bot.get_chat_member(GROUP_ID, invited_user_id)
        if member.status in ("left", "kicked"):
            async with db_pool.acquire() as con:
                await con.execute("DELETE FROM pending_joins WHERE invited_user_id=$1", invited_user_id)
            return
    except Exception:
        return

    referrer_id = row["referrer_id"]
    invite_link = row["invite_link"]

    async with db_pool.acquire() as con:
        await con.execute("""
        INSERT INTO referrals(referrer_id,invited_user_id,invite_link,joined_at,validated_at)
        VALUES($1,$2,$3,NOW(),NOW())
        ON CONFLICT(referrer_id, invited_user_id)
        DO UPDATE SET validated_at=NOW()
        """, referrer_id, invited_user_id, invite_link)

        await con.execute("DELETE FROM pending_joins WHERE invited_user_id=$1", invited_user_id)

        valid = await con.fetchval(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id=$1 AND validated_at IS NOT NULL",
            referrer_id,
        )

        reward = reward_count(valid)

        old_reward = await con.fetchval(
            "SELECT COALESCE(max_videos_sent,0) FROM user_rewards WHERE user_id=$1",
            referrer_id,
        )
        old_reward = old_reward or 0

    if reward > old_reward:
        await send_reward_videos(context, referrer_id, old_reward + 1, reward)
        async with db_pool.acquire() as con:
            await con.execute("""
            INSERT INTO user_rewards(user_id,max_videos_sent,updated_at)
            VALUES($1,$2,NOW())
            ON CONFLICT(user_id) DO UPDATE SET max_videos_sent=$2, updated_at=NOW()
            """, referrer_id, reward)


async def send_reward_videos(context: ContextTypes.DEFAULT_TYPE, user_id: int, start_slot: int, end_slot: int):
    async with db_pool.acquire() as con:
        rows = await con.fetch("""
        SELECT slot, file_id FROM reward_videos
        WHERE slot BETWEEN $1 AND $2
        ORDER BY slot
        """, start_slot, end_slot)

    try:
        await context.bot.send_message(user_id, f"🎁 Tu as débloqué {end_slot} vidéo(s).")
        for r in rows:
            await context.bot.send_video(user_id, r["file_id"], caption=f"Vidéo {r['slot']}/60")
            await asyncio.sleep(0.2)
    except Forbidden:
        print(f"Cannot send videos to {user_id}: user did not start bot", flush=True)
    except Exception as e:
        print(f"SEND REWARD ERROR {user_id}: {e}", flush=True)


# ---------------- PRIVATE ADMIN ----------------

async def handle_private_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    if not user or not msg or not is_admin(user.id):
        return

    state = await get_admin_state(user.id)

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
        await set_admin_state(user.id, None)
        await msg.reply_text(f"✅ Mot interdit ajouté : {word}")
        return

    if state == "deleting_word":
        word = text.lower()
        async with db_pool.acquire() as con:
            await con.execute("DELETE FROM banned_words WHERE word=$1", word)
        await set_admin_state(user.id, None)
        await msg.reply_text(f"✅ Mot supprimé : {word}")
        return

    await msg.reply_text("Admin prêt. Envoie /start pour ouvrir le panel.")


# ---------------- GROUP MODERATION ----------------

def media_unique_id(msg):
    if msg.photo:
        return msg.photo[-1].file_unique_id
    if msg.video:
        return msg.video.file_unique_id
    if msg.animation:
        return msg.animation.file_unique_id
    if msg.document:
        return msg.document.file_unique_id
    return None


async def save_user_message_if_session(update: Update):
    if await get_setting("group_open", "off") != "on":
        return
    sid = await current_session_id()
    if not sid:
        return
    await save_message(
        update.effective_chat.id,
        update.message.message_id,
        update.effective_user.id if update.effective_user else None,
        False,
        sid,
    )


async def punish_ban(update, context, reason):
    user = update.effective_user
    if not user:
        return

    try:
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
    except Exception as e:
        print(f"BAN ERROR: {e}", flush=True)

    await delete_message_safe(context, update.effective_chat.id, update.message.message_id)

    msg = await context.bot.send_message(
        update.effective_chat.id,
        f"🚫 {user.mention_html()} a été banni pour {reason}. Ne faites pas la même erreur.",
        parse_mode="HTML",
    )
    await save_message(update.effective_chat.id, msg.message_id, None, True)


async def punish_word(update, context):
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

    await delete_message_safe(context, update.effective_chat.id, update.message.message_id)

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
        parse_mode="HTML",
    )
    await save_message(update.effective_chat.id, msg.message_id, None, True)


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.effective_chat.id != GROUP_ID:
        return

    # Supprime les messages Telegram automatiques d'entrée et de sortie.
    if update.message.new_chat_members or update.message.left_chat_member:
        await delete_message_safe(context, update.effective_chat.id, update.message.message_id)
        return

    await save_user_message_if_session(update)

    msg = update.message
    text = (msg.text or msg.caption or "").lower()

    user_id = update.effective_user.id if update.effective_user else 0
    admin_exempt = await is_group_admin(context, user_id)

    if await get_setting("moderation", "on") != "on":
        return

    if not admin_exempt and (msg.forward_origin or msg.forward_date):
        await punish_ban(update, context, "transfert de message")
        return

    if not admin_exempt and await get_setting("anti_links", "on") == "on" and URL_RE.search(text):
        await punish_ban(update, context, "envoi de lien")
        return

    if not admin_exempt and await get_setting("anti_photo_mention", "on") == "on":
        has_photo = bool(msg.photo)
        has_mention = bool(msg.caption_entities and any(e.type in ("mention", "text_mention") for e in msg.caption_entities))
        if has_photo and has_mention:
            await punish_ban(update, context, "photo avec identification")
            return

    if admin_exempt:
        return

    async with db_pool.acquire() as con:
        words = await con.fetch("SELECT word FROM banned_words")
    for r in words:
        word = r["word"].lower()
        if word and re.search(rf"\b{re.escape(word)}\b", text, re.I):
            await punish_word(update, context)
            return

    if await get_setting("anti_repost", "on") == "on":
        fid = media_unique_id(msg)
        if fid:
            async with db_pool.acquire() as con:
                old = await con.fetchrow("""
                SELECT id FROM media_hashes
                WHERE chat_id=$1 AND file_unique_id=$2 AND created_at > NOW() - INTERVAL '4 days'
                LIMIT 1
                """, GROUP_ID, fid)

                if old:
                    await delete_message_safe(context, GROUP_ID, msg.message_id)
                    warn = await context.bot.send_message(GROUP_ID, "♻️ C’est du vu et déjà vu.")
                    await save_message(GROUP_ID, warn.message_id, None, True)
                    return

                await con.execute("""
                INSERT INTO media_hashes(chat_id,file_unique_id,message_id)
                VALUES($1,$2,$3)
                """, GROUP_ID, fid, msg.message_id)


# ---------------- JOIN TRACKING ----------------

async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmu = update.chat_member
    if not cmu or cmu.chat.id != GROUP_ID:
        return

    old_status = cmu.old_chat_member.status
    new_status = cmu.new_chat_member.status
    user = cmu.new_chat_member.user

    if old_status in ("left", "kicked") and new_status in ("member", "restricted"):
        invite_link = cmu.invite_link.invite_link if cmu.invite_link else None
        if invite_link:
            async with db_pool.acquire() as con:
                ref = await con.fetchrow("SELECT user_id FROM referral_links WHERE invite_link=$1", invite_link)

            if ref and ref["user_id"] != user.id:
                async with db_pool.acquire() as con:
                    await con.execute("""
                    INSERT INTO pending_joins(invited_user_id,referrer_id,invite_link,joined_at)
                    VALUES($1,$2,$3,NOW())
                    ON CONFLICT(invited_user_id) DO UPDATE SET referrer_id=$2, invite_link=$3, joined_at=NOW()
                    """, user.id, ref["user_id"], invite_link)

                context.application.create_task(validate_join_later(context, user.id))

    if new_status in ("left", "kicked"):
        async with db_pool.acquire() as con:
            await con.execute("DELETE FROM pending_joins WHERE invited_user_id=$1", user.id)


# ---------------- SCHEDULE ----------------

def is_open_window(now: datetime, open_hour: int, close_hour: int) -> bool:
    if open_hour < close_hour:
        return open_hour <= now.hour < close_hour
    return now.hour >= open_hour or now.hour < close_hour


async def hourly_job(context: ContextTypes.DEFAULT_TYPE):
    if await get_setting("auto_schedule", "on") != "on":
        return

    now = datetime.now(TZ)
    open_hour = int(await get_setting("open_hour", "23"))
    close_hour = int(await get_setting("close_hour", "1"))
    group_open = await get_setting("group_open", "off")
    should_be_open = is_open_window(now, open_hour, close_hour)

    if should_be_open and group_open != "on":
        await open_group(context)
        return

    if not should_be_open and group_open == "on":
        await close_group_and_clean(context)
        return

    if now.minute == 0 and not should_be_open:
        target = now.replace(hour=open_hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        hours = int((target - now).total_seconds() // 3600)
        try:
            await send_system_message(
                context,
                f"⏰ Prochaine ouverture dans {hours} heure(s).",
                "countdown",
                record_in_session=False,
            )
        except Exception as e:
            print(f"COUNTDOWN ERROR: {e}", flush=True)


async def post_init(app):
    await init_db()
    app.job_queue.run_repeating(hourly_job, interval=60, first=10)


async def error_handler(update, context):
    print(f"ERROR: {context.error}", flush=True)


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE, handle_private_admin))
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & ~filters.COMMAND, handle_group_message))
    app.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.CHAT_MEMBER))
    app.add_error_handler(error_handler)

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
