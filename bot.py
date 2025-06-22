import os
import asyncio
import logging
from datetime import datetime, timedelta
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------- Logging Setup ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- Environment Variables ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
VAULT_CHANNEL_ID = int(os.getenv("VAULT_CHANNEL_ID"))
MAIN_CHANNEL_ID = int(os.getenv("MAIN_CHANNEL_ID"))
FORCE_JOIN_CHANNEL = os.getenv("FORCE_JOIN_CHANNEL").lstrip("@")
DEVELOPER_USERNAME = os.getenv("DEVELOPER_USERNAME")
BOT_USERNAME = os.getenv("BOT_USERNAME")

# ---------- MongoDB Setup ----------
mongo = MongoClient(MONGO_URI)
db = mongo["corn_world"]
collection = db["video_logs"]

# ---------- Check if User Joined Required Channel ----------
async def is_user_joined(bot, user_id):
    try:
        member = await bot.get_chat_member(chat_id=f"@{FORCE_JOIN_CHANNEL}", user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning(f"Force join check failed: {e}")
        return False

# ---------- Admin Video Handler ----------
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message
        user_id = message.from_user.id
        logger.info(f"Received message from {user_id}")

        if user_id not in ADMIN_IDS:
            await message.reply_text("❌ You are not authorized to upload content.")
            return

        if not message.video:
            await message.reply_text("❌ Please send a proper video file.")
            return

        # Save to vault
        sent_msg = await context.bot.copy_message(
            chat_id=VAULT_CHANNEL_ID,
            from_chat_id=message.chat_id,
            message_id=message.message_id
        )

        payload = f"get-{sent_msg.message_id}"
        start_link = f"https://t.me/{BOT_USERNAME}?start={payload}"
        thumbnail = message.video.thumbnail.file_id if message.video.thumbnail else message.video.file_id

        caption = f"""🎬 <b>New Content</b>

👉 <a href="{start_link}">Watch Now</a>"""

        await context.bot.send_photo(
            chat_id=MAIN_CHANNEL_ID,
            photo=thumbnail,
            caption=caption,
            parse_mode="HTML"
        )

        await message.reply_text("✅ Video successfully posted to the channel.")

    except Exception as e:
        logger.error(f"handle_video error: {e}")
        await update.message.reply_text("❌ An error occurred while processing your video.")

# ---------- Start Command ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = context.args
        user_id = update.effective_user.id

        if not await is_user_joined(context.bot, user_id):
            btn = [[InlineKeyboardButton("🔒 Join Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL}")]]
            reply_markup = InlineKeyboardMarkup(btn)

            if update.message:
                await update.message.reply_text(
                    "🚫 You must join our channel first.",
                    reply_markup=reply_markup
                )
            return

        # If user came with payload
        if args and args[0].startswith("get-"):
            try:
                message_id = int(args[0].split("-")[1])
                sent = await context.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=VAULT_CHANNEL_ID,
                    message_id=message_id
                )
                await context.bot.send_message(
                    chat_id=user_id,
                    text="⚠️ This video will be deleted in 1 hour due to copyright."
                )

                collection.insert_one({
                    "chat_id": user_id,
                    "message_id": sent.message_id,
                    "delete_at": datetime.utcnow() + timedelta(hours=1)
                })

            except Exception as e:
                logger.error(f"start command payload error: {e}")
                await context.bot.send_message(chat_id=user_id, text="❌ Failed to fetch the video.")
        else:
            # No payload = welcome message
            btn = [[
                InlineKeyboardButton("👨‍💻 Developer", url=f"https://t.me/{DEVELOPER_USERNAME}"),
                InlineKeyboardButton("🔞 Tharki Hub Bot", url="https://t.me/tharki_hub_bot")
            ]]
            await update.message.reply_photo(
                photo="https://telegra.ph/file/6e3fdcfb0cf67cf34c178.jpg",
                caption="👋 Welcome to Corn World Bot!",
                reply_markup=InlineKeyboardMarkup(btn)
            )

    except Exception as e:
        logger.error(f"start command error: {e}")

# ---------- Auto Delete Background Task ----------
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
                        text="✅ Video deleted successfully.\nJoin @corn_world_bot_backup for more!"
                    )
                    collection.delete_one({"_id": doc["_id"]})
                except Exception as e:
                    logger.error(f"Error deleting message: {e}")

            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Auto delete loop error: {e}")
            await asyncio.sleep(60)

# ---------- Error Handler ----------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

# ---------- Main ----------
if __name__ == "__main__":
    import threading

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(CommandHandler("start", start))
    app.add_error_handler(error_handler)

    def start_background_loop():
        asyncio.run(auto_delete(app))

    threading.Thread(target=start_background_loop, daemon=True).start()

    logger.info("Corn World Bot started successfully!")
    app.run_polling()
