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
    CallbackQueryHandler,
    ContextTypes,
    filters
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
FORCE_JOIN_CHANNEL = os.getenv("FORCE_JOIN_CHANNEL")
DEVELOPER_USERNAME = os.getenv("DEVELOPER_USERNAME")
BOT_USERNAME = os.getenv("BOT_USERNAME")

# ---------- MongoDB ----------
mongo = MongoClient(MONGO_URI)
db = mongo["corn_world"]
collection = db["video_logs"]

# ---------- Check Force Join ----------
async def is_user_joined(bot, user_id):
    try:
        member = await bot.get_chat_member(chat_id=FORCE_JOIN_CHANNEL, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        return False

# ---------- Admin Video Upload ----------
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return

    video = update.message.video
    if not video:
        await update.message.reply_text("Please send a valid video.")
        return

    msg = await context.bot.copy_message(
        chat_id=VAULT_CHANNEL_ID,
        from_chat_id=update.message.chat_id,
        message_id=update.message.message_id
    )

    payload = f"get-{msg.message_id}"
    start_link = f"https://t.me/{BOT_USERNAME}?start={payload}"
    thumbnail = video.thumbnail.file_id if video.thumbnail else video.file_id

    await context.bot.send_photo(
        chat_id=MAIN_CHANNEL_ID,
        photo=thumbnail,
        caption=f"🎬 <b>New Content</b>\n\n👉 <a href='{start_link}'>Watch Now</a>",
        parse_mode="HTML"
    )

# ---------- Start Command ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id

    if not await is_user_joined(context.bot, user_id):
        btn = [[InlineKeyboardButton("🔒 Join Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL.lstrip('@')}")]]
        await update.message.reply_text(
            "🚫 You must join our channel first.",
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
            text="⚠️ This video will be deleted in 1 hour due to copyright."
        )
        delete_time = datetime.utcnow() + timedelta(hours=1)
        collection.insert_one({
            "chat_id": user_id,
            "message_id": sent.message_id,
            "delete_at": delete_time
        })
    else:
        btn = [[
            InlineKeyboardButton("👨‍💻 Developer", url=f"https://t.me/{DEVELOPER_USERNAME}"),
            InlineKeyboardButton("🔞 Tharki Hub Bot", url="https://t.me/tharki_hub_bot")
        ]]
        await update.message.reply_photo(
            photo="https://telegra.ph/file/6e3fdcfb0cf67cf34c178.jpg",  # Replace with welcome image URL
            caption="👋 Welcome to Corn World Bot!",
            reply_markup=InlineKeyboardMarkup(btn)
        )

# ---------- Auto Delete Logic ----------
async def auto_delete(app):
    while True:
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
                logger.error(f"Delete failed: {e}")

        await asyncio.sleep(60)

# ---------- Main ----------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(CommandHandler("start", start))

    # Start auto-delete loop
    app.job_queue.run_once(lambda ctx: asyncio.create_task(auto_delete(app)), when=5)

    logger.info("Corn World Bot started!")
    app.run_polling()
