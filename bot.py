import os
import asyncio
import logging
import tempfile
import aiohttp
from datetime import datetime, timedelta
from pymongo import MongoClient
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ------------ Config & Logging ------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
VAULT_CHANNEL_ID = int(os.getenv("VAULT_CHANNEL_ID"))
MAIN_CHANNEL_ID = int(os.getenv("MAIN_CHANNEL_ID"))
FORCE_JOIN_CHANNEL = os.getenv("FORCE_JOIN_CHANNEL").lstrip("@")
DEVELOPER_USERNAME = os.getenv("DEVELOPER_USERNAME")
BOT_USERNAME = os.getenv("BOT_USERNAME")

mongo = MongoClient(MONGO_URI)
db = mongo["corn_world"]
collection = db["video_logs"]

# In-memory preview queue
PENDING_PREVIEWS = {}

# ------------ Force Join Check ------------
async def is_user_joined(bot, user_id):
    try:
        member = await bot.get_chat_member(chat_id=f"@{FORCE_JOIN_CHANNEL}", user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning(f"Force join check failed: {e}")
        return False

# ------------ Admin Sends Video ------------
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message
        user_id = message.from_user.id

        if user_id not in ADMIN_IDS:
            await message.reply_text("❌ You are not authorized.")
            return

        if not message.video:
            await message.reply_text("❌ Send a proper video.")
            return

        sent = await context.bot.copy_message(
            chat_id=VAULT_CHANNEL_ID,
            from_chat_id=message.chat_id,
            message_id=message.message_id
        )

        payload = f"get-{sent.message_id}"
        start_link = f"https://t.me/{BOT_USERNAME}?start={payload}"
        caption = f"🎬 <b>New Content</b>\n\n👉 <a href=\"{start_link}\">Watch Now</a>"

        preview = None
        if message.video.thumbnail:
            try:
                file = await context.bot.get_file(message.video.thumbnail.file_id)
                async with aiohttp.ClientSession() as session:
                    async with session.get(file.file_path) as resp:
                        if resp.status == 200:
                            with tempfile.NamedTemporaryFile(delete=False) as tf:
                                tf.write(await resp.read())
                                preview = InputFile(tf.name)
            except Exception as thumb_err:
                logger.warning(f"Thumbnail fetch failed: {thumb_err}")

        if preview:
            await context.bot.send_photo(
                chat_id=MAIN_CHANNEL_ID,
                photo=preview,
                caption=caption,
                parse_mode="HTML"
            )
            await message.reply_text("✅ Video posted.")
        else:
            PENDING_PREVIEWS[user_id] = {
                "caption": caption
            }
            await message.reply_text("⚠️ No thumbnail. Send an image for preview.")

    except Exception as e:
        logger.error(f"Video handler error: {e}")
        await message.reply_text("❌ Something went wrong.")

# ------------ Admin Sends Image for Preview ------------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user_id = message.from_user.id

    if user_id not in ADMIN_IDS:
        return

    if user_id in PENDING_PREVIEWS:
        data = PENDING_PREVIEWS.pop(user_id)
        caption = data["caption"]

        await context.bot.send_photo(
            chat_id=MAIN_CHANNEL_ID,
            photo=message.photo[-1].file_id,
            caption=caption,
            parse_mode="HTML"
        )
        await message.reply_text("✅ Preview posted.")
    else:
        await message.reply_text("❌ No pending preview request.")

# ------------ /start Handler ------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = context.args
        user_id = update.effective_user.id

        if not await is_user_joined(context.bot, user_id):
            btn = [[InlineKeyboardButton("🔒 Join Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL}")]]
            await update.message.reply_text(
                "🚫 Join our channel to continue.",
                reply_markup=InlineKeyboardMarkup(btn)
            )
            return

        if args and args[0].startswith("get-"):
            message_id = int(args[0].split("-")[1])
            sent = await context.bot.copy_message(
                chat_id=user_id,
                from_chat_id=VAULT_CHANNEL_ID,
                message_id=message_id
            )
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ This video will auto-delete in 1 hour."
            )
            collection.insert_one({
                "chat_id": user_id,
                "message_id": sent.message_id,
                "delete_at": datetime.utcnow() + timedelta(hours=1)
            })
        else:
            btn = [[
                InlineKeyboardButton("👨‍💻 Developer", url=f"https://t.me/{DEVELOPER_USERNAME}"),
                InlineKeyboardButton("🔞 Tharki Hub Bot", url="https://t.me/tharki_hub_bot")
            ]]
            await update.message.reply_photo(
                photo="https://graph.org/file/16b1a2828cc507f8048bd.jpg",
                caption=" Welcome to Corn World Bot! this is a file share bot",
                reply_markup=InlineKeyboardMarkup(btn)
            )

    except Exception as e:
        logger.error(f"Start command error: {e}")

# ------------ Auto Delete Loop ------------
async def auto_delete(app):
    while True:
        try:
            now = datetime.utcnow()
            expired = list(collection.find({"delete_at": {"$lte": now}}))

            for doc in expired:
                try:
                    await app.bot.delete_message(chat_id=doc["chat_id"], message_id=doc["message_id"])
                    await app.bot.send_message(
                        chat_id=doc["chat_id"],
                        text="✅ Video deleted.\nJoin @bot_backup for more!"
                    )
                    collection.delete_one({"_id": doc["_id"]})
                except Exception as e:
                    logger.error(f"Delete failed: {e}")

            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Auto delete loop error: {e}")
            await asyncio.sleep(60)

# ------------ Main Setup ------------
if __name__ == "__main__":
    import threading

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CommandHandler("start", start))

    def start_background_loop():
        asyncio.run(auto_delete(app))

    threading.Thread(target=start_background_loop, daemon=True).start()

    logger.info("Corn World Bot started ✅")
    app.run_polling()
