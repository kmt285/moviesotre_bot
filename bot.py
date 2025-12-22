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
    collection = db['movies']        # Movie ID သိမ်းတဲ့ နေရာ
    delete_queue = db['delete_queue'] # ဖျက်ရမယ့် စာရင်းမှတ်တဲ့ နေရာ (New)
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
    return "I am alive! Bot is running."

def run_http():
    app.run(host='0.0.0.0', port=8000)

# --- Auto Delete Function (New Feature) ---
# ၂၄ နာရီပြည့်တဲ့ စာတွေကို လိုက်ဖျက်မယ့် Function
def auto_delete_worker():
    print("Auto-delete worker started...")
    while True:
        try:
            current_time = time.time()
            # အချိန်ပြည့်ပြီးသော Message များကို Database ထဲ ရှာမယ်
            expired_messages = delete_queue.find({"delete_time": {"$lte": current_time}})
            
            for msg in expired_messages:
                chat_id = msg['chat_id']
                message_id = msg['message_id']
                
                try:
                    # Telegram မှာ လှမ်းဖျက်မယ်
                    bot.delete_message(chat_id, message_id)
                    print(f"Deleted message {message_id} for user {chat_id}")
                except Exception as e:
                    print(f"Failed to delete (User might have blocked bot): {e}")
                
                # ဖျက်ပြီးရင် Database ထဲကပါ ထုတ်လိုက်မယ်
                delete_queue.delete_one({'_id': msg['_id']})
                
            time.sleep(60) # ၁ မိနစ်တစ်ခါ ထစစ်မယ်
        except Exception as e:
            print(f"Auto-delete loop error: {e}")
            time.sleep(5)

def keep_alive():
    # Web Server အတွက် Thread
    t1 = Thread(target=run_http)
    t1.start()
    
    # Auto Delete အတွက် Thread
    t2 = Thread(target=auto_delete_worker)
    t2.start()
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
             bot.reply_to(message, "မင်္ဂလာပါ! Movieများကို download ပြုလုပ်ရန်နှင့် ကြည့်ရှုရန်အတွက် Movie ID နံပါတ်ရိုက်ထည့်ပါ")
        return

    user_id = message.from_user.id

    if not is_subscribed(user_id):
        markup = types.InlineKeyboardMarkup()
        btn = types.InlineKeyboardButton("Member ဝင်ရန် ✅", url=CHANNEL_2_LINK)
        markup.add(btn)
        bot.reply_to(message, "⚠️ မိတ်ဆွေက Movie Store ကို Join မထားပါဘူး။\nအောက်က Link ကိုနှိပ်ပြီး Member အရင်ဝင်ပေးပါ။ ပြီးမှ ID ပြန်ရိုက်ပါ။", reply_markup=markup)
        return

    custom_id = message.text.strip()
    movie_data = collection.find_one({'_id': custom_id})
    
    if movie_data:
        real_msg_id = movie_data['msg_id']
        waiting = bot.reply_to(message, "🔍 Finding movie...")
        
        try:
            # 1. Movie ပို့မယ် (Sent Message ကို ပြန်ဖမ်းမယ်)
            sent_msg = bot.copy_message(chat_id=user_id, from_chat_id=CHANNEL_3_ID, message_id=real_msg_id, protect_content=True)
            
            # 2. "Finding..." စာကို ဖျက်မယ်
            bot.delete_message(chat_id=user_id, message_id=waiting.message_id)
            
            # 3. Auto Delete စာရင်းထဲ ထည့်မယ် (24 နာရီ = 86400 seconds)
            delete_time = time.time() + 60 
            
            delete_queue.insert_one({
                'chat_id': user_id,
                'message_id': sent_msg.message_id,
                'delete_time': delete_time
            })
            
            # User ကို အသိပေးစာ ပို့ချင်ရင် အောက်ကစာကြောင်းကို ဖွင့်ပါ
            # bot.send_message(user_id, "⚠️ ဒီ Movie link သည် ၂၄ နာရီပြည့်ရင် အလိုအလျောက် ပျက်ပါမည်။")
            
        except Exception as e:
            bot.reply_to(message, "❌ Error sending file.")
            print(e)
    else:
        bot.reply_to(message, f"❌ ID '{custom_id}' ရှာမတွေ့ပါ။ ID မှန်မမှန်ပြန်လည်စစ်ဆေးပါ။")

# --- Main Execution ---
if __name__ == "__main__":
    keep_alive()
    print("Bot started with Auto-Delete...")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"Bot crashed: {e}")
            time.sleep(5)

