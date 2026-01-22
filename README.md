🚆 Telegram Train Live Status Bot

A Telegram bot built with Python that provides real-time Indian train tracking using live public data.
Users can add a train number and receive automatic updates whenever the train reaches a new station.

✨ Features

📍 Current station with actual arrival time

⏱️ Delay calculation (shown in hours & minutes)

🕒 Scheduled vs Actual timings (12-hour AM/PM format)

🚉 Previous, Current & Next station details

🎞️ Animated text updates (continuous, smooth animations)

🔄 Auto updates when train crosses a station

🧹 Remove tracking anytime

☁️ Ready for Render deployment

🤖 Bot Commands
Command	Description
/start	Greet user & show help
/status	Check bot status
/addtrain <train_no>	Start tracking a train
/removetrain	Stop tracking


🛠️ Tech Stack

Python 3.12

python-telegram-bot v21+

WhereIsMyTrain public API

Render (Cloud Hosting)

📂 Project Structure
Train-Telegram-Bot/
│
├── bot.py
├── requirements.txt
├── .env.example
├── README.md



⚙️ Environment Variables

Create a .env file:

BOT_TOKEN=your_telegram_bot_token

🚀 Run Locally
pip install -r requirements.txt
python bot.py

☁️ Deploy on Render

Service type: Background Worker

Build command:

pip install -r requirements.txt


Start command:

python bot.py

⚠️ Disclaimer

This project uses publicly accessible train status data for educational purposes.
It is not affiliated with IRCTC or Indian Railways.

🙌 Author

Roshan Kumar
Made with ❤️ for Indian Rail commuters 🇮🇳
