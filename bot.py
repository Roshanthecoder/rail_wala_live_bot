import os
import asyncio
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ================= ENV =================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TRAIN_API_URL = os.getenv("TRAIN_API_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://your-app.onrender.com

# ================= LOGGING =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= GLOBALS =================
active_trains = {}
message_ids = {}

# ================= UTILS =================
def fmt_time(ts):
    if not ts:
        return "N/A"
    return datetime.fromtimestamp(ts).strftime("%I:%M %p")

def delay_hm(actual, scheduled):
    if not actual or not scheduled:
        return "N/A"
    diff = actual - scheduled
    if diff <= 0:
        return "On Time"
    h = diff // 3600
    m = (diff % 3600) // 60
    return f"{int(h)}h {int(m)}m" if h else f"{int(m)}m"

# ================= FLASK =================
app = Flask(__name__)
bot_app = Application.builder().token(BOT_TOKEN).build()

@app.route("/")
def home():
    return "🚆 Train Live Bot Running"

@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.json, bot_app.bot)
    asyncio.get_event_loop().create_task(
        bot_app.process_update(update)
    )
    return "ok"


# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚆 Train Live Bot\n\n"
        "Use `/addtrain <train_no>` to track train",
        parse_mode="Markdown"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    train = active_trains.get(chat_id)
    if not train:
        await update.message.reply_text("❌ No active train")
    else:
        await update.message.reply_text(f"✅ Tracking Train `{train}`", parse_mode="Markdown")

async def add_train(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text("Usage: `/addtrain 12303`", parse_mode="Markdown")
        return

    train_no = context.args[0]
    active_trains[chat_id] = train_no

    for job in context.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()

    context.job_queue.run_repeating(
        fetch_and_render,
        interval=60,
        first=2,
        chat_id=chat_id,
        name=str(chat_id)
    )

    await update.message.reply_text(f"🚆 Tracking Train `{train_no}`", parse_mode="Markdown")

async def remove_train(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    active_trains.pop(chat_id, None)

    for job in context.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()

    await update.message.reply_text("🗑️ Tracking stopped")

# ================= JOB =================
async def fetch_and_render(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    train_no = active_trains.get(chat_id)
    if not train_no:
        return

    try:
        r = requests.get(TRAIN_API_URL, params={"trainNo": train_no}, timeout=10)
        data = r.json()
        if not data.get("success"):
            return

        info = data["data"]
        route = info["route"]
        pos = info["currentPosition"]
        code = pos.get("stationCode")

        idx = next(i for i, s in enumerate(route) if s["stationCode"] == code)
        cur = route[idx]
        nxt = route[idx + 1] if idx < len(route) - 1 else None

        text = (
            f"🚆 *Train {train_no}*\n"
            f"📍 {cur['station_name']}\n"
            f"🕒 {fmt_time(cur.get('actualArrivalTime'))}\n"
        )

        if chat_id in message_ids:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_ids[chat_id],
                text=text,
                parse_mode="Markdown"
            )
        else:
            msg = await context.bot.send_message(chat_id, text, parse_mode="Markdown")
            message_ids[chat_id] = msg.message_id

    except Exception as e:
        logger.error(e)

# ================= INIT =================
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("status", status))
bot_app.add_handler(CommandHandler("addtrain", add_train))
bot_app.add_handler(CommandHandler("removetrain", remove_train))

async def init_bot():
    await bot_app.initialize()
    await bot_app.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    logger.info("Webhook set successfully")

asyncio.get_event_loop().create_task(init_bot())


