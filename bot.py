import telebot
from telebot import types
import pymongo
import os
import re
from flask import Flask
from threading import Thread
import time

# --- Configuration (Koyeb Environment Variables) ---
API_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URL = os.getenv('MONGO_URL')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

# Channel IDs
CHANNEL_2_ID = int(os.getenv('CHANNEL_2_ID')) # Poster Channel
CHANNEL_2_LINK = os.getenv('CHANNEL_2_LINK')
CHANNEL_3_ID = int(os.getenv('CHANNEL_3_ID')) # Database Channel

# --- SETTINGS ---
# Free User Settings
FREE_DAILY_LIMIT = 5
FREE_DELETE_TIME = 86400     # ၅ နာရီ
FREE_COOLDOWN = 90           # ၁ မိနစ်

# VIP User Settings
VIP_SAVE_LIMIT = 15          # ၁၀ ပုဒ်အထိ Save ရမယ်
VIP_DELETE_TIME = 86400      # ၂၄ နာရီ
# ၁၀ ပုဒ်ကျော်ရင် Unlimited ဆက်ရမယ် (ဒါပေမဲ့ Save မရတော့ဘူး)

CAPTION_SUFFIX = "\n\n$ ဆက်သွယ်ရန် $ admin @tec102024"

# --- Database Connection ---
try:
    client = pymongo.MongoClient(MONGO_URL)
    db = client['movie_bot_db']
    collection = db['movies']
    delete_queue = db['delete_queue']
    user_stats = db['user_stats']
    print("✅ MongoDB Connected!")
except Exception as e:
    print(f"❌ MongoDB Error: {e}")

bot = telebot.TeleBot(API_TOKEN)

# ==========================================
# (1) HELPER FUNCTIONS
# ==========================================

def is_vip(user_id):
    """VIP ဖြစ်မဖြစ် စစ်ဆေးခြင်း"""
    user = user_stats.find_one({'_id': user_id})
    if user and 'vip_expiry' in user:
        if user['vip_expiry'] > time.time():
            return True
    return False

def check_subscription(user_id):
    """Channel 2 Member ဝင်ထားခြင်း ရှိမရှိ စစ်ဆေးခြင်း"""
    try:
        member = bot.get_chat_member(CHANNEL_2_ID, user_id)
        if member.status in ['creator', 'administrator', 'member']:
            return True
        return False
    except:
        return False

# ==========================================
# (2) ADMIN COMMANDS (Add/Remove VIP)
# ==========================================

@bot.message_handler(commands=['addvip'])
def add_vip(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        # /addvip 123456 30
        parts = message.text.split()
        uid = int(parts[1])
        days = int(parts[2])
        expiry = time.time() + (days * 86400)
        
        user_stats.update_one({'_id': uid}, {'$set': {'vip_expiry': expiry}}, upsert=True)
        bot.reply_to(message, f"✅ User `{uid}` is now VIP for {days} days.", parse_mode="Markdown")
    except:
        bot.reply_to(message, "⚠️ Usage: `/addvip [UserID] [Days]`")

@bot.message_handler(commands=['delvip'])
def delete_vip(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        # /delvip 123456
        parts = message.text.split()
        uid = int(parts[1])
        
        # VIP Expiry ကို ဖျက်ပစ်မည် ($unset)
        user_stats.update_one({'_id': uid}, {'$unset': {'vip_expiry': ""}})
        bot.reply_to(message, f"🗑️ User `{uid}` မှ VIP status ကို ဖယ်ရှားလိုက်ပါပြီ။", parse_mode="Markdown")
    except:
        bot.reply_to(message, "⚠️ Usage: `/delvip [UserID]`")

@bot.message_handler(commands=['broadcast'])
def broadcast(message):
    if message.from_user.id != ADMIN_ID: return
    msg = bot.reply_to(message, "🚀 Broadcasting...")
    users = user_stats.find({}, {'_id': 1})
    count = 0
    for user in users:
        try:
            if message.reply_to_message:
                bot.copy_message(user['_id'], message.chat.id, message.reply_to_message.message_id)
            else:
                text = message.text.replace('/broadcast', '')
                if text.strip(): bot.send_message(user['_id'], text)
            count += 1
            time.sleep(0.05)
        except: pass
    bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"✅ Sent to {count} users.")

# ==========================================
# (3) SAVE MOVIE (Admin Only)
# ==========================================
@bot.message_handler(content_types=['video', 'document'], func=lambda m: m.from_user.id == ADMIN_ID)
def save_movie(message):
    if not message.forward_from_message_id:
        bot.reply_to(message, "⚠️ Channel 3 (Database) မှ Forward လုပ်ပေးပါ။")
        return

    caption = message.caption if message.caption else ""
    match = re.search(r'^\s*(\d+)', caption) 
    
    if match:
        custom_id = match.group(1)
        data = {
            '_id': custom_id,
            'msg_id': message.forward_from_message_id,
            'file_name': caption
        }
        collection.update_one({'_id': custom_id}, {'$set': data}, upsert=True)
        bot.reply_to(message, f"✅ Saved! ID: `{custom_id}`", parse_mode="Markdown")
    else:
        bot.reply_to(message, "⚠️ ID နံပါတ် မတွေ့ပါ။")

# ==========================================
# (4) MAIN LOGIC (VIP vs Free Hybrid)
# ==========================================
@bot.message_handler(func=lambda m: True)
def handle_message(message):
    user_id = message.from_user.id
    #try: bot.delete_message(message.chat.id, message.message_id)
   # except: pass

    # START
    if message.text == '/start':
        vip_status = is_vip(user_id)
        status_text = "🌟 VIP Member" if vip_status else "👤 Free Member"
        user_stats.update_one({'_id': user_id}, {'$set': {'active': True}}, upsert=True)
        
        txt = (f"🔰 **Movie Downloader** 🔰\n"
               f"🆔 `{user_id}`\n💎 Status: {status_text}\n\n"
               f"Join VIP for Unlimited!\n\n"
               f"🎬 Movie ID ရိုက်ထည့်ပါ:")
        bot.send_message(message.chat.id, txt, parse_mode="Markdown")
        return

    # SUBSCRIPTION CHECK
    if not check_subscription(user_id):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Join Channel First", url=CHANNEL_2_LINK))
        bot.send_message(message.chat.id, "⚠️ Channel Join ထားမှ သုံးလို့ရပါမည်။", reply_markup=markup)
        return

    # GET MOVIE DATA
    movie_id = message.text.strip()
    movie = collection.find_one({'_id': movie_id})
    if not movie:
        bot.send_message(message.chat.id, "❌ ID မှားယွင်းနေပါသည်။")
        return

    # --- LOGIC CALCULATION ---
    user_vip = is_vip(user_id)
    current_time = time.time()
    
    # User Stats Fetching
    user_data = user_stats.find_one({'_id': user_id})
    daily_count = user_data.get('daily_count', 0) if user_data else 0
    reset_time = user_data.get('reset_time', current_time + 86400) if user_data else current_time + 86400
    last_req = user_data.get('last_request_time', 0)

    # Daily Reset Logic
    if current_time > reset_time:
        daily_count = 0
        reset_time = current_time + 86400
        user_stats.update_one({'_id': user_id}, {'$set': {'daily_count': 0, 'reset_time': reset_time}})

    # --- DECISION MAKING ---
    if user_vip:
        # === VIP LOGIC ===
        delete_delay = VIP_DELETE_TIME
        
        # ၁၀ ပုဒ်အောက်ဆိုရင် Save ရမယ်
        if daily_count < VIP_SAVE_LIMIT:
            protect_content = False 
            note = f"✅ VIP Privilege: Can Save ({daily_count+1}/{VIP_SAVE_LIMIT})"
        else:
            # ၁၀ ပုဒ်ကျော်ရင် Save မရတော့ဘူး (ဒါပေမဲ့ Unlimited)
            protect_content = True
            note = "⚠️ VIP Note: Daily Save Limit Reached. (View Only Mode)"
            
    else:
        # === FREE LOGIC ===
        if daily_count >= FREE_DAILY_LIMIT:
            bot.send_message(message.chat.id, "❌ Daily Limit ပြည့်သွားပါပြီ။ Unlimited ရရန် VIP ဝယ်ပါ။")
            return
        
        if (current_time - last_req) < FREE_COOLDOWN:
            wait = int(FREE_COOLDOWN - (current_time - last_req))
            bot.send_message(message.chat.id, f"⏳ ခဏစောင့်ပါ... {wait}s")
            return

        protect_content = True  # Free User ဘယ်တော့မှ Save မရ
        delete_delay = FREE_DELETE_TIME
        note = f"👤 Free Mode: Save Restricted ({daily_count+1}/{FREE_DAILY_LIMIT})"

    # --- SENDING ---
    wait_msg = bot.send_message(message.chat.id, "🔍 Finding...")
    try:
        final_caption = f"{movie.get('file_name', '')}{CAPTION_SUFFIX}"
        
        sent_msg = bot.copy_message(
            chat_id=user_id,
            from_chat_id=CHANNEL_3_ID,
            message_id=movie['msg_id'],
            caption=final_caption,
            protect_content=protect_content
        )
        
        bot.delete_message(message.chat.id, wait_msg.message_id)
        bot.send_message(message.chat.id, f"{note}\n🗑️ Auto-delete in {int(delete_delay/86400)} hours.")

        # Update Count (Everyone gets count update)
        user_stats.update_one(
            {'_id': user_id},
            {
                '$inc': {'daily_count': 1}, 
                '$set': {'last_request_time': current_time, 'reset_time': reset_time}
            },
            upsert=True
        )

        # Queue for Auto Delete
        delete_queue.insert_one({
            'chat_id': user_id,
            'message_id': sent_msg.message_id,
            'delete_time': current_time + delete_delay
        })

    except Exception as e:
        bot.delete_message(message.chat.id, wait_msg.message_id)
        bot.send_message(message.chat.id, "❌ Error sending movie.")
        print(f"Error: {e}")

# ==========================================
# (5) BACKGROUND TASKS
# ==========================================
app = Flask('')
@app.route('/')
def home(): return "Bot Running with Hybrid VIP Logic"
def run_http(): app.run(host='0.0.0.0', port=8000)
def auto_delete_worker():
    while True:
        try:
            now = time.time()
            expired = delete_queue.find({"delete_time": {"$lte": now}})
            for msg in expired:
                try: bot.delete_message(msg['chat_id'], msg['message_id'])
                except: pass
                delete_queue.delete_one({'_id': msg['_id']})
            time.sleep(60)
        except: time.sleep(5)

def keep_alive():
    Thread(target=run_http).start()
    Thread(target=auto_delete_worker).start()

if __name__ == "__main__":
    keep_alive()
    print("🤖 Bot Started...")
    bot.infinity_polling()

