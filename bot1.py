import os
import asyncio
import logging
from datetime import datetime
import json
from datetime import datetime, timezone, timedelta
import requests
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# ================= ENV =================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TRAIN_API_URL = os.getenv("TRAIN_API_URL")
PORT = int(os.environ.get("PORT", 8443))  # Render will provide this
WEBHOOK_URL = os.getenv("WEBHOOK_URL")    # e.g., https://your-app.onrender.com
IST = timezone(timedelta(hours=5, minutes=30))

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("TRAIN_BOT")

# ================= GLOBALS =================
active_trains = {}       # chat_id -> train_no
tasks = {}               # chat_id -> asyncio task
message_ids = {}         # chat_id -> message_id
last_station_code = {}   # chat_id -> last station code

# ================= UTILS =================
def fmt_time(ts):
    if not ts:
        return "N/A"
    return datetime.fromtimestamp(ts, IST).strftime("%I:%M %p")

def delay_from_secs(sec):
    if not sec or sec <= 0:
        return "On Time"
    m = sec // 60
    h = m // 60
    m = m % 60
    return f"{h} hour {m} minute late" if h else f"{m} minute late"

def get_context(info):
    pos = info.get("currentPosition", {})
    code = pos.get("stationCode")
    prev = cur = nxt = None
    route = info.get("route", [])

    for i, s in enumerate(route):
        if s.get("stationCode") == code:
            cur = s
            prev = route[i - 1] if i > 0 else None
            nxt = route[i + 1] if i < len(route) - 1 else None
            break
    return cur, prev, nxt

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "there"
    await update.message.reply_text(
        f"👋 *Hello {name}!*\n\n"
        "🚆 *Train Live Bot*\n\n"
        "▶️ */addtrain <00000>*\n"
        "📊 */status*\n"
        "🛑 */removetrain*\n\n"
        "    *Made By Roshan ❤️️*\n",
        parse_mode="Markdown"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    train = active_trains.get(update.effective_chat.id)
    await update.message.reply_text(
        f"✅ Tracking *{train}*" if train else "❌ No active train",
        parse_mode="Markdown"
    )

async def add_train(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Usage: /addtrain 12303")
        return

    train = context.args[0]
    active_trains[chat_id] = train

    if chat_id in tasks:
        tasks[chat_id].cancel()
    tasks[chat_id] = asyncio.create_task(track_train(chat_id, context))

    msg = await update.message.reply_text(f"🚆 Tracking Train *{train}*", parse_mode="Markdown")
    message_ids[chat_id] = msg.message_id

async def remove_train(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    active_trains.pop(cid, None)
    last_station_code.pop(cid, None)

    if cid in tasks:
        tasks[cid].cancel()
        tasks.pop(cid)

    message_ids.pop(cid, None)
    await update.message.reply_text("🗑️ Tracking stopped")

# ================= TRACK LOOP =================
async def track_train(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    last_text = None
    while True:
        try:
            train = active_trains.get(chat_id)
            if not train:
                return

            r = requests.get(TRAIN_API_URL, params={"trainNo": train}, timeout=10)
            json_data = r.json()
            if not json_data.get("success"):
                await asyncio.sleep(15)
                continue

            data = json_data.get("data", {})
            cur, prev, nxt = get_context(data)
            cur_code = data.get("currentPosition", {}).get("stationCode") if data.get("currentPosition") else None
            notify = last_station_code.get(chat_id) != cur_code
            last_station_code[chat_id] = cur_code

            platform = "N/A"
            if cur_code:
                for s in data.get("route", []):
                    if s.get("stationCode") == cur_code:
                        platform = s.get("platformNumber", "N/A")
                        break

            current_loc_name = cur.get("station_name", "Unknown") if cur else "Unknown"
            dist = round(data.get("currentPosition", {}).get("distanceFromOriginKm", 0), 1)
            lastDist = round(data.get("currentPosition", {}).get("distanceFromLastStationKm", 0), 1)

            text = f"🚆 Train *{train}*\n"
            text += f"📍 Current Station: *{current_loc_name}*\n"
            text += f"📏Total Distance Covered: *{dist} km*\n"
            text += f"📏Last Distance Covered From Station: *{lastDist} km*\n\n"

            if prev:
                text += (
                    "⬅️ Previous Station\n"
                    f"🏁 {prev.get('station_name', 'N/A')}\n"
                    f"🚉 Platform: {prev.get('platformNumber', 'N/A')}\n"
                    f"🕒 Chart Timing: {fmt_time(prev.get('scheduledArrivalTime'))}\n"
                    f"🕓 Actual Arrived: {fmt_time(prev.get('actualArrivalTime'))}\n"
                    f"⏱️ Delay: {delay_from_secs(prev.get('scheduledDepartureDelaySecs'))}\n\n"
                )

            if nxt:
                text += (
                    "➡️ Next Station\n"
                    f"🚉 {nxt.get('station_name', 'N/A')}\n"
                    f"🚉 Platform: {nxt.get('platformNumber', 'N/A')}\n"
                    f"🕒 Chart Timing: {fmt_time(nxt.get('scheduledArrivalTime'))}\n"
                    f"🕓 Expected Timing: {fmt_time(nxt.get('actualArrivalTime'))}\n"
                    f"⏱️ Delay: {delay_from_secs(nxt.get('scheduledDepartureDelaySecs'))}\n"
                )

            # Send or edit full message
            if chat_id in message_ids:
                if text != last_text:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_ids[chat_id],
                        text=text,
                        parse_mode="Markdown"
                    )
                    last_text = text
            else:
                msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="Markdown"
                )
                message_ids[chat_id] = msg.message_id
                last_text = text

            await asyncio.sleep(4)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Tracking error")
            await asyncio.sleep(20)

# ================= WEBHOOK HANDLER =================
async def webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        if update.message.text.startswith("/"):
            return  # command handled by command handlers
        else:
            await update.message.reply_text("Send /addtrain <train_no> to track a train")

# ================= MAIN =================
def main():
    logger.info("🚀 Bot Started (Webhook Mode)")
    app = Application.builder().token(BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("addtrain", add_train))
    app.add_handler(CommandHandler("removetrain", remove_train))

    # Webhook for other messages
    app.add_handler(MessageHandler(filters.ALL, webhook))

    # Run webhook on Render
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=f"{WEBHOOK_URL}/webhook"
    )

if __name__ == "__main__":
    main()
