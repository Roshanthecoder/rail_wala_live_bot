import os
import asyncio
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ================= ENV =================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TRAIN_API_URL = os.getenv("TRAIN_API_URL")

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ================= GLOBALS =================
active_trains = {}      # chat_id -> train_no
message_ids = {}        # chat_id -> message_id
animation_tasks = {}    # chat_id -> asyncio.Task

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

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"/start command received from chat_id={update.effective_chat.id}")
    await update.message.reply_text(
        "🚆 *Train Live Bot*\n\n"
        "/addtrain <train_no> - Track a train\n"
        "/removetrain - Stop tracking\n"
        "/status - See active trains",
        parse_mode="Markdown"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    logger.info(f"/status command received from chat_id={chat_id}")

    if not active_trains:
        await update.message.reply_text("🤖 Bot is running but no trains are being tracked.")
        return

    text = "🤖 *Bot Active Trains:*\n\n"
    for chat, train_no in active_trains.items():
        text += f"Chat ID {chat}: Train {train_no}\n"
    await update.message.reply_text(text, parse_mode="Markdown")
    logger.info(f"Sent status message to chat_id={chat_id}")

async def add_train(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    logger.info(f"/addtrain command received from chat_id={chat_id} with args={context.args}")

    if not context.args:
        await update.message.reply_text("❌ Usage: /addtrain <train_no>")
        logger.warning(f"No train number provided by chat_id={chat_id}")
        return

    train_no = context.args[0].strip()
    active_trains[chat_id] = train_no
    logger.info(f"Tracking started for train {train_no} in chat_id={chat_id}")

    # Cancel old animation task if exists
    if task := animation_tasks.get(chat_id):
        task.cancel()
        animation_tasks.pop(chat_id, None)
        logger.info(f"Cancelled previous animation task for chat_id={chat_id}")

    # Remove old job if exists
    for job in context.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()
        logger.info(f"Removed old job for chat_id={chat_id}")

    # Clear old message_id to force sending a new message
    message_ids.pop(chat_id, None)

    # Schedule repeating job
    context.job_queue.run_repeating(
        fetch_and_render,
        interval=60,
        first=1,  # run immediately
        chat_id=chat_id,
        name=str(chat_id)
    )

    await update.message.reply_text(f"✅ Tracking Train {train_no}")

async def remove_train(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    logger.info(f"/removetrain command received from chat_id={chat_id}")

    active_trains.pop(chat_id, None)
    logger.info(f"Stopped tracking train for chat_id={chat_id}")

    # Remove scheduled jobs
    for job in context.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()
        logger.info(f"Removed job from job queue for chat_id={chat_id}")

    # Cancel animation task if running
    if task := animation_tasks.get(chat_id):
        task.cancel()
        animation_tasks.pop(chat_id, None)
        logger.info(f"Cancelled animation task for chat_id={chat_id}")

    # Remove old message_id
    message_ids.pop(chat_id, None)

    await update.message.reply_text("🗑️ Tracking stopped")

# ================= CORE =================
async def fetch_and_render(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    train_no = active_trains.get(chat_id)
    if not train_no:
        logger.warning(f"No active train for chat_id={chat_id}")
        return

    logger.info(f"Fetching data for train {train_no} for chat_id={chat_id}")

    try:
        r = requests.get(
            TRAIN_API_URL,
            params={"trainNo": train_no},
            headers={"user-agent": "Mozilla/5.0"},
            timeout=10
        )
        data = r.json()
        if not data.get("success"):
            logger.warning(f"API response unsuccessful for train {train_no}")
            return

        info = data["data"]
        route = info["route"]
        pos = info["currentPosition"]
        code = pos.get("stationCode")

        idx = next(i for i, s in enumerate(route) if s["stationCode"] == code)
        cur = route[idx]
        prev = route[idx - 1] if idx > 0 else None
        nxt = route[idx + 1] if idx < len(route) - 1 else None

        base_text = (
            f"🚆 *Train {train_no}*\n\n"
            f"📍 *Current Station*\n"
            f"{cur['station_name']}\n"
            f"🕒 Reached: {fmt_time(cur.get('actualArrivalTime'))}\n"
            f"📏 Distance Covered: {round(pos.get('distanceFromOriginKm', 0), 2)} km\n\n"
        )

        if prev:
            base_text += (
                f"⬅️ *Previous Station*\n"
                f"{prev['station_name']}\n"
                f"🚉 Departed: {fmt_time(prev.get('actualDepartureTime'))}\n"
                f"🛤️ Platform: {prev.get('platformNumber','N/A')}\n\n"
            )

        if nxt:
            base_text += (
                f"➡️ *Next Station*\n"
                f"{nxt['station_name']}\n"
                f"⏰ Expected: {fmt_time(nxt.get('actualArrivalTime'))}\n"
                f"🕒 Scheduled: {fmt_time(nxt.get('scheduledArrivalTime'))}\n"
                f"⏱️ Delay: {delay_hm(nxt.get('actualArrivalTime'), nxt.get('scheduledArrivalTime'))}\n"
                f"🛤️ Platform: {nxt.get('platformNumber','N/A')}\n"
            )

        # ===== SEND / UPDATE BASE MESSAGE =====
        if chat_id not in message_ids:
            msg = await context.bot.send_message(chat_id, base_text, parse_mode="Markdown")
            message_ids[chat_id] = msg.message_id
            logger.info(f"Sent initial message for train {train_no} to chat_id={chat_id}")
        else:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_ids[chat_id],
                    text=base_text,
                    parse_mode="Markdown"
                )
                logger.info(f"Updated message for train {train_no} in chat_id={chat_id}")
            except Exception as e:
                logger.warning(f"Failed to edit message, sending new message instead: {e}")
                msg = await context.bot.send_message(chat_id, base_text, parse_mode="Markdown")
                message_ids[chat_id] = msg.message_id

        # ===== START ANIMATION TASK ONCE =====
        if chat_id not in animation_tasks:
            task = asyncio.create_task(animate_message(context, chat_id, base_text))
            animation_tasks[chat_id] = task
            logger.info(f"Started animation task for chat_id={chat_id}")

    except Exception as e:
        logger.error(f"Error fetching/rendering train data: {e}")

# ================= ANIMATION =================
async def animate_message(context, chat_id, base_text):
    frames = [
        ("📍", "⬅️ .", "➡️"),
        ("📍➤", "⬅️ . .", "➡️➡️"),
        ("📍➤📍", "⬅️ . . .", "➡️➡️➡️")
    ]

    try:
        while True:
            for c, p, n in frames:
                animated = (
                    base_text
                    .replace("📍 *Current Station*", f"{c} *Current Station*")
                    .replace("⬅️ *Previous Station*", f"{p} *Previous Station*")
                    .replace("➡️ *Next Station*", f"{n} *Next Station*")
                )
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_ids[chat_id],
                    text=animated,
                    parse_mode="Markdown"
                )
                await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info(f"Animation task cancelled for chat_id={chat_id}")
        return
    except Exception as e:
        logger.error(f"Animation error for chat_id={chat_id}: {e}")

# ================= MAIN =================
async def main():
    logger.info("Starting Train Live Bot...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("addtrain", add_train))
    app.add_handler(CommandHandler("removetrain", remove_train))
    await app.run_polling()
    logger.info("Bot stopped.")

# ================= MAIN =================
if __name__ == "__main__":
    logger.info("Starting Train Live Bot...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("addtrain", add_train))
    app.add_handler(CommandHandler("removetrain", remove_train))
    
    # Directly run polling, no asyncio.run()
    app.run_polling()
    logger.info("Bot stopped.")
