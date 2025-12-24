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

# --- SETTINGS (ဒီမှာ ပြင်ပါ) ---
COOLDOWN_SECONDS = 60  # 1 မိနစ်
DAILY_LIMIT = 10        # ၁၀ ပုဒ်
# (New) Caption နောက်မှာ ထပ်ဖြည့်မည့်စာ
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
# (1) BROADCAST SECTION (ထိပ်ဆုံးမှာ ထားရပါမယ်)
# ==========================================
@bot.message_handler(commands=['broadcast'], func=lambda m: m.from_user.id == ADMIN_ID)
def handle_broadcast(message):
    msg_text = message.text.replace('/broadcast', '').strip()
    if not msg_text:
        bot.reply_to(message, "⚠️ ပို့ချင်သော စာသားကို ရေးပေးပါ။\nဥပမာ: /broadcast မင်္ဂလာပါ")
        return

    # Thread အသစ်နဲ့ ပို့မယ် (Bot မလေးသွားအောင်)
    Thread(target=start_broadcast_process, args=(message, msg_text)).start()

def start_broadcast_process(message, text_to_send):
    users = user_stats.find({})
    total_users = user_stats.count_documents({})
    sent_count = 0
    blocked_count = 0
    
    status_msg = bot.reply_to(message, f"📢 Broadcast စတင်နေပါပြီ...\nTotal Users: {total_users}")
    
    for user in users:
        try:
            bot.send_message(user['_id'], text_to_send)
            sent_count += 1
            time.sleep(0.05) 
        except:
            blocked_count += 1
            continue
            
    bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=status_msg.message_id,
        text=f"✅ Broadcast ပြီးဆုံးပါပြီ!\n👥 ပို့လိုက်သူ: {sent_count}\n🚫 Block/Fail: {blocked_count}"
    )

# ==========================================
# WEB SERVER & AUTO DELETE WORKER
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "Bot is running with Custom Caption!"

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

# --- Admin Section (Save Movie) ---
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
            # (ပြင်ဆင်ချက်) Caption ကို အပြည့်သိမ်းပါမယ် ([:50] ကို ဖြုတ်လိုက်သည်)
            'file_name': caption 
        }
        collection.update_one({'_id': custom_id}, {'$set': data}, upsert=True)
        bot.reply_to(message, f"✅ Saved!\nCustom ID: {custom_id}")
    else:
        bot.reply_to(message, "⚠️ ID နံပါတ် မတွေ့ပါ။")

# --- User Section (Get Movie) ---
@bot.message_handler(func=lambda message: True)
def handle_user_request(message):
    # 1. User ပို့တဲ့ ID စာကို ချက်ချင်း ဖျက်မယ် (Chat ရှင်းအောင်)
    try:
        bot.delete_message(message.chat.id) #message.message_id
    except:
        pass

    if message.text.startswith('/'):
        if message.text == '/start':
            user_stats.update_one(
             {'_id': user_id}, 
             {'$setOnInsert': {'daily_count': 0, 'join_date': time.time()}}, 
             upsert=True
         )
             bot.reply_to(message, f"Download ပြုလုပ်လိုသော Movie ID ရိုက်ထည့်ပါ")
        return

    user_id = message.from_user.id

    if not is_subscribed(user_id):
        markup = types.InlineKeyboardMarkup()
        btn = types.InlineKeyboardButton("Movie Store Member ဝင်ရန်", url=CHANNEL_2_LINK)
        markup.add(btn)
        bot.reply_to(message, "⚠️ မိတ်ဆွေသည် Movie Channel ကို Join မထားရသေးပါ။\nအောက်က Link ကိုနှိပ်ပြီး Member အရင်ဝင်ပေးပါ။", reply_markup=markup)
        return

    # --- LIMIT CHECK ---
    current_time = time.time()
    user_data = user_stats.find_one({'_id': user_id})
    daily_count = 0
    reset_time = current_time + 86400
    last_request = 0

    if user_data:
        reset_time = user_data.get('reset_time', current_time + 86400)
        daily_count = user_data.get('daily_count', 0)
        last_request = user_data.get('last_request_time', 0)

        if current_time > reset_time:
            daily_count = 0
            reset_time = current_time + 86400
            user_stats.update_one({'_id': user_id}, {'$set': {'daily_count': 0, 'reset_time': reset_time}})

        if daily_count >= DAILY_LIMIT:
            bot.reply_to(message, f"❌ ဒီနေ့အတွက် Download Limit ပြည့်သွားပါပြီ။\n(၂၄ နာရီပြည့်မှ ပြန်လည် Download ပြုလုပ်နိုင်မည်) admin-@tec102024")
            return

        time_diff = current_time - last_request
        if time_diff < COOLDOWN_SECONDS:
            wait_time = int(COOLDOWN_SECONDS - time_diff)
            bot.reply_to(message, f"⏳ ခဏစောင့်ပါ။ Waiting time - {wait_time}s ကျန်သေးသည်။")
            return

    # --- Find & Send Movie ---
    custom_id = message.text.strip()
    movie_data = collection.find_one({'_id': custom_id})
    
    if movie_data:
        real_msg_id = movie_data['msg_id']
        # Database ထဲက မူရင်း Caption ကို ယူမယ်
        original_caption = movie_data.get('file_name', '')
        
        # မူရင်း Caption + Admin Credit ပေါင်းထည့်မယ်
        new_caption = f"{original_caption}{CAPTION_SUFFIX}"
        
        waiting = bot.reply_to(message, f"🔍 Finding movie... ({daily_count + 1}/{DAILY_LIMIT})")
        
        try:
            # (ပြင်ဆင်ချက်) caption=new_caption ကို ထည့်ပေးလိုက်သည်
            sent_msg = bot.copy_message(
                chat_id=user_id, 
                from_chat_id=CHANNEL_3_ID, 
                message_id=real_msg_id,
                caption=new_caption
            )
            
            bot.delete_message(chat_id=user_id, message_id=waiting.message_id)
            
            user_stats.update_one(
                {'_id': user_id}, 
                {
                    '$set': {'last_request_time': current_time, 'reset_time': reset_time},
                    '$inc': {'daily_count': 1}
                }, 
                upsert=True
            )
            
            delete_time = time.time() + 60
            delete_queue.insert_one({
                'chat_id': user_id,
                'message_id': sent_msg.message_id,
                'delete_time': delete_time
            })
            
        except Exception as e:
            # --- AUTO CLEAN LOGIC (ဒီအပိုင်းက အသစ်ပါ) ---
            # 1. "Finding..." ဆိုတဲ့ စာကို အရင်ဖျက်မယ်
            try:
                bot.delete_message(chat_id=user_id, message_id=waiting.message_id)
            except:
                pass

            # 2. User ကို စာပြန်မယ်
            bot.reply_to(message, "❌ တောင်းပန်ပါတယ်၊ ဒီဇာတ်ကားကို Channel ထဲမှ ဖျက်သိမ်းလိုက်ပါပြီ။")
            
            # 3. Database ထဲကနေပါ အဲ့ဒီ ID ကို အပြီးတိုင် ဖျက်မယ်
            collection.delete_one({'_id': custom_id})
            print(f"Deleted invalid movie ID {custom_id} from database.")
    else:
        bot.reply_to(message, f"❌ ID '{custom_id}' နှင့် Movie ရှာမတွေ့ပါ။ ID မှန်ကန်ကြောင်း ပြန်စစ်ပါ (သို့) Admin မှ မထည့်ရသေးခြင်း ဖြစ်နိုင်ပါသည်။ $ admin $ @tec102024")

# --- Main Execution ---
if __name__ == "__main__":
    keep_alive()
    print("Bot started...")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"Bot crashed: {e}")
            time.sleep(5)

