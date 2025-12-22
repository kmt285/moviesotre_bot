import telebot
from telebot import types
import pymongo
import os
import re
from flask import Flask
from threading import Thread
import time

# --- Configuration ---
API_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URL = os.getenv('MONGO_URL')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
CHANNEL_2_ID = int(os.getenv('CHANNEL_2_ID'))
CHANNEL_2_LINK = os.getenv('CHANNEL_2_LINK')
CHANNEL_3_ID = int(os.getenv('CHANNEL_3_ID'))

# --- Database Connection ---
try:
    client = pymongo.MongoClient(MONGO_URL)
    db = client['movie_bot_db']
    collection = db['movies']
    print("MongoDB Connected Successfully!")
except Exception as e:
    print(f"MongoDB Connection Error: {e}")

bot = telebot.TeleBot(API_TOKEN)

# ==========================================
# WEB SERVER SECTION (For Koyeb Health Check)
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "I am alive! Bot is running."

def run_http():
    # 0.0.0.0 နဲ့ Port 8000 မှာ မဖြစ်မနေ run ရမည်
    app.run(host='0.0.0.0', port=8000)

def keep_alive():
    t = Thread(target=run_http)
    t.start()
# ==========================================

# --- Check Member Function ---
def is_subscribed(user_id):
    try:
        status = bot.get_chat_member(CHANNEL_2_ID, user_id).status
        if status in ['creator', 'administrator', 'member']:
            return True
        return False
    except:
        return False

# --- Admin Section ---
@bot.message_handler(content_types=['video', 'document'], func=lambda m: m.from_user.id == ADMIN_ID)
def handle_admin_forward(message):
    caption = message.caption if message.caption else ""
    # 16042 သို့မဟုတ် 16042- စသဖြင့် ရှာမယ်
    match = re.search(r'(\d+)', caption)
    
    if match:
        custom_id = match.group(1)
        real_msg_id = message.forward_from_message_id
        
        if not real_msg_id:
             bot.reply_to(message, "⚠️ Channel 3 ထဲကနေ Forward လုပ်ပေးမှ အဆင်ပြေပါမယ်။")
             return

        data = {
            '_id': custom_id,
            'msg_id': real_msg_id,
            'file_name': caption[:50]
        }
        collection.update_one({'_id': custom_id}, {'$set': data}, upsert=True)
        bot.reply_to(message, f"✅ Saved!\nCustom ID: {custom_id}")
    else:
        bot.reply_to(message, "⚠️ ID နံပါတ် မတွေ့ပါ။")

# --- User Section ---
@bot.message_handler(func=lambda message: True)
def handle_user_request(message):
    # Start command ဆိုရင် ဘာမှဆက်မလုပ်ဘူး
    if message.text.startswith('/'):
        if message.text == '/start':
             bot.reply_to(message, "Movie ID ရိုက်ထည့်ပါ (Channel Member ဖြစ်မှ ကြည့်ရပါမည်)")
        return

    user_id = message.from_user.id

    if not is_subscribed(user_id):
        markup = types.InlineKeyboardMarkup()
        btn = types.InlineKeyboardButton("Join Movie Channel", url=CHANNEL_2_LINK)
        markup.add(btn)
        bot.reply_to(message, "Channel ကို Join ပေးပါခင်ဗျာ။", reply_markup=markup)
        return

    custom_id = message.text.strip()
    movie_data = collection.find_one({'_id': custom_id})
    
    if movie_data:
        real_msg_id = movie_data['msg_id']
        waiting = bot.reply_to(message, "🔍 Finding movie...")
        try:
            bot.copy_message(chat_id=user_id, from_chat_id=CHANNEL_3_ID, message_id=real_msg_id)
            bot.delete_message(chat_id=user_id, message_id=waiting.message_id)
        except Exception as e:
            bot.reply_to(message, "❌ Error sending file.")
            print(e)
    else:
        bot.reply_to(message, f"❌ ID '{custom_id}' မတွေ့ပါ။")

# --- Main Execution ---
if __name__ == "__main__":
    # 1. Web Server ကို အရင်ဖွင့်မယ်
    keep_alive()
    
    # 2. ပြီးမှ Bot ကို run မယ် (Bot ပိတ်သွားရင် ပြန် run အောင် loop ခံထားမယ်)
    print("Bot started...")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"Bot crashed: {e}")
            time.sleep(5) # 5 စက္ကန့်နားပြီး ပြန် run မယ်
