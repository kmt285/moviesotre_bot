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

# Channel 2 = Public Poster Channel (User Join ရမည်)
CHANNEL_2_ID = int(os.getenv('CHANNEL_2_ID'))
CHANNEL_2_LINK = os.getenv('CHANNEL_2_LINK')

# Channel 3 = Database Channel (Video သိမ်းမည့်နေရာ)
CHANNEL_3_ID = int(os.getenv('CHANNEL_3_ID'))

# --- SETTINGS ---
COOLDOWN_SECONDS = 60   # Free User စောင့်ချိန် (၁ မိနစ်)
DAILY_LIMIT = 5         # Free User တစ်ရက် (၅) ပုဒ်
FREE_DELETE_TIME = 18000 # Free User ဖျက်ချိန် (၅ နာရီ = 18000s)
VIP_DELETE_TIME = 86400  # VIP User ဖျက်ချိန် (၂၄ နာရီ = 86400s)
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
        # Bot သည် Channel 2 တွင် Admin ဖြစ်ရပါမည်
        member = bot.get_chat_member(CHANNEL_2_ID, user_id)
        if member.status in ['creator', 'administrator', 'member']:
            return True
        return False
    except Exception as e:
        # Error တက်ရင် Bot ကို Channel Admin ပေးထားလား ပြန်စစ်ပါ
        print(f"Sub Check Error: {e}")
        return False

# ==========================================
# (2) ADMIN COMMANDS (/broadcast, /addvip)
# ==========================================

@bot.message_handler(commands=['addvip'])
def add_vip(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        # Format: /addvip 123456 30
        parts = message.text.split()
        uid = int(parts[1])
        days = int(parts[2])
        expiry = time.time() + (days * 86400)
        
        user_stats.update_one({'_id': uid}, {'$set': {'vip_expiry': expiry}}, upsert=True)
        bot.reply_to(message, f"✅ User `{uid}` is now VIP for {days} days.", parse_mode="Markdown")
    except:
        bot.reply_to(message, "⚠️ Error: `/addvip [User_ID] [Days]`")

@bot.message_handler(commands=['broadcast'])
def broadcast(message):
    if message.from_user.id != ADMIN_ID: return
    
    msg = bot.reply_to(message, "🚀 Broadcasting...")
    users = user_stats.find({}, {'_id': 1})
    count = 0
    
    # Broadcast Loop
    for user in users:
        try:
            if message.reply_to_message:
                bot.copy_message(user['_id'], message.chat.id, message.reply_to_message.message_id)
            else:
                text = message.text.replace('/broadcast', '')
                if text.strip(): bot.send_message(user['_id'], text)
            count += 1
            time.sleep(0.05)
        except:
            pass
            
    bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"✅ Sent to {count} users.")

# ==========================================
# (3) SAVE MOVIE (Admin Only)
# ==========================================
@bot.message_handler(content_types=['video', 'document'], func=lambda m: m.from_user.id == ADMIN_ID)
def save_movie(message):
    # Channel 3 မှ Forward လုပ်မှသာ အလုပ်လုပ်မည်
    if not message.forward_from_message_id:
        bot.reply_to(message, "⚠️ Channel 3 (Database) မှ Forward လုပ်ပေးပါ။")
        return

    # Caption ထဲက ID ရှာမည်
    caption = message.caption if message.caption else ""
    # ဂဏန်းသက်သက် ID ကိုရှာမည် (ဥပမာ: 101)
    match = re.search(r'^\s*(\d+)', caption) 
    
    if match:
        custom_id = match.group(1)
        data = {
            '_id': custom_id,
            'msg_id': message.forward_from_message_id,
            'file_name': caption # မူရင်း Caption အကုန်သိမ်းမည်
        }
        collection.update_one({'_id': custom_id}, {'$set': data}, upsert=True)
        bot.reply_to(message, f"✅ Movie Saved!\nID: `{custom_id}`", parse_mode="Markdown")
    else:
        bot.reply_to(message, "⚠️ Caption တွင် ID နံပါတ် မတွေ့ပါ။ (ဥပမာ: `1001 My Movie`)", parse_mode="Markdown")

# ==========================================
# (4) USER REQUEST HANDLER (Main Logic)
# ==========================================
@bot.message_handler(func=lambda m: True)
def handle_message(message):
    user_id = message.from_user.id

    # 1. Clean User Message (စာပို့တာနဲ့ ချက်ချင်းဖျက်မယ်)
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass

    # 2. START COMMAND
    if message.text == '/start':
        vip_status = is_vip(user_id)
        status_text = "🌟 VIP Member" if vip_status else "👤 Free Member"
        
        # User Data ထည့်မည်
        user_stats.update_one({'_id': user_id}, {'$set': {'active': True}}, upsert=True)
        
        welcome_msg = (
            f"🔰 **Movie Downloader Bot** 🔰\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"💎 Status: {status_text}\n\n"
            f"🎬 ကြည့်ရှုလိုသော ဇာတ်ကား ID ကို ရိုက်ထည့်ပါ..."
        )
        bot.send_message(message.chat.id, welcome_msg, parse_mode="Markdown")
        return

    # 3. FORCE SUBSCRIBE CHECK (အရေးကြီးသည်)
    if not check_subscription(user_id):
        markup = types.InlineKeyboardMarkup()
        btn = types.InlineKeyboardButton("Join Movie Channel", url=CHANNEL_2_LINK)
        markup.add(btn)
        bot.send_message(message.chat.id, "⚠️ Bot ကိုအသုံးပြုရန် Channel ကို အရင် Join ပေးပါ။", reply_markup=markup)
        return

    # 4. PROCESS MOVIE ID
    movie_id = message.text.strip()
    movie = collection.find_one({'_id': movie_id})

    if not movie:
        bot.send_message(message.chat.id, f"❌ ID `{movie_id}` မရှိပါ။ ID မှန်ကန်အောင် ပြန်စစ်ပါ။", parse_mode="Markdown")
        return

    # 5. VIP vs FREE LOGIC
    user_vip = is_vip(user_id)
    current_time = time.time()
    
    # Defaults for Free User
    protect_content = True          # Save မရ
    delete_delay = FREE_DELETE_TIME # 5 နာရီ
    limit_check = True              # Limit စစ်မည်
    
    if user_vip:
        protect_content = False        # Save ရ (Premium)
        delete_delay = VIP_DELETE_TIME # 24 နာရီ
        limit_check = False            # Limit မစစ် (Unlimited)

    # --- Limit Checking for Free Users ---
    if limit_check:
        user_data = user_stats.find_one({'_id': user_id})
        daily_count = user_data.get('daily_count', 0) if user_data else 0
        reset_time = user_data.get('reset_time', current_time + 86400) if user_data else current_time + 86400
        last_req = user_data.get('last_request_time', 0)

        # Reset Day
        if current_time > reset_time:
            daily_count = 0
            reset_time = current_time + 86400
            user_stats.update_one({'_id': user_id}, {'$set': {'daily_count': 0, 'reset_time': reset_time}})

        # Check Count
        if daily_count >= DAILY_LIMIT:
            bot.send_message(message.chat.id, "❌ Daily Limit ပြည့်သွားပါပြီ။ Unlimited ရရန် VIP ဝယ်ယူပါ။")
            return
        
        # Check Cooldown
        if (current_time - last_req) < COOLDOWN_SECONDS:
            wait = int(COOLDOWN_SECONDS - (current_time - last_req))
            bot.send_message(message.chat.id, f"⏳ ခဏစောင့်ပါ... {wait} စက္ကန့်")
            return

    # 6. SENDING THE MOVIE
    wait_msg = bot.send_message(message.chat.id, "🔍 Finding Movie...")
    
    try:
        final_caption = f"{movie.get('file_name', '')}{CAPTION_SUFFIX}"
        
        sent_msg = bot.copy_message(
            chat_id=user_id,
            from_chat_id=CHANNEL_3_ID,
            message_id=movie['msg_id'],
            caption=final_caption,
            protect_content=protect_content  # <--- ဒီနေရာမှာ Save ရ/မရ ခွဲပေးထားသည်
        )

        # Delete "Finding..." message
        bot.delete_message(message.chat.id, wait_msg.message_id)

        # Update Database (Count & Last Request)
        if limit_check:
            user_stats.update_one(
                {'_id': user_id},
                {'$inc': {'daily_count': 1}, '$set': {'last_request_time': current_time, 'reset_time': reset_time}},
                upsert=True
            )

        # Add to Auto Delete Queue
        expire_time = current_time + delete_delay
        delete_queue.insert_one({
            'chat_id': user_id,
            'message_id': sent_msg.message_id,
            'delete_time': expire_time
        })

        # Success Message
        hours = int(delete_delay / 3600)
        status_note = "✅ Save ရပါသည်" if user_vip else "🚫 Save မရပါ (Free Version)"
        bot.send_message(message.chat.id, f"{status_note}\n🗑️ Auto-delete in {hours} hours.")

    except Exception as e:
        bot.delete_message(message.chat.id, wait_msg.message_id)
        bot.send_message(message.chat.id, "❌ Error: ဇာတ်ကား ပို့မရပါ။ (Source Channel တွင် မရှိတော့ခြင်း ဖြစ်နိုင်သည်)")
        print(f"Send Error: {e}")

# ==========================================
# (5) BACKGROUND TASKS (Flask + Auto Delete)
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "Bot is Running!"

def run_http():
    app.run(host='0.0.0.0', port=8000)

def auto_delete_worker():
    while True:
        try:
            now = time.time()
            # အချိန်ကျော်နေသော message များကို ရှာသည်
            expired_msgs = delete_queue.find({"delete_time": {"$lte": now}})
            
            for msg in expired_msgs:
                try:
                    bot.delete_message(msg['chat_id'], msg['message_id'])
                except:
                    pass # Already deleted
                # Database ထဲမှ ဖယ်ထုတ်သည်
                delete_queue.delete_one({'_id': msg['_id']})
            
            time.sleep(60) # ၁ မိနစ် တစ်ခါ စစ်မည်
        except Exception as e:
            print(f"Auto-Delete Error: {e}")
            time.sleep(10)

def keep_alive():
    t1 = Thread(target=run_http)
    t2 = Thread(target=auto_delete_worker)
    t1.start()
    t2.start()

# --- START BOT ---
if __name__ == "__main__":
    keep_alive()
    print("🤖 Bot Started...")
    bot.infinity_polling()
