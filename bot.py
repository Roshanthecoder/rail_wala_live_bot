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

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚆 *Train Live Bot*\n\n"
        "/addtrain <train_no>\n"
        "/removetrain",
        parse_mode="Markdown"
    )

async def add_train(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    train_no = context.args[0]
    active_trains[chat_id] = train_no

    context.job_queue.run_repeating(
        fetch_and_render,
        interval=60,
        first=3,
        chat_id=chat_id,
        name=str(chat_id)
    )

    await update.message.reply_text(f"✅ Tracking Train {train_no}")

async def remove_train(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    active_trains.pop(chat_id, None)

    for job in context.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()

    await update.message.reply_text("🗑️ Tracking stopped")

# ================= CORE =================
async def fetch_and_render(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    train_no = active_trains.get(chat_id)
    if not train_no:
        return

    try:
        r = requests.get(
            TRAIN_API_URL,
            params={"trainNo": train_no},
            headers={"user-agent": "Mozilla/5.0"},
            timeout=10
        )
        data = r.json()
        if not data.get("success"):
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
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_ids[chat_id],
                text=base_text,
                parse_mode="Markdown"
            )

        # ===== START ANIMATION LOOP =====
        asyncio.create_task(animate_message(context, chat_id, base_text))

    except Exception as e:
        logger.error(e)

# ================= ANIMATION =================
async def animate_message(context, chat_id, base_text):
    frames = [
        ("📍", "⬅️ .", "➡️"),
        ("📍➤", "⬅️ . .", "➡️➡️"),
        ("📍➤📍", "⬅️ . . .", "➡️➡️➡️")
    ]

    while True:
        for c, p, n in frames:
            animated = (
                base_text
                .replace("📍 *Current Station*", f"{c} *Current Station*")
                .replace("⬅️ *Previous Station*", f"{p} *Previous Station*")
                .replace("➡️ *Next Station*", f"{n} *Next Station*")
            )

            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_ids[chat_id],
                    text=animated,
                    parse_mode="Markdown"
                )
            except:
                return

            await asyncio.sleep(1)

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addtrain", add_train))
    app.add_handler(CommandHandler("removetrain", remove_train))
    app.run_polling()

if __name__ == "__main__":
    main()
