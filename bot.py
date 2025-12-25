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
FREE_DAILY_LIMIT = 5
FREE_DELETE_TIME = 86400     # 24 Hours
FREE_COOLDOWN = 120           # 120 Seconds

VIP_SAVE_LIMIT = 15          # 15 Files Save Limit
VIP_DELETE_TIME = 86400      # 24 Hours

CAPTION_SUFFIX = "\n\n🌵admin @tec102024🌵" 

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
# (1) HELPER FUNCTIONS (AUTO UPDATE)
# ==========================================

def get_or_register_user(message):
    """User Data သိမ်းခြင်း + Username Auto Update လုပ်ခြင်း"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name

    user = user_stats.find_one({'_id': user_id})
    
    # User အသစ်ဆိုရင် Create လုပ်မည်
    if not user:
        new_user = {
            '_id': user_id,
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
            'phone_number': None,          # Button နှိပ်မှ ဝင်လာမည်
            'status': 'free',
            'vip_info': {'expiry': None, 'start_date': None},
            'usage': {
                'daily_count': 0, 
                'reset_time': time.time() + 86400, 
                'last_request_time': 0
            }
        }
        user_stats.insert_one(new_user)
        return new_user
    
    # User အဟောင်းဆိုရင် Info Update လုပ်မည်
    else:
        update_data = {}
        if user.get('username') != username: update_data['username'] = username
        if user.get('first_name') != first_name: update_data['first_name'] = first_name
        if user.get('last_name') != last_name: update_data['last_name'] = last_name
            
        if update_data:
            user_stats.update_one({'_id': user_id}, {'$set': update_data})
            
    return user

def is_vip(user_id):
    """VIP စစ်ဆေးခြင်း"""
    user = user_stats.find_one({'_id': user_id})
    if user and user.get('status') == 'vip':
        expiry = user.get('vip_info', {}).get('expiry', 0)
        if expiry and expiry > time.time():
            return True
        else:
            user_stats.update_one({'_id': user_id}, {'$set': {'status': 'free', 'vip_info.expiry': None}})
            return False
    return False

def check_subscription(user_id):
    """Member Join ထားမထား စစ်ခြင်း"""
    try:
        member = bot.get_chat_member(CHANNEL_2_ID, user_id)
        if member.status in ['creator', 'administrator', 'member']:
            return True
        return False
    except:
        return False

# ==========================================
# (2) ADMIN COMMANDS
# ==========================================

@bot.message_handler(commands=['addvip'])
def add_vip(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        uid = int(parts[1])
        days = int(parts[2])
        expiry = time.time() + (days * 86400)
        
        user_stats.update_one(
            {'_id': uid}, 
            {'$set': {'status': 'vip', 'vip_info': {'expiry': expiry, 'start_date': time.time()}}}, 
            upsert=True
        )
        bot.reply_to(message, f"✅ User `{uid}` is now VIP for {days} days.", parse_mode="Markdown")
    except:
        bot.reply_to(message, "⚠️ Usage: `/addvip [UserID] [Days]`")

@bot.message_handler(commands=['delvip'])
def delete_vip(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        uid = int(message.text.split()[1])
        user_stats.update_one({'_id': uid}, {'$set': {'status': 'free', 'vip_info': {}}})
        bot.reply_to(message, f"🗑️ User `{uid}` is now Free User.", parse_mode="Markdown")
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

# --- NEW COMMAND: LIST ALL USERS ---
@bot.message_handler(commands=['users'])
def list_users(message):
    if message.from_user.id != ADMIN_ID: return
    
    wait_msg = bot.reply_to(message, "📂 Generating user list...")
    
    try:
        # Get all users from DB
        users = user_stats.find()
        
        # Create file content string
        file_content = "ID | Name | Username | Status | Phone\n"
        file_content += "="*60 + "\n"
        
        count = 0
        for user in users:
            uid = user.get('_id', 'N/A')
            name = user.get('first_name', 'No Name')
            username = user.get('username', 'None')
            status = user.get('status', 'free')
            phone = user.get('phone_number', 'None')
            
            line = f"{uid} | {name} | @{username} | {status} | {phone}\n"
            file_content += line
            count += 1
            
        file_content += f"\nTotal Users: {count}"
        
        # Write to temporary file
        filename = "user_list.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(file_content)
            
        # Send the file
        with open(filename, "rb") as f:
            bot.send_document(message.chat.id, f, caption=f"✅ Total Users: {count}")
            
        # Clean up (Delete the file from server)
        os.remove(filename)
        bot.delete_message(message.chat.id, wait_msg.message_id)
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

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
        data = {'_id': custom_id, 'msg_id': message.forward_from_message_id, 'file_name': caption}
        collection.update_one({'_id': custom_id}, {'$set': data}, upsert=True)
        bot.reply_to(message, f"✅ Saved! ID: `{custom_id}`", parse_mode="Markdown")
    else:
        bot.reply_to(message, "⚠️ ID နံပါတ် မတွေ့ပါ။")

# ==========================================
# (4) PHONE NUMBER HANDLER (NEW FEATURE)
# ==========================================
@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    if message.contact:
        user_id = message.from_user.id
        phone_number = message.contact.phone_number
        
        # Database ထဲသို့ Phone Number သိမ်းခြင်း
        user_stats.update_one(
            {'_id': user_id}, 
            {'$set': {'phone_number': phone_number}}
        )
        
        # Button ကို ပြန်ဖျက်ပြီး Welcome စာ ပြန်ပို့
        remove_kb = types.ReplyKeyboardRemove()
        bot.send_message(message.chat.id, "✅ Registration Successful!", reply_markup=remove_kb)

# ==========================================
# (5) MAIN LOGIC & START
# ==========================================
@bot.message_handler(func=lambda m: True)
def handle_message(message):
    user_id = message.from_user.id
    user_data = get_or_register_user(message) # Register & Update Info

    # START COMMAND
    if message.text == '/start':
        vip_status = is_vip(user_id)
        status_text = " VIP Member 🏆" if vip_status else "Free Member🐼"
        user_name = message.from_user.first_name
        
        # Phone Number မရှိသေးရင် Button ပြမည်
        markup = types.ReplyKeyboardRemove() # Default is remove
        if user_data.get('phone_number') is None:
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            btn = types.KeyboardButton("Add to Contact", request_contact=True)
            markup.add(btn)
        
        txt = (f"👋 Hello {user_name}\n\n"
               f"🪪 Your ID - `{user_id}`\n"
               f"💎 Status: {status_text}\n\n"
               f"🎬 Movie ID ရိုက်ထည့်ပါ")
        
        bot.send_message(message.chat.id, txt, parse_mode="Markdown", reply_markup=markup)
        return

    # SUBSCRIPTION CHECK
    if not check_subscription(user_id):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Join Channel First", url=CHANNEL_2_LINK))
        bot.send_message(message.chat.id, "⚠️ Movie Request လုပ်ရန် Channel Join ပေးပါ", reply_markup=markup)
        return

    # GET MOVIE
    movie_id = message.text.strip()
    movie = collection.find_one({'_id': movie_id})
    if not movie:
        bot.send_message(message.chat.id, "❌ ID မှားယွင်းနေပါသည်။\n\n admin 🌵 @tec102024")
        return

    # LOGIC
    user_vip = is_vip(user_id)
    current_time = time.time()
    usage = user_data.get('usage', {})
    daily_count = usage.get('daily_count', 0)
    reset_time = usage.get('reset_time', current_time + 86400)
    last_req = usage.get('last_request_time', 0)

    if current_time > reset_time:
        daily_count = 0
        reset_time = current_time + 86400
        user_stats.update_one({'_id': user_id}, {'$set': {'usage.daily_count': 0, 'usage.reset_time': reset_time}})

    if user_vip:
        if daily_count < VIP_SAVE_LIMIT:
            protect_content = False 
            note = f"🏆 VIP Mode: 🔰 ({daily_count+1}/{VIP_SAVE_LIMIT})"
        else:
            protect_content = True
            note = "⚠️ VIP Mode: Unlimited View Only"
        delete_delay = VIP_DELETE_TIME
    else:
        if daily_count >= FREE_DAILY_LIMIT:
            bot.send_message(message.chat.id, "❌ Daily Limit Reached.\n\nဒီနေ့အတွက် Request Limit ပြည့်သွားပါပြီ။\n\n(၂၄ နာရီပြည့်မှ ပြန်လည် Request ပြုလုပ်နိုင်မည်။)\n\n Join VIP 🏆 for Unlimited \n\n admin 🌵 @tec102024")
            return
        if (current_time - last_req) < FREE_COOLDOWN:
            bot.send_message(message.chat.id, f"⏳ Free Mode Wait {int(FREE_COOLDOWN - (current_time - last_req))}s")
            return
        protect_content = True 
        delete_delay = FREE_DELETE_TIME
        note = f"🔴 Free Mode: Save Restricted ({daily_count+1}/{FREE_DAILY_LIMIT})"

    # SEND
    wait_msg = bot.send_message(message.chat.id, "🔍 Finding...")
    try:
        sent_msg = bot.copy_message(
            chat_id=user_id,
            from_chat_id=CHANNEL_3_ID,
            message_id=movie['msg_id'],
            caption=f"{movie.get('file_name', '')}{CAPTION_SUFFIX}",
            protect_content=protect_content
        )
        bot.delete_message(message.chat.id, wait_msg.message_id)
        bot.send_message(message.chat.id,f"{note}\n")

        user_stats.update_one(
            {'_id': user_id},
            {
                '$inc': {'usage.daily_count': 1}, 
                '$set': {'usage.last_request_time': current_time, 'usage.reset_time': reset_time}
            }
        )
        delete_queue.insert_one({
            'chat_id': user_id,
            'message_id': sent_msg.message_id,
            'delete_time': current_time + delete_delay
        })
    except Exception as e:
        bot.delete_message(message.chat.id, wait_msg.message_id)
        bot.send_message(message.chat.id, "❌ Error sending movie.")

# ==========================================
# (6) SERVER
# ==========================================
app = Flask('')
@app.route('/')
def home(): return "Bot Running"
def run_http(): app.run(host='0.0.0.0', port=8000)
def auto_delete_worker():
    while True:
        try:
            now = time.time()
            for msg in delete_queue.find({"delete_time": {"$lte": now}}):
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
