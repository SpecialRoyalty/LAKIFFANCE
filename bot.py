
# Horaires dynamiques V14
def get_schedule_for_day(now):
    wd = now.weekday()

    # samedi
    if wd == 5:
        return {"open_hour": 23, "open_minute": 0, "close_hour": 1, "close_minute": 0}

    # dimanche
    if wd == 6:
        return {"open_hour": 22, "open_minute": 30, "close_hour": 0, "close_minute": 15}

    # semaine
    return {"open_hour": 22, "open_minute": 0, "close_hour": 0, "close_minute": 0}


import os
import re
import asyncio
import hashlib
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

APP_VERSION = "FINAL_COMPLETE_V22"

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "").replace("@", "")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
TRUSTED_IDS = [int(x.strip()) for x in os.getenv("TRUSTED_IDS", "").split(",") if x.strip()]
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
            hash TEXT PRIMARY KEY,
            chat_id BIGINT,
            user_id BIGINT,
            message_id BIGINT,
            media_type TEXT,
            used_for_participation BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
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

        await con.execute("""
        CREATE TABLE IF NOT EXISTS trusted_actions(
            id SERIAL PRIMARY KEY,
            session_id INTEGER,
            trusted_id BIGINT NOT NULL,
            action TEXT NOT NULL,
            target_user_id BIGINT,
            target_message_id BIGINT,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS trusted_strikes(
            session_id INTEGER NOT NULL,
            target_user_id BIGINT NOT NULL,
            strikes INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY(session_id, target_user_id)
        )
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS danger_scores(
            user_id BIGINT PRIMARY KEY,
            score INTEGER DEFAULT 0,
            reason TEXT,
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """)
        await con.execute("""
        CREATE TABLE IF NOT EXISTS banned_hashes(
            hash TEXT PRIMARY KEY,
            media_type TEXT,
            reason TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """)
        await con.execute("""
        CREATE TABLE IF NOT EXISTS media_fingerprints(
            hash TEXT PRIMARY KEY,
            chat_id BIGINT,
            user_id BIGINT,
            message_id BIGINT,
            media_type TEXT,
            used_for_participation BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """)
        await con.execute("""
        CREATE TABLE IF NOT EXISTS participants(
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TIMESTAMP DEFAULT NOW(),
            has_participated BOOLEAN DEFAULT FALSE,
            participation_hash TEXT,
            participated_at TIMESTAMP,
            warn_count INTEGER DEFAULT 0,
            last_warned_at TIMESTAMP
        )
        """)
        await con.execute("""
        CREATE TABLE IF NOT EXISTS referrer_abuse(
            referrer_id BIGINT PRIMARY KEY,
            failed_joins INTEGER DEFAULT 0,
            blacklisted BOOLEAN DEFAULT FALSE,
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """)
        await con.execute("""
        CREATE TABLE IF NOT EXISTS reward_links(
            level INTEGER PRIMARY KEY,
            url TEXT,
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """)

        defaults = {
            "moderation": "on",
            "anti_links": "on",
            "anti_photo_mention": "on",
            "anti_repost": "on",
            "auto_schedule": "on",
            "silent_sanctions": "off",
            "raid_mode": "off",
            "participation": "off",
            "kick_non_participants": "off",
            "rules_auto": "off",
            "rules_text": "📌 Règles du groupe : respect, pas de lien, pas de repost, participez avec un média nouveau.",
            "rules_message_id": "0",
            "last_countdown_key": "",
            "ban_report_count": "0",
            "non_participants_kicked_total": "0",
            "nonparticipant_kicked_today": "0",
            "last_nonparticipant_kick_date": "",
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

        for level in (1, 10, 50, 60):
            await con.execute("INSERT INTO reward_links(level,url) VALUES($1,'') ON CONFLICT(level) DO NOTHING", level)
        # SCHEMA REPAIR V22
        # Corrige automatiquement les DB Railway ayant gardé d'anciens schémas.
        await con.execute("ALTER TABLE IF EXISTS media_hashes ADD COLUMN IF NOT EXISTS hash TEXT")
        await con.execute("ALTER TABLE IF EXISTS media_hashes ADD COLUMN IF NOT EXISTS chat_id BIGINT")
        await con.execute("ALTER TABLE IF EXISTS media_hashes ADD COLUMN IF NOT EXISTS user_id BIGINT")
        await con.execute("ALTER TABLE IF EXISTS media_hashes ADD COLUMN IF NOT EXISTS message_id BIGINT")
        await con.execute("ALTER TABLE IF EXISTS media_hashes ADD COLUMN IF NOT EXISTS media_type TEXT")
        await con.execute("ALTER TABLE IF EXISTS media_hashes ADD COLUMN IF NOT EXISTS used_for_participation BOOLEAN DEFAULT FALSE")
        await con.execute("ALTER TABLE IF EXISTS media_hashes ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()")

        await con.execute("ALTER TABLE IF EXISTS banned_hashes ADD COLUMN IF NOT EXISTS hash TEXT")
        await con.execute("ALTER TABLE IF EXISTS banned_hashes ADD COLUMN IF NOT EXISTS media_type TEXT")
        await con.execute("ALTER TABLE IF EXISTS banned_hashes ADD COLUMN IF NOT EXISTS reason TEXT")
        await con.execute("ALTER TABLE IF EXISTS banned_hashes ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()")

        # Nettoyage des lignes inutilisables avant création des index uniques.
        await con.execute("DELETE FROM media_hashes WHERE hash IS NULL OR hash = ''")
        await con.execute("DELETE FROM banned_hashes WHERE hash IS NULL OR hash = ''")

        # Suppression doublons si ancienne table avait plusieurs fois le même hash.
        await con.execute("""
        DELETE FROM media_hashes a
        USING media_hashes b
        WHERE a.ctid < b.ctid AND a.hash = b.hash
        """)
        await con.execute("""
        DELETE FROM banned_hashes a
        USING banned_hashes b
        WHERE a.ctid < b.ctid AND a.hash = b.hash
        """)

        # Contraintes uniques requises pour ON CONFLICT(hash).
        await con.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'media_hashes_hash_unique'
            ) THEN
                ALTER TABLE media_hashes ADD CONSTRAINT media_hashes_hash_unique UNIQUE(hash);
            END IF;
        END $$;
        """)
        await con.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'banned_hashes_hash_unique'
            ) THEN
                ALTER TABLE banned_hashes ADD CONSTRAINT banned_hashes_hash_unique UNIQUE(hash);
            END IF;
        END $$;
        """)

        # Contraintes supplémentaires pour les autres ON CONFLICT.
        await con.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'settings_key_unique'
            ) THEN
                ALTER TABLE settings ADD CONSTRAINT settings_key_unique UNIQUE(key);
            END IF;
        END $$;
        """)
        await con.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'reward_links_level_unique'
            ) THEN
                ALTER TABLE reward_links ADD CONSTRAINT reward_links_level_unique UNIQUE(level);
            END IF;
        END $$;
        """)
        await con.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'referral_links_user_unique'
            ) THEN
                ALTER TABLE referral_links ADD CONSTRAINT referral_links_user_unique UNIQUE(user_id);
            END IF;
        END $$;
        """)
        await con.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'user_rewards_user_unique'
            ) THEN
                ALTER TABLE user_rewards ADD CONSTRAINT user_rewards_user_unique UNIQUE(user_id);
            END IF;
        END $$;
        """)

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


def is_trusted_id(user_id):
    return user_id in ADMIN_IDS or user_id in TRUSTED_IDS


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


async def is_silent():
    return await get_setting("silent_sanctions", "off") == "on"

async def add_danger(user_id, points, reason):
    async with db_pool.acquire() as con:
        await con.execute("""
        INSERT INTO danger_scores(user_id,score,reason,updated_at)
        VALUES($1,$2,$3,NOW())
        ON CONFLICT(user_id) DO UPDATE SET score=danger_scores.score+$2, reason=$3, updated_at=NOW()
        """, user_id, points, reason)

async def increment_ban_count():
    current = int(await get_setting("ban_report_count", "0") or "0")
    await set_setting("ban_report_count", current + 1)

def message_has_media(msg):
    return bool(msg.photo or msg.video or msg.animation or msg.document)

def message_is_photo_or_video(msg):
    return bool(msg.photo or msg.video)

def media_type(msg):
    if msg.photo: return "photo"
    if msg.video: return "video"
    if msg.animation: return "animation"
    if msg.document: return "document"
    return "unknown"

async def media_hash_from_message(context, msg):
    file_id = None
    if msg.photo:
        file_id = msg.photo[-1].file_id
    elif msg.video:
        file_id = msg.video.file_id
    elif msg.animation:
        file_id = msg.animation.file_id
    elif msg.document:
        file_id = msg.document.file_id
    if not file_id:
        return None
    tg_file = await context.bot.get_file(file_id)
    data = await tg_file.download_as_bytearray()
    return hashlib.sha256(bytes(data)).hexdigest()

async def reward_links_ready():
    async with db_pool.acquire() as con:
        c = await con.fetchval("SELECT COUNT(*) FROM reward_links WHERE level IN (1,10,50,60) AND COALESCE(url,'') <> ''")
    return c == 4

async def upsert_participant(user):
    async with db_pool.acquire() as con:
        await con.execute("""
        INSERT INTO participants(user_id,username,first_name,joined_at)
        VALUES($1,$2,$3,NOW())
        ON CONFLICT(user_id) DO UPDATE SET username=$2, first_name=$3
        """, user.id, user.username, user.first_name)

async def has_participated(user_id):
    async with db_pool.acquire() as con:
        row = await con.fetchrow("SELECT has_participated FROM participants WHERE user_id=$1", user_id)
    return bool(row and row['has_participated'])

async def mark_participated(user_id, media_hash):
    async with db_pool.acquire() as con:
        await con.execute("""
        INSERT INTO participants(user_id,has_participated,participation_hash,participated_at)
        VALUES($1,TRUE,$2,NOW())
        ON CONFLICT(user_id) DO UPDATE SET has_participated=TRUE, participation_hash=$2, participated_at=NOW()
        """, user_id, media_hash)

async def delete_later(context, chat_id, message_id, seconds=45):
    await asyncio.sleep(seconds)
    await delete_message_safe(context, chat_id, message_id)

async def send_temp_message(context, chat_id, text, seconds=45):
    msg = await context.bot.send_message(chat_id, text)
    context.application.create_task(delete_later(context, chat_id, msg.message_id, seconds))
    return msg


async def delete_message_safe(context, chat_id, message_id):
    try:
        await context.bot.delete_message(chat_id, message_id)
        try:
            async with db_pool.acquire() as con:
                await con.execute(
                    "DELETE FROM messages WHERE chat_id=$1 AND message_id=$2",
                    chat_id,
                    message_id,
                )
        except Exception as db_e:
            print(f"DELETE SQL CLEANUP FAILED {message_id}: {db_e}", flush=True)
        return True

    except BadRequest as e:
        err = str(e).lower()
        if (
            "message to delete not found" in err
            or "message can't be deleted" in err
            or "message identifier is not specified" in err
            or "message not found" in err
            or "not found" in err
        ):
            try:
                async with db_pool.acquire() as con:
                    await con.execute(
                        "DELETE FROM messages WHERE chat_id=$1 AND message_id=$2",
                        chat_id,
                        message_id,
                    )
            except Exception as db_e:
                print(f"DELETE SQL CLEANUP FAILED {message_id}: {db_e}", flush=True)
            print(f"DELETE SKIPPED/CLEANED {message_id}: {e}", flush=True)
            return False

        print(f"DELETE FAILED {message_id}: {e}", flush=True)
        return False

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
    moderation = await get_setting("moderation", "off")
    anti_links = await get_setting("anti_links", "off")
    anti_photo = await get_setting("anti_photo_mention", "off")
    anti_repost = await get_setting("anti_repost", "off")
    auto_schedule = await get_setting("auto_schedule", "off")
    silent = await get_setting("silent_sanctions", "off")
    raid = await get_setting("raid_mode", "off")
    participation = await get_setting("participation", "off")
    kick_np = await get_setting("kick_non_participants", "off")
    rules_auto = await get_setting("rules_auto", "off")

    links_ok = await reward_links_ready()
    pub_label = "📢 Publier publicité" if links_ok else "📢 Publicité bloquée : liens manquants"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🛡️ Modération {led(moderation)}", callback_data="toggle:moderation")],
        [InlineKeyboardButton(f"🔗 Anti-liens {led(anti_links)}", callback_data="toggle:anti_links")],
        [InlineKeyboardButton(f"🖼️ Photo mention {led(anti_photo)}", callback_data="toggle:anti_photo_mention")],
        [InlineKeyboardButton(f"♻️ Anti-repost {led(anti_repost)}", callback_data="toggle:anti_repost")],
        [InlineKeyboardButton(f"⏰ Auto horaires {led(auto_schedule)}", callback_data="toggle:auto_schedule")],
        [InlineKeyboardButton(f"👁️ Sanctions silencieuses {led(silent)}", callback_data="toggle_silent")],
        [InlineKeyboardButton(f"🚨 Mode RAID {led(raid)}", callback_data="toggle_raid")],
        [InlineKeyboardButton(f"🎭 Participation {led(participation)}", callback_data="toggle:participation")],
        [InlineKeyboardButton(f"🥾 Kick non-participants {led(kick_np)}", callback_data="toggle:kick_non_participants")],
        [InlineKeyboardButton(f"📌 Règles auto {led(rules_auto)}", callback_data="toggle:rules_auto")],
        [
            InlineKeyboardButton("🟢 Ouvrir session", callback_data="open_group"),
            InlineKeyboardButton("🔴 Fermer + effacer", callback_data="close_group"),
        ],
        [InlineKeyboardButton("🚫 Mots interdits", callback_data="words_menu")],
        [InlineKeyboardButton("📌 Modifier règles", callback_data="rules_set")],
        [InlineKeyboardButton("📣 Broadcast groupe", callback_data="broadcast_set")],
        [InlineKeyboardButton("🚫 Ban hash", callback_data="ban_hash_set")],
        [InlineKeyboardButton("🔗 Liens récompenses", callback_data="reward_links_menu")],
        [InlineKeyboardButton(pub_label, callback_data="publish_ad" if links_ok else "publish_ad_locked")],
        [InlineKeyboardButton("📊 Stats parrainage", callback_data="ref_stats")],
        [InlineKeyboardButton("📣 Relancer non-participants", callback_data="warn_non_participants")],
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


async def reward_links_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Modifier lien 1 vidéo", callback_data="set_reward_link:1")],
        [InlineKeyboardButton("Modifier lien 10 vidéos", callback_data="set_reward_link:10")],
        [InlineKeyboardButton("Modifier lien 50 vidéos", callback_data="set_reward_link:50")],
        [InlineKeyboardButton("Modifier lien 60 vidéos", callback_data="set_reward_link:60")],
        [InlineKeyboardButton("📋 Voir liens", callback_data="show_reward_links")],
        [InlineKeyboardButton("⬅️ Retour", callback_data="info")],
    ])


def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Retour", callback_data="info")]])


async def panel_text(extra=""):
    links_ready = await reward_links_ready() if "reward_links_ready" in globals() else False

    async with db_pool.acquire() as con:
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
        silent = await con.fetchval("SELECT value FROM settings WHERE key='silent_sanctions'") if await table_has_setting("silent_sanctions") else "off"
        raid = await con.fetchval("SELECT value FROM settings WHERE key='raid_mode'") if await table_has_setting("raid_mode") else "off"
        participation = await con.fetchval("SELECT value FROM settings WHERE key='participation'") if await table_has_setting("participation") else "off"
        kick_np = await con.fetchval("SELECT value FROM settings WHERE key='kick_non_participants'") if await table_has_setting("kick_non_participants") else "off"
        kicked_total = await con.fetchval("SELECT value FROM settings WHERE key='non_participants_kicked_total'") if await table_has_setting("non_participants_kicked_total") else "0"
        rules_auto = await con.fetchval("SELECT value FROM settings WHERE key='rules_auto'") if await table_has_setting("rules_auto") else "off"

        non_participants = 0
        banned_hashes = 0
        try:
            non_participants = await con.fetchval("SELECT COUNT(*) FROM participants WHERE has_participated=FALSE")
        except Exception:
            pass
        try:
            banned_hashes = await con.fetchval("SELECT COUNT(*) FROM banned_hashes")
        except Exception:
            pass

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
        f"⏰ Auto horaires : {led(auto_schedule)}\n"
        f"👁️ Sanctions silencieuses : {led(silent)}\n"
        f"🚨 Mode RAID : {led(raid)}\n"
        f"🎭 Participation : {led(participation)}\n"
        f"🥾 Kick non-participants : {led(kick_np)}\n"
        f"🥾 Déjà supprimés non-participation : {kicked_total}\n"
        f"📌 Règles auto : {led(rules_auto)}\n\n"
        f"🔗 Liens récompenses : {'✅ complets' if links_ready else '❌ incomplets'}\n"
        f"💬 Messages session stockés : {msg_count}\n"
        f"🚫 Mots interdits : {words}\n"
        f"🚫 Hash bannis : {banned_hashes}\n"
        f"🎭 Non-participants : {non_participants}\n"
        f"🔗 Liens privés : {links}\n"
        f"✅ Parrainages validés : {valid_refs}\n"
    )
    if extra:
        text += f"\n✅ Dernière action : {extra}"
    return text


async def table_has_setting(key):
    try:
        value = await get_setting(key, None)
        return value is not None
    except Exception:
        return False


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



# =========================
# TRUSTED MODERATION
# =========================

async def get_session_for_trusted():
    sid = await current_session_id()
    return sid if sid else 0


async def trusted_action_count(session_id: int, trusted_id: int, action: str) -> int:
    async with db_pool.acquire() as con:
        return await con.fetchval(
            "SELECT COUNT(*) FROM trusted_actions WHERE session_id=$1 AND trusted_id=$2 AND action=$3",
            session_id, trusted_id, action
        )


async def log_trusted_action(session_id: int, trusted_id: int, action: str, target_user_id: int, target_message_id: int):
    async with db_pool.acquire() as con:
        await con.execute("""
        INSERT INTO trusted_actions(session_id,trusted_id,action,target_user_id,target_message_id)
        VALUES($1,$2,$3,$4,$5)
        """, session_id, trusted_id, action, target_user_id, target_message_id)


async def delete_user_session_messages(context: ContextTypes.DEFAULT_TYPE, target_user_id: int):
    sid = await current_session_id()
    if not sid:
        return 0

    async with db_pool.acquire() as con:
        rows = await con.fetch("""
        SELECT chat_id, message_id
        FROM messages
        WHERE chat_id=$1 AND session_id=$2 AND user_id=$3
        ORDER BY created_at ASC
        """, GROUP_ID, sid, target_user_id)

    deleted = 0
    for r in rows:
        if await delete_message_safe(context, r["chat_id"], r["message_id"]):
            deleted += 1
        await asyncio.sleep(0.03)
    return deleted


async def ban_hashes_from_user_session(target_user_id: int):
    sid = await current_session_id()
    async with db_pool.acquire() as con:
        if sid:
            rows = await con.fetch("""
            SELECT hash, media_type
            FROM media_hashes
            WHERE user_id=$1
              AND hash IS NOT NULL
              AND created_at > NOW() - INTERVAL '10 days'
            """, target_user_id)
        else:
            rows = await con.fetch("""
            SELECT hash, media_type
            FROM media_hashes
            WHERE user_id=$1
              AND hash IS NOT NULL
              AND created_at > NOW() - INTERVAL '10 days'
            """, target_user_id)

        for r in rows:
            await con.execute("""
            INSERT INTO banned_hashes(hash,media_type,reason)
            VALUES($1,$2,$3)
            ON CONFLICT(hash) DO UPDATE SET reason=$3
            """, r["hash"], r["media_type"], "trusted ban user media")

    return len(rows)


async def trusted_supprime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    actor = update.effective_user
    if not msg or not actor:
        return

    if not is_trusted_id(actor.id):
        await delete_message_safe(context, msg.chat_id, msg.message_id)
        return

    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await delete_message_safe(context, msg.chat_id, msg.message_id)
        return

    target = msg.reply_to_message.from_user

    if await is_group_admin(context, target.id) or target.id in TRUSTED_IDS:
        await delete_message_safe(context, msg.chat_id, msg.message_id)
        if not await is_silent():
            warn = await context.bot.send_message(GROUP_ID, "⛔ Action refusée : impossible de cibler un admin, owner ou trusted.")
            await save_message(GROUP_ID, warn.message_id, None, True)
        return

    sid = await get_session_for_trusted()
    used = await trusted_action_count(sid, actor.id, "supprime")
    if used >= 20:
        await delete_message_safe(context, msg.chat_id, msg.message_id)
        if not await is_silent():
            warn = await context.bot.send_message(GROUP_ID, "⛔ Limite atteinte : 20 /supprime par session.")
            await save_message(GROUP_ID, warn.message_id, None, True)
        return

    await delete_message_safe(context, msg.chat_id, msg.reply_to_message.message_id)
    await delete_message_safe(context, msg.chat_id, msg.message_id)
    await log_trusted_action(sid, actor.id, "supprime", target.id, msg.reply_to_message.message_id)

    async with db_pool.acquire() as con:
        row = await con.fetchrow(
            "SELECT strikes FROM trusted_strikes WHERE session_id=$1 AND target_user_id=$2",
            sid, target.id
        )
        strikes = (row["strikes"] if row else 0) + 1
        await con.execute("""
        INSERT INTO trusted_strikes(session_id,target_user_id,strikes,updated_at)
        VALUES($1,$2,$3,NOW())
        ON CONFLICT(session_id,target_user_id)
        DO UPDATE SET strikes=$3, updated_at=NOW()
        """, sid, target.id, strikes)

    if strikes >= 2:
        until = datetime.now(TZ) + timedelta(days=7)
        try:
            await context.bot.restrict_chat_member(GROUP_ID, target.id, ChatPermissions(can_send_messages=False), until_date=until)
        except Exception as e:
            print(f"TRUSTED MUTE ERROR: {e}", flush=True)

        deleted = await delete_user_session_messages(context, target.id)
        await add_danger(target.id, 5, "trusted strikes")
        if not await is_silent():
            note = await context.bot.send_message(
                GROUP_ID,
                f"🔇 Utilisateur sanctionné : mute 7 jours. {deleted} message(s) supprimé(s)."
            )
            await save_message(GROUP_ID, note.message_id, None, True)


async def trusted_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    actor = update.effective_user
    if not msg or not actor:
        return

    if not is_trusted_id(actor.id):
        await delete_message_safe(context, msg.chat_id, msg.message_id)
        return

    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await delete_message_safe(context, msg.chat_id, msg.message_id)
        return

    target = msg.reply_to_message.from_user

    if await is_group_admin(context, target.id) or target.id in TRUSTED_IDS:
        await delete_message_safe(context, msg.chat_id, msg.message_id)
        if not await is_silent():
            warn = await context.bot.send_message(GROUP_ID, "⛔ Action refusée : impossible de cibler un admin, owner ou trusted.")
            await save_message(GROUP_ID, warn.message_id, None, True)
        return

    sid = await get_session_for_trusted()
    used = await trusted_action_count(sid, actor.id, "ban")
    if used >= 20:
        await delete_message_safe(context, msg.chat_id, msg.message_id)
        if not await is_silent():
            warn = await context.bot.send_message(GROUP_ID, "⛔ Limite atteinte : 20 /ban par session.")
            await save_message(GROUP_ID, warn.message_id, None, True)
        return

    await log_trusted_action(sid, actor.id, "ban", target.id, msg.reply_to_message.message_id)

    banned_hashes = await ban_hashes_from_user_session(target.id)
    deleted = await delete_user_session_messages(context, target.id)

    try:
        await context.bot.ban_chat_member(GROUP_ID, target.id)
    except Exception as e:
        print(f"TRUSTED BAN ERROR: {e}", flush=True)

    await delete_message_safe(context, msg.chat_id, msg.reply_to_message.message_id)
    await delete_message_safe(context, msg.chat_id, msg.message_id)
    await add_danger(target.id, 20, "trusted ban")
    await increment_ban_count()

    if not await is_silent():
        note = await context.bot.send_message(
            GROUP_ID,
            f"🚫 Ban trusted appliqué. {deleted} message(s) supprimé(s), {banned_hashes} hash média interdit(s)."
        )
        await save_message(GROUP_ID, note.message_id, None, True)

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


    if data == "toggle_raid":
        current = await get_setting("raid_mode", "off")
        new = "off" if current == "on" else "on"
        await set_setting("raid_mode", new)
        await show_panel(q, f"mode RAID = {new.upper()}")
        return

    if data == "rules_set":
        await set_admin_state(q.from_user.id, "setting_rules")
        await safe_edit(q, "📌 Envoie maintenant le texte des règles.", reply_markup=back_keyboard())
        return

    if data == "broadcast_set":
        await set_admin_state(q.from_user.id, "broadcast_group")
        await safe_edit(q, "📣 Envoie maintenant le message à publier dans le groupe.", reply_markup=back_keyboard())
        return

    if data == "ban_hash_set":
        await set_admin_state(q.from_user.id, "ban_hash")
        await safe_edit(q, "🚫 Envoie maintenant la photo ou vidéo à bannir par hash.", reply_markup=back_keyboard())
        return

    if data == "reward_links_menu":
        await safe_edit(q, "🔗 LIENS RÉCOMPENSES\n\nChoisis le lien à modifier.", reply_markup=await reward_links_keyboard())
        return

    if data.startswith("set_reward_link:"):
        level = data.split(":", 1)[1]
        await set_admin_state(q.from_user.id, f"set_reward_link:{level}")
        await safe_edit(q, f"🔗 Envoie maintenant le lien pour le palier {level}.", reply_markup=back_keyboard())
        return

    if data == "show_reward_links":
        async with db_pool.acquire() as con:
            rows = await con.fetch("SELECT level,url FROM reward_links ORDER BY level")
        txt = "🔗 LIENS RÉCOMPENSES\n\n" + "\n".join([f"{r['level']} : {r['url'] or '❌ vide'}" for r in rows])
        await safe_edit(q, txt, reply_markup=await reward_links_keyboard())
        return

    if data == "warn_non_participants":
        count = await warn_non_participants(context)
        await show_panel(q, f"{count} non-participant(s) averti(s)")
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




async def send_trusted_session_report(context: ContextTypes.DEFAULT_TYPE, session_id: int, deleted_count: int):
    if not session_id:
        return

    async with db_pool.acquire() as con:
        rows = await con.fetch("""
        SELECT trusted_id, action, COUNT(*) AS total
        FROM trusted_actions
        WHERE session_id=$1
        GROUP BY trusted_id, action
        ORDER BY trusted_id, action
        """, session_id)

        strikes = await con.fetch("""
        SELECT target_user_id, strikes
        FROM trusted_strikes
        WHERE session_id=$1
        ORDER BY strikes DESC
        LIMIT 20
        """, session_id)

    by_user = {}
    for r in rows:
        tid = r["trusted_id"]
        by_user.setdefault(tid, {"supprime": 0, "ban": 0})
        by_user[tid][r["action"]] = r["total"]

    lines = [
        f"📊 Bilan modération trusted — Session #{session_id}",
        "",
        f"🧹 Messages supprimés à la fermeture : {deleted_count}",
        "",
    ]

    if not by_user:
        lines.append("Aucune action trusted pendant cette session.")
    else:
        for tid, data in by_user.items():
            sup = data.get("supprime", 0)
            ban = data.get("ban", 0)
            sup_limit = " ⚠️ limite atteinte" if sup >= 20 else ""
            ban_limit = " ⚠️ limite atteinte" if ban >= 20 else ""
            lines.append(f"👤 Trusted ID {tid}")
            lines.append(f"• /supprime : {sup}{sup_limit}")
            lines.append(f"• /ban : {ban}{ban_limit}")
            lines.append("")

    if strikes:
        lines.append("🎯 Utilisateurs avec strikes :")
        for s in strikes:
            lines.append(f"• {s['target_user_id']} : {s['strikes']} strike(s)")

    text = "\n".join(lines)

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text)
        except Exception as e:
            print(f"TRUSTED REPORT SEND ERROR admin={admin_id}: {e}", flush=True)

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

    await send_trusted_session_report(context, sid, deleted)
    return deleted


# ---------------- PUBLICITY / REFERRAL ----------------

async def publish_ad(context: ContextTypes.DEFAULT_TYPE):
    if not await reward_links_ready():
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
        abuse = await con.fetchrow("SELECT blacklisted FROM referrer_abuse WHERE referrer_id=$1", user.id)
        if abuse and abuse["blacklisted"]:
            await update.message.reply_text("❌ Ton accès au parrainage est bloqué.")
            return
        row = await con.fetchrow("SELECT invite_link FROM referral_links WHERE user_id=$1", user.id)

    if row:
        invite_link = row["invite_link"]
    else:
        try:
            link = await context.bot.create_chat_invite_link(chat_id=GROUP_ID, name=f"ref_{user.id}", creates_join_request=False)
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
        valid = await con.fetchval("SELECT COUNT(*) FROM referrals WHERE referrer_id=$1 AND validated_at IS NOT NULL", user.id)
    level = reward_count(valid)
    reward_url = ""
    if level:
        async with db_pool.acquire() as con:
            row = await con.fetchrow("SELECT url FROM reward_links WHERE level=$1", level)
            reward_url = row["url"] if row and row["url"] else ""

    txt = (
        "🎁 Ton lien privé :\n\n"
        f"{invite_link}\n\n"
        "Règles :\n"
        "1 personne valide = 1 vidéo\n"
        "5 personnes valides = 10 vidéos\n"
        "30 personnes valides = 50 vidéos\n"
        "40 personnes valides = 60 vidéos\n\n"
        f"✅ Personnes validées : {valid}\n"
        f"🎬 Vidéos débloquées : {level}/60"
    )
    if reward_url:
        txt += f"\n\n🔗 Ton lien débloqué :\n{reward_url}"
    await update.message.reply_text(txt)


async def validate_join_later(context: ContextTypes.DEFAULT_TYPE, invited_user_id: int):
    await asyncio.sleep(300)
    async with db_pool.acquire() as con:
        row = await con.fetchrow("SELECT referrer_id, invite_link FROM pending_joins WHERE invited_user_id=$1", invited_user_id)
    if not row:
        return
    referrer_id = row["referrer_id"]
    try:
        member = await context.bot.get_chat_member(GROUP_ID, invited_user_id)
        if member.status in ("left", "kicked"):
            async with db_pool.acquire() as con:
                await con.execute("DELETE FROM pending_joins WHERE invited_user_id=$1", invited_user_id)
                await con.execute("""
                INSERT INTO referrer_abuse(referrer_id,failed_joins,updated_at)
                VALUES($1,1,NOW())
                ON CONFLICT(referrer_id) DO UPDATE SET failed_joins=referrer_abuse.failed_joins+1, updated_at=NOW()
                """, referrer_id)
                failed = await con.fetchval("SELECT failed_joins FROM referrer_abuse WHERE referrer_id=$1", referrer_id)
                if failed and failed >= 5:
                    await con.execute("UPDATE referrer_abuse SET blacklisted=TRUE, updated_at=NOW() WHERE referrer_id=$1", referrer_id)
            return
    except Exception:
        return

    invite_link = row["invite_link"]
    async with db_pool.acquire() as con:
        await con.execute("""
        INSERT INTO referrals(referrer_id,invited_user_id,invite_link,joined_at,validated_at)
        VALUES($1,$2,$3,NOW(),NOW())
        ON CONFLICT(referrer_id, invited_user_id) DO UPDATE SET validated_at=NOW()
        """, referrer_id, invited_user_id, invite_link)
        await con.execute("DELETE FROM pending_joins WHERE invited_user_id=$1", invited_user_id)
        valid = await con.fetchval("SELECT COUNT(*) FROM referrals WHERE referrer_id=$1 AND validated_at IS NOT NULL", referrer_id)
        level = reward_count(valid)
        old = await con.fetchval("SELECT COALESCE(max_videos_sent,0) FROM user_rewards WHERE user_id=$1", referrer_id)
        old = old or 0

    if level > old:
        await send_reward_link(context, referrer_id, level)
        async with db_pool.acquire() as con:
            await con.execute("""
            INSERT INTO user_rewards(user_id,max_videos_sent,updated_at)
            VALUES($1,$2,NOW())
            ON CONFLICT(user_id) DO UPDATE SET max_videos_sent=$2, updated_at=NOW()
            """, referrer_id, level)


async def send_reward_link(context: ContextTypes.DEFAULT_TYPE, user_id: int, level: int):
    async with db_pool.acquire() as con:
        row = await con.fetchrow("SELECT url FROM reward_links WHERE level=$1", level)
    if not row or not row["url"]:
        return
    try:
        await context.bot.send_message(user_id, f"🎁 Tu as débloqué le palier {level}/60 :\n{row['url']}")
    except Forbidden:
        print(f"Cannot send reward link to {user_id}: user did not start bot", flush=True)
    except Exception as e:
        print(f"SEND REWARD LINK ERROR {user_id}: {e}", flush=True)


# ---------------- PRIVATE ADMIN ----------------

async def handle_private_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    if not user or not msg or not is_admin(user.id):
        return

    state = await get_admin_state(user.id)
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


    if state == "setting_rules":
        await set_setting("rules_text", text)
        await set_admin_state(user.id, None)
        await msg.reply_text("✅ Règles mises à jour.")
        return

    if state == "broadcast_group":
        sent = await context.bot.send_message(GROUP_ID, text)
        await save_message(GROUP_ID, sent.message_id, None, True)
        await set_admin_state(user.id, None)
        await msg.reply_text("✅ Broadcast envoyé dans le groupe.")
        return

    if state and state.startswith("set_reward_link:"):
        level = int(state.split(":", 1)[1])
        async with db_pool.acquire() as con:
            await con.execute("""
            INSERT INTO reward_links(level,url,updated_at)
            VALUES($1,$2,NOW())
            ON CONFLICT(level) DO UPDATE SET url=$2, updated_at=NOW()
            """, level, text)
        await set_admin_state(user.id, None)
        await msg.reply_text(f"✅ Lien palier {level} mis à jour.")
        return

    if state == "ban_hash":
        if not message_has_media(msg):
            await msg.reply_text("❌ Envoie une photo ou une vidéo.")
            return
        h = await media_hash_from_message(context, msg)
        async with db_pool.acquire() as con:
            await con.execute("""
            INSERT INTO banned_hashes(hash,media_type,reason)
            VALUES($1,$2,$3)
            ON CONFLICT(hash) DO UPDATE SET reason=$3
            """, h, media_type(msg), "hash interdit admin")
        await set_admin_state(user.id, None)
        await msg.reply_text("✅ Hash banni. Toute republication sera bannie automatiquement.")
        return
    if message_has_media(msg):
        await msg.reply_text("ℹ️ Média reçu, mais aucun mode actif. Pour bannir un hash, clique d’abord sur 🚫 Ban hash dans le panel.")
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
    await add_danger(user.id, 10, reason)
    await increment_ban_count()
    if await is_silent():
        return

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

    msg = update.message
    user = update.effective_user

    # 0) Supprime messages Telegram automatiques entrée/sortie.
    if msg.new_chat_members or msg.left_chat_member:
        await delete_message_safe(context, update.effective_chat.id, msg.message_id)
        return

    if not user:
        return

    # 1) Commandes trusted /ban et /supprime sont traitées par CommandHandler avant ce handler.
    admin_exempt = await is_group_admin(context, user.id)

    # 2) Les autres commandes / sont supprimées. Récidive = mute 1 mois.
    if msg.text and msg.text.startswith("/") and not admin_exempt:
        await delete_message_safe(context, GROUP_ID, msg.message_id)
        async with db_pool.acquire() as con:
            row = await con.fetchrow("SELECT score FROM danger_scores WHERE user_id=$1", user.id)
            score = row["score"] if row else 0
        await add_danger(user.id, 2, "commande slash")
        if score >= 2:
            until = datetime.now(TZ) + timedelta(days=30)
            try:
                await context.bot.restrict_chat_member(
                    GROUP_ID,
                    user.id,
                    ChatPermissions(can_send_messages=False),
                    until_date=until
                )
            except Exception as e:
                print(f"SLASH MUTE ERROR: {e}", flush=True)
        return

    await upsert_participant(user)
    await save_user_message_if_session(update)

    if await get_setting("moderation", "on") != "on":
        return

    # 3) Admins/owner exemptés de toutes les règles fortes.
    if admin_exempt:
        return

    text = (msg.text or msg.caption or "").lower()

    # 4) Anti-lien prioritaire : ban direct même si participation ON.
    if await get_setting("anti_links", "on") == "on" and URL_RE.search(text):
        await punish_ban(update, context, "envoi de lien")
        return

    # 5) Transferts interdits prioritaires.
    is_forward = bool(
        msg.forward_origin
        or getattr(msg, "forward_date", None)
        or getattr(msg, "forward_from", None)
        or getattr(msg, "forward_from_chat", None)
    )
    if is_forward:
        await punish_ban(update, context, "transfert de message")
        return

    # 6) Photo + mention prioritaire.
    if await get_setting("anti_photo_mention", "on") == "on":
        has_photo = bool(msg.photo)
        has_mention = bool(
            msg.caption_entities
            and any(e.type in ("mention", "text_mention") for e in msg.caption_entities)
        )
        if has_photo and has_mention:
            await punish_ban(update, context, "photo avec identification")
            return

    # 7) Hash média : ban hash puis anti-repost avant participation.
    h = None
    if message_has_media(msg):
        try:
            h = await media_hash_from_message(context, msg)
        except Exception as e:
            print(f"HASH ERROR: {e}", flush=True)

    if h:
        async with db_pool.acquire() as con:
            banned = await con.fetchrow("SELECT hash FROM banned_hashes WHERE hash=$1", h)

        if banned:
            await punish_ban(
                update,
                context,
                "hash interdit",
                "🚫 Je viens de choper automatiquement une publication interdite ici."
            )
            return

        if await get_setting("anti_repost", "on") == "on":
            async with db_pool.acquire() as con:
                old = await con.fetchrow("""
                SELECT hash FROM media_hashes
                WHERE hash=$1 AND created_at > NOW() - INTERVAL '10 days'
                LIMIT 1
                """, h)

            if old:
                await delete_message_safe(context, GROUP_ID, msg.message_id)
                if await get_setting("participation", "off") == "on" and not await has_participated(user.id):
                    warn = await context.bot.send_message(
                        GROUP_ID,
                        "♻️ Ce média a déjà été envoyé. Merci de participer avec un contenu nouveau."
                    )
                else:
                    warn = await context.bot.send_message(GROUP_ID, "♻️ C’est du vu et déjà vu.")
                await save_message(GROUP_ID, warn.message_id, None, True)
                await add_danger(user.id, 2, "repost média")
                return

        async with db_pool.acquire() as con:
            await con.execute("""
            INSERT INTO media_hashes(hash,chat_id,user_id,message_id,media_type,used_for_participation)
            VALUES($1,$2,$3,$4,$5,$6)
            ON CONFLICT(hash) DO NOTHING
            """, h, GROUP_ID, user.id, msg.message_id, media_type(msg), bool(message_is_photo_or_video(msg)))

    # 8) Mots interdits.
    async with db_pool.acquire() as con:
        words = await con.fetch("SELECT word FROM banned_words")
    for r in words:
        word = r["word"].lower()
        if word and re.search(rf"\b{re.escape(word)}\b", text, re.I):
            await punish_word(update, context)
            return

    # 9) Participation obligatoire EN DERNIER.
    if await get_setting("participation", "off") == "on":
        if not await has_participated(user.id):
            if not message_is_photo_or_video(msg):
                await delete_message_safe(context, GROUP_ID, msg.message_id)
                await send_temp_message(
                    context,
                    GROUP_ID,
                    "Merci de participer avant d’envoyer un message.",
                    seconds=45
                )
                await add_danger(user.id, 1, "message avant participation")
                return

            if h:
                await mark_participated(user.id, h)
                return

    return


async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmu = update.chat_member
    if not cmu or cmu.chat.id != GROUP_ID:
        return

    old_status = cmu.old_chat_member.status
    new_status = cmu.new_chat_member.status
    user = cmu.new_chat_member.user

    if old_status in ("left", "kicked") and new_status in ("member", "restricted"):
        await upsert_participant(user)
        if user.is_bot:
            try:
                await context.bot.ban_chat_member(GROUP_ID, user.id)
            except Exception:
                pass
            return
        if await get_setting("raid_mode", "off") == "on":
            try:
                until = datetime.now(TZ) + timedelta(hours=6)
                await context.bot.restrict_chat_member(GROUP_ID, user.id, ChatPermissions(can_send_messages=False), until_date=until)
            except Exception as e:
                print(f"RAID MUTE NEW MEMBER ERROR: {e}", flush=True)
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




# ---------------- PARTICIPATION / RULES ----------------

async def warn_non_participants(context):
    if await get_setting("participation", "off") != "on":
        return 0

    kicked_total = await get_setting("non_participants_kicked_total", "0")
    kick_np = await get_setting("kick_non_participants", "off")

    async with db_pool.acquire() as con:
        rows = await con.fetch("""
        SELECT user_id, username, first_name
        FROM participants
        WHERE has_participated=FALSE
        ORDER BY joined_at ASC
        LIMIT 200
        """)

    if not rows:
        return 0

    total = 0
    for i in range(0, len(rows), 20):
        batch = rows[i:i+20]
        mentions = []
        for r in batch:
            if r["username"]:
                mentions.append(f"@{r['username']}")
            else:
                mentions.append(f'<a href="tg://user?id={r["user_id"]}">{r["first_name"] or r["user_id"]}</a>')

        txt = (
            "⚠️ Veuillez participer si vous voulez rester dans le groupe.\n"
            "Envoyez au moins 1 photo ou 1 vidéo jamais déjà postée.\n\n"
            "✅ Une seule participation valide suffit pour rester définitivement.\n\n"
            "Si vous ne participez pas, vous serez supprimé du groupe sous peu.\n\n"
            f"🥾 Déjà supprimés pour non-participation : {kicked_total}\n"
            f"🥾 Kick automatique : {'ON' if kick_np == 'on' else 'OFF'}\n"
            "Limite : 20 suppressions / jour\n\n"
        )
        txt += " ".join(mentions)

        msg = await context.bot.send_message(GROUP_ID, txt, parse_mode="HTML")
        await save_message(GROUP_ID, msg.message_id, None, True)
        total += len(batch)
        await asyncio.sleep(0.2)

        async with db_pool.acquire() as con:
            for r in batch:
                await con.execute("""
                UPDATE participants
                SET warn_count=warn_count+1, last_warned_at=NOW()
                WHERE user_id=$1
                """, r["user_id"])

    return total


async def kick_old_non_participants(context):
    if await get_setting("participation", "off") != "on":
        return
    if await get_setting("kick_non_participants", "off") != "on":
        return

    today = datetime.now(TZ).strftime("%Y-%m-%d")
    last_day = await get_setting("last_nonparticipant_kick_date", "")

    if last_day != today:
        await set_setting("last_nonparticipant_kick_date", today)
        await set_setting("nonparticipant_kicked_today", "0")

    kicked_today = int(await get_setting("nonparticipant_kicked_today", "0") or "0")
    remaining = max(0, 20 - kicked_today)
    if remaining <= 0:
        return

    async with db_pool.acquire() as con:
        rows = await con.fetch("""
        SELECT user_id
        FROM participants
        WHERE has_participated=FALSE
          AND joined_at < NOW() - INTERVAL '3 days'
        ORDER BY joined_at ASC
        LIMIT $1
        """, remaining)

    if not rows:
        return

    kicked = 0
    for r in rows:
        uid = r["user_id"]
        try:
            await context.bot.ban_chat_member(GROUP_ID, uid)
            await context.bot.unban_chat_member(GROUP_ID, uid, only_if_banned=True)
            kicked += 1
        except Exception as e:
            print(f"KICK NON PARTICIPANT ERROR {uid}: {e}", flush=True)

        async with db_pool.acquire() as con:
            await con.execute("DELETE FROM participants WHERE user_id=$1", uid)
            await con.execute("DELETE FROM pending_joins WHERE invited_user_id=$1", uid)

        await asyncio.sleep(0.1)

    if kicked:
        old_total = int(await get_setting("non_participants_kicked_total", "0") or "0")
        await set_setting("non_participants_kicked_total", old_total + kicked)
        await set_setting("nonparticipant_kicked_today", kicked_today + kicked)

        report = (
            "🥾 Bilan kick non-participants\n\n"
            f"Supprimés aujourd'hui : {kicked_today + kicked}/20\n"
            f"Nouveaux supprimés maintenant : {kicked}\n"
            f"Total supprimés pour non-participation : {old_total + kicked}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, report)
            except Exception as e:
                print(f"KICK REPORT SEND ERROR admin={admin_id}: {e}", flush=True)


async def post_rules(context):
    if await get_setting("rules_auto", "off") != "on":
        return
    if await get_setting("group_open", "off") != "on":
        return
    old_id = int(await get_setting("rules_message_id", "0") or "0")
    if old_id:
        await delete_message_safe(context, GROUP_ID, old_id)
    text = await get_setting("rules_text", "")
    if not text:
        return
    msg = await context.bot.send_message(GROUP_ID, text)
    await save_message(GROUP_ID, msg.message_id, None, True)
    await set_setting("rules_message_id", msg.message_id)

async def ban_report(context):
    if await get_setting("group_open", "off") != "on":
        return
    count = int(await get_setting("ban_report_count", "0") or "0")
    if count <= 0:
        return
    msg = await context.bot.send_message(GROUP_ID, f"⚠️ Bilan sécurité : {count} sanction(s) automatique(s) depuis l'ouverture. Respectez les règles.")
    await save_message(GROUP_ID, msg.message_id, None, True)

# ---------------- SCHEDULE ----------------

def get_schedule_for_day(now: datetime):
    # 0=lundi, 5=samedi, 6=dimanche
    wd = now.weekday()
    if wd == 5:
        return {"open_hour": 23, "open_minute": 0, "close_hour": 1, "close_minute": 0}
    if wd == 6:
        return {"open_hour": 22, "open_minute": 30, "close_hour": 0, "close_minute": 15}
    return {"open_hour": 22, "open_minute": 0, "close_hour": 0, "close_minute": 0}


def target_datetime(now: datetime, hour: int, minute: int):
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def minutes_until(now: datetime, hour: int, minute: int) -> int:
    seconds = int((target_datetime(now, hour, minute) - now).total_seconds())
    return max(0, (seconds + 59) // 60)


def is_open_window_precise(now: datetime, schedule: dict) -> bool:
    open_today = now.replace(hour=schedule["open_hour"], minute=schedule["open_minute"], second=0, microsecond=0)
    close_today = now.replace(hour=schedule["close_hour"], minute=schedule["close_minute"], second=0, microsecond=0)

    if close_today <= open_today:
        close_today += timedelta(days=1)

    open_yesterday = open_today - timedelta(days=1)
    close_yesterday = close_today - timedelta(days=1)

    return (open_today <= now < close_today) or (open_yesterday <= now < close_yesterday)


async def send_countdown_once(context: ContextTypes.DEFAULT_TYPE, key: str, text: str):
    last = await get_setting("last_countdown_key", "")
    if last == key:
        return
    await set_setting("last_countdown_key", key)
    await send_system_message(context, text, "countdown", record_in_session=False)


async def hourly_job(context: ContextTypes.DEFAULT_TYPE):
    if await get_setting("auto_schedule", "on") != "on":
        return

    now = datetime.now(TZ)
    schedule = get_schedule_for_day(now)

    group_open = await get_setting("group_open", "off")
    should_be_open = is_open_window_precise(now, schedule)

    open_h = schedule["open_hour"]
    open_m = schedule["open_minute"]
    close_h = schedule["close_hour"]
    close_m = schedule["close_minute"]

    if should_be_open and group_open != "on":
        await set_setting("last_countdown_key", "")
        await open_group(context)
        await warn_non_participants(context)
        return

    if not should_be_open and group_open == "on":
        await set_setting("last_countdown_key", "")
        await close_group_and_clean(context)
        return

    # Groupe fermé : countdown vers ouverture.
    if group_open != "on":
        m = minutes_until(now, open_h, open_m)

        # Avant la dernière heure : uniquement à l'heure pile, en heures.
        if m > 60:
            if now.minute == 0:
                hours = max(1, (m + 59) // 60)
                await send_countdown_once(
                    context,
                    f"open_h_{hours}",
                    f"⏰ Prochaine ouverture dans {hours} heure(s)."
                )
            return

        # Dernière heure : en minutes.
        if m == 60:
            await send_countdown_once(context, "open_60", "⏰ Prochaine ouverture dans 60 minutes.")
        elif m == 30:
            await send_countdown_once(context, "open_30", "⏰ Prochaine ouverture dans 30 minutes.")
        elif m == 10:
            await send_countdown_once(context, "open_10", "⏰ Ouverture dans 10 minutes.")
        elif 1 <= m <= 5:
            await send_countdown_once(context, f"open_{m}", f"⏰ Ouverture dans {m} minute(s).")
        return

    # Groupe ouvert : countdown vers fermeture.
    m = minutes_until(now, close_h, close_m)

    if m == 30:
        await send_countdown_once(context, "close_30", "⚠️ Fermeture du groupe dans 30 minutes.")
    elif m == 15:
        await send_countdown_once(context, "close_15", "⚠️ Fermeture du groupe dans 15 minutes.")
    elif 1 <= m <= 5:
        await send_countdown_once(context, f"close_{m}", f"⚠️ Fermeture dans {m} minute(s).")


async def post_init(app):
    await init_db()
    app.job_queue.run_repeating(hourly_job, interval=60, first=10)
    app.job_queue.run_repeating(post_rules, interval=15 * 60, first=90)
    app.job_queue.run_repeating(ban_report, interval=20 * 60, first=120)
    app.job_queue.run_repeating(kick_old_non_participants, interval=6 * 60 * 60, first=300)


async def error_handler(update, context):
    print(f"ERROR: {context.error}", flush=True)


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("supprime", trusted_supprime, filters=filters.Chat(GROUP_ID)))
    app.add_handler(CommandHandler("ban", trusted_ban, filters=filters.Chat(GROUP_ID)))
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
