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

# --- LIMIT SETTINGS (ဒီမှာ ပြင်ပါ) ---
COOLDOWN_SECONDS = 120  # တစ်ပုဒ်နဲ့ တစ်ပုဒ်ကြား စောင့်ရမည့်အချိန် (၂ မိနစ်)
DAILY_LIMIT = 10        # တစ်ရက်ကို ကြည့်ခွင့်ပြုမည့် အကန့်အသတ် (၁၀ ပုဒ်)

# --- Database Connection ---
try:
    client = pymongo.MongoClient(MONGO_URL)
    db = client['movie_bot_db']
    collection = db['movies']
    delete_queue = db['delete_queue']
    user_stats = db['user_stats'] 
    print("MongoDB Connected Successfully!")
except Exception as e:
    print(f"MongoDB Connection Error: {e}")

bot = telebot.TeleBot(API_TOKEN)

# ==========================================
# WEB SERVER & AUTO DELETE WORKER
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "Bot is running with Daily Limit & Cooldown!"

def run_http():
    app.run(host='0.0.0.0', port=8000)

def auto_delete_worker():
    while True:
        try:
            current_time = time.time()
            expired_messages = delete_queue.find({"delete_time": {"$lte": current_time}})
            
            for msg in expired_messages:
                try:
                    bot.delete_message(msg['chat_id'], msg['message_id'])
                except:
                    pass
                delete_queue.delete_one({'_id': msg['_id']})
                
            time.sleep(60)
        except:
            time.sleep(5)

def keep_alive():
    Thread(target=run_http).start()
    Thread(target=auto_delete_worker).start()
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
    if message.text.startswith('/'):
        if message.text == '/start':
             bot.reply_to(message, f"ဇာတ်ကားများ download ပြုလုပ်ရန် Movie ID ရိုက်ထည့်ပါ")
        return

    user_id = message.from_user.id

    if not is_subscribed(user_id):
        markup = types.InlineKeyboardMarkup()
        btn = types.InlineKeyboardButton("Movie Store Member ဝင်ရန်", url=CHANNEL_2_LINK)
        markup.add(btn)
        bot.reply_to(message, "⚠️ မိတ်ဆွေသည် Movie Channel ကို Join မထားရသေးပါ။\nအောက်က Link ကိုနှိပ်ပြီး Member အရင်ဝင်းပေးပါ။", reply_markup=markup)
        return

    # --- LIMIT CHECK LOGIC ---
    current_time = time.time()
    user_data = user_stats.find_one({'_id': user_id})

    # Default Data (User အသစ်ဆိုရင်)
    daily_count = 0
    reset_time = current_time + 86400 # နောက် ၂၄ နာရီနေမှ Reset မယ်
    last_request = 0

    if user_data:
        reset_time = user_data.get('reset_time', current_time + 86400)
        daily_count = user_data.get('daily_count', 0)
        last_request = user_data.get('last_request_time', 0)

        # 1. Check if 24 hours passed (Reset Limit)
        if current_time > reset_time:
            daily_count = 0
            reset_time = current_time + 86400 # Reset time ကို အသစ်ပြန်သတ်မှတ်
            # Database မှာ ချက်ချင်း Reset လုပ်ထားလိုက်မယ်
            user_stats.update_one({'_id': user_id}, {'$set': {'daily_count': 0, 'reset_time': reset_time}})

        # 2. Check Daily Limit (10 Files Max)
        if daily_count >= DAILY_LIMIT:
            bot.reply_to(message, f"🚫 ဒီနေ့အတွက် {DAILY_LIMIT} ပုဒ် ပြည့်သွားပါပြီ။\n(၂၄ နာရီပြည့်မှ ပြန်လည် Download ပြုလုပ်နိုင်ပါမည်)")
            return

        # 3. Check Cooldown (3 Minutes Wait)
        time_diff = current_time - last_request
        if time_diff < COOLDOWN_SECONDS:
            wait_time = int(COOLDOWN_SECONDS - time_diff)
            bot.reply_to(message, f"⏳ ခဏစောင့်ပါ။ နောက်ထပ် {wait_time} စက္ကန့်နေမှ နောက်တစ်ကား တောင်းလို့ရပါမယ်။")
            return

    # --- Find Movie ---
    custom_id = message.text.strip()
    movie_data = collection.find_one({'_id': custom_id})
    
    if movie_data:
        real_msg_id = movie_data['msg_id']
        waiting = bot.reply_to(message, f"🔍 Finding movie... ({daily_count + 1}/{DAILY_LIMIT})")
        
        try:
            # Movie ပို့မယ်
            sent_msg = bot.copy_message(chat_id=user_id, from_chat_id=CHANNEL_3_ID, message_id=real_msg_id)
            bot.delete_message(chat_id=user_id, message_id=waiting.message_id)
            
            # --- SUCCESS UPDATE STATS ---
            # ပို့ပြီးမှ Count ကို တိုးမယ် (ID မှားရင် Count မတိုးဘူး)
            user_stats.update_one(
                {'_id': user_id}, 
                {
                    '$set': {
                        'last_request_time': current_time, # Cooldown အတွက်
                        'reset_time': reset_time           # Reset Time မပျောက်အောင်
                    },
                    '$inc': {'daily_count': 1}             # အရေအတွက် ၁ တိုးမယ်
                }, 
                upsert=True
            )
            
            # Auto Delete
            delete_time = time.time() + 86400 
            delete_queue.insert_one({
                'chat_id': user_id,
                'message_id': sent_msg.message_id,
                'delete_time': delete_time
            })
            
        except Exception as e:
            bot.reply_to(message, "❌ File ပို့မရပါ (Database ပြတ်တောက်သွားခြင်း ဖြစ်နိုင်သည်)")
            print(e)
    else:
        # ID မှားရင် Count မတိုးဘဲ Error ပဲပြမယ်
        bot.reply_to(message, f"❌ ID '{custom_id}' နှင့် Movie ရှာမတွေ့ပါ။ ID မှန်ကန်ကြောင်း ပြန်စစ်ပါ (သို့) Admin မှ မထည့်ရသေးခြင်း ဖြစ်နိုင်ပါသည်။")

# --- Main Execution ---
if __name__ == "__main__":
    keep_alive()
    print("Bot started with Daily Limit (10) & Cooldown (3m)...")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"Bot crashed: {e}")
            time.sleep(5)
