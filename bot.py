import telebot
from telebot import types
import pymongo
import os
import re
from flask import Flask
from threading import Thread
import time
from datetime import datetime, timedelta

# --- Configuration ---
API_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URL = os.getenv('MONGO_URL')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

# Channel 2 = Public Poster Channel (User မဖြစ်မနေ Join ရမည်)
CHANNEL_2_ID = int(os.getenv('CHANNEL_2_ID'))
CHANNEL_2_LINK = os.getenv('CHANNEL_2_LINK')

# Channel 3 = Database Channel (Video အစစ်တင်မည့်နေရာ)
CHANNEL_3_ID = int(os.getenv('CHANNEL_3_ID'))

# --- SETTINGS ---
# Free User အတွက် Limit
COOLDOWN_SECONDS = 60  # ၁ မိနစ်
DAILY_LIMIT = 5        # တစ်ရက် ၅ ပုဒ်

# Delete Times (စက္ကန့်ဖြင့်)
FREE_DELETE_TIME = 5 * 3600   # ၅ နာရီ (18000 seconds)
VIP_DELETE_TIME = 24 * 3600   # ၂၄ နာရီ (86400 seconds)

CAPTION_SUFFIX = " $ ဆက်သွယ်ရန် $ admin @tec102024" 

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
# (1) BROADCAST SECTION & VIP COMMANDS
# ==========================================
@bot.message_handler(commands=['broadcast'])
def handle_broadcast(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return

    if message.reply_to_message:
        msg_id_to_copy = message.reply_to_message.message_id
        Thread(target=start_broadcast_process, args=(message, 'copy', msg_id_to_copy)).start()
    else:
        msg_text = message.text.replace('/broadcast', '').strip()
        if not msg_text:
            bot.reply_to(message, "⚠️ Use: /broadcast [Message] or Reply to a message.")
            return
        Thread(target=start_broadcast_process, args=(message, 'text', msg_text)).start()

def start_broadcast_process(message, mode, content):
    users = list(user_stats.find({}, {'_id': 1}))
    status_msg = bot.reply_to(message, f"📢 Broadcast started... ({len(users)} users)")
    sent, blocked = 0, 0
    for user in users:
        try:
            if mode == 'copy':
                bot.copy_message(chat_id=user['_id'], from_chat_id=message.chat.id, message_id=content)
            else:
                bot.send_message(user['_id'], content)
            sent += 1
            time.sleep(0.05)
        except:
            blocked += 1
    bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, 
                          text=f"✅ Done!\nSent: {sent}\nBlocked: {blocked}")

# --- VIP ADD COMMAND ---
@bot.message_handler(commands=['addvip'])
def add_vip_user(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    try:
        parts = message.text.split() # /addvip 12345 30
        uid = int(parts[1])
        days = int(parts[2])
        expiry = time.time() + (days * 86400)
        user_stats.update_one({'_id': uid}, {'$set': {'vip_expiry': expiry}}, upsert=True)
        bot.reply_to(message, f"✅ User {uid} is now VIP for {days} days.")
    except:
        bot.reply_to(message, "⚠️ Usage: /addvip [UserID] [Days]")

# ==========================================
# WEB SERVER & WORKERS
# ==========================================
app = Flask('')
@app.route('/')
def home(): return "Bot Running with Protected Content Logic"

def run_http(): app.run(host='0.0.0.0', port=8000)

def auto_delete_worker():
    while True:
        try:
            now = time.time()
            # အချိန်ပြည့်သွားသော Message များကို ရှာပြီးဖျက်မည်
            expired = delete_queue.find({"delete_time": {"$lte": now}})
            for msg in expired:
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
# HELPER FUNCTIONS
# ==========================================
def is_subscribed(user_id):
    """Channel 2 Member ဖြစ်မဖြစ် စစ်ဆေးခြင်း"""
    try:
        status = bot.get_chat_member(CHANNEL_2_ID, user_id).status
        return status in ['creator', 'administrator', 'member']
    except:
        return False

def check_vip_status(user_id):
    """VIP ဟုတ်မဟုတ်နှင့် သက်တမ်းစစ်ဆေးခြင်း"""
    user = user_stats.find_one({'_id': user_id})
    if user and 'vip_expiry' in user:
        if user['vip_expiry'] > time.time():
            return True
    return False

# ==========================================
# ADMIN & USER HANDLERS
# ==========================================
@bot.message_handler(content_types=['video', 'document'], func=lambda m: m.from_user.id == ADMIN_ID)
def handle_admin_save(message):
    caption = message.caption if message.caption else ""
    match = re.search(r'(\d+)', caption)
    if match:
        custom_id = match.group(1)
        # Channel 3 မှ Forward လုပ်မှသာ အလုပ်လုပ်မည်
        if not message.forward_from_message_id:
            bot.reply_to(message, "⚠️ Channel 3 မှ Forward လုပ်ပေးပါ။")
            return
            
        data = {
            '_id': custom_id,
            'msg_id': message.forward_from_message_id,
            'file_name': caption
        }
        collection.update_one({'_id': custom_id}, {'$set': data}, upsert=True)
        bot.reply_to(message, f"✅ Saved ID: {custom_id}")
    else:
        bot.reply_to(message, "⚠️ No ID found in caption.")

@bot.message_handler(func=lambda message: True)
def handle_user_request(message):
    # 1. Clean User Chat
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass

    user_id = message.from_user.id
    is_vip = check_vip_status(user_id)

    # 2. START MESSAGE
    if message.text == '/start':
        user_stats.update_one({'_id': user_id}, {'$set': {'active': True}}, upsert=True)
        status_txt = "🌟 VIP Member" if is_vip else "👤 Free Member"
        bot.send_message(message.chat.id, f"🔰 **Movie Downloader** 🔰\n\nStatus: {status_txt}\n\nPlease enter Movie ID:", parse_mode="Markdown")
        return

    # 3. FORCE SUBSCRIBE CHECK (VIP ရော Free ရော စစ်မည်)
    if not is_subscribed(user_id):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Join Channel First", url=CHANNEL_2_LINK))
        bot.send_message(message.chat.id, "⚠️ Bot ကိုသုံးရန် အောက်ပါ Channel ကို Join ထားရပါမည်။", reply_markup=markup)
        return

    # 4. LIMIT CHECK (Free Only)
    current_time = time.time()
    user_data = user_stats.find_one({'_id': user_id})
    daily_count = user_data.get('daily_count', 0) if user_data else 0
    reset_time = user_data.get('reset_time', current_time + 86400) if user_data else current_time + 86400
    
    if not is_vip:
        # Reset Limit if new day
        if current_time > reset_time:
            daily_count = 0
            reset_time = current_time + 86400
            user_stats.update_one({'_id': user_id}, {'$set': {'daily_count': 0, 'reset_time': reset_time}})

        if daily_count >= DAILY_LIMIT:
            bot.send_message(message.chat.id, "❌ Daily Limit Reached. Buy VIP for Unlimited.")
            return

        # Cooldown Check
        last_req = user_data.get('last_request_time', 0)
        if (current_time - last_req) < COOLDOWN_SECONDS:
            bot.send_message(message.chat.id, f"⏳ Please wait {int(COOLDOWN_SECONDS - (current_time - last_req))}s.")
            return

    # 5. SEND MOVIE LOGIC
    custom_id = message.text.strip()
    movie_data = collection.find_one({'_id': custom_id})

    if movie_data:
        real_msg_id = movie_data['msg_id']
        caption = f"{movie_data.get('file_name', '')}\n{CAPTION_SUFFIX}"
        
        # --- VIP VS FREE CONFIGURATION ---
        if is_vip:
            protect = False           # Save ရမယ်
            del_delay = VIP_DELETE_TIME # 24 နာရီ
            wait_msg = "💎 VIP Request: Sending File (Can Save)..."
        else:
            protect = True            # Save မရ
            del_delay = FREE_DELETE_TIME # 5 နာရီ
            wait_msg = f"👤 Free Request: Sending Protected File ({daily_count+1}/{DAILY_LIMIT})..."

        status_msg = bot.send_message(message.chat.id, wait_msg)

        try:
            sent_msg = bot.copy_message(
                chat_id=user_id,
                from_chat_id=CHANNEL_3_ID,
                message_id=real_msg_id,
                caption=caption,
                protect_content=protect  # ဒီနေရာမှာ Save ရ/မရ ခွဲခြားသည်
            )
            
            # Delete Status Message
            bot.delete_message(user_id, status_msg.message_id)

            # Update Count for Free User
            if not is_vip:
                user_stats.update_one(
                    {'_id': user_id}, 
                    {
                        '$set': {'last_request_time': current_time, 'reset_time': reset_time},
                        '$inc': {'daily_count': 1}
                    }, 
                    upsert=True
                )

            # Schedule Auto Delete
            delete_time = time.time() + del_delay
            delete_queue.insert_one({
                'chat_id': user_id,
                'message_id': sent_msg.message_id,
                'delete_time': delete_time
            })
            
            # Info Message
            info_txt = f"⏳ Auto-delete in {int(del_delay/3600)} hours."
            if not is_vip:
                info_txt += "\n🚫 Save/Forward Restricted (Free Mode)."
            
            # ဒီ Info စာကိုလည်း အချိန်တန်ရင် ဖျက်ချင်ရင် Queue ထဲထည့်လို့ရသည် (Optional)
            info_msg = bot.send_message(message.chat.id, info_txt)
            delete_queue.insert_one({
                'chat_id': user_id,
                'message_id': info_msg.message_id,
                'delete_time': delete_time
            })

        except Exception as e:
            try: bot.delete_message(user_id, status_msg.message_id)
            except: pass
            bot.send_message(message.chat.id, "❌ Error: Movie not found or deleted from database.")
    else:
        bot.send_message(message.chat.id, "❌ Invalid ID.")

if __name__ == "__main__":
    keep_alive()
    print("Bot Started...")
    bot.infinity_polling()
