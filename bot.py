import telebot
from telebot import types
import pymongo
import os
import re
from flask import Flask     # (အသစ်တိုး)
from threading import Thread # (အသစ်တိုး)

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

# --- WEB SERVER FOR KOYEB HEALTH CHECK (အသစ်ထပ်ထည့်ထားသော အပိုင်း) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive and running!"

def run():
    # Port 8000 မှာ Server ဖွင့်မည်
    app.run(host='0.0.0.0', port=8000)

def keep_alive():
    t = Thread(target=run)
    t.start()
# ------------------------------------------------------------------

# --- Check Member Function ---
def is_subscribed(user_id):
    try:
        status = bot.get_chat_member(CHANNEL_2_ID, user_id).status
        if status in ['creator', 'administrator', 'member']:
            return True
        return False
    except Exception as e:
        print(f"Subscription Check Error: {e}")
        return False

# --- Admin Section ---
@bot.message_handler(content_types=['video', 'document'], func=lambda m: m.from_user.id == ADMIN_ID)
def handle_admin_forward(message):
    caption = message.caption if message.caption else ""
    match = re.search(r'(\d+)', caption) # ပုံထဲကလို 16029 ကို ရှာမယ်
    
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
        bot.reply_to(message, f"✅ Database မှာ သိမ်းလိုက်ပါပြီ!\nCustom ID: {custom_id}")
    else:
        bot.reply_to(message, "⚠️ Caption ထဲမှာ ID နံပါတ် မတွေ့ပါ။")

# --- User Section ---
@bot.message_handler(func=lambda message: True)
def handle_user_request(message):
    user_id = message.from_user.id
    
    if message.text == '/start':
        bot.reply_to(message, "မင်္ဂလာပါ! Movie ID နံပါတ်ကို ရိုက်ထည့်ပါ။")
        return

    if not is_subscribed(user_id):
        markup = types.InlineKeyboardMarkup()
        btn = types.InlineKeyboardButton("Join Movie Channel First", url=CHANNEL_2_LINK)
        markup.add(btn)
        bot.reply_to(message, "Channel ကို Join ထားခြင်း မရှိပါ။ အောက်က Link ကနေ Join ပါ။", reply_markup=markup)
        return

    custom_id = message.text.strip()
    movie_data = collection.find_one({'_id': custom_id})
    
    if movie_data:
        real_msg_id = movie_data['msg_id']
        waiting = bot.reply_to(message, "🔍 Movie ရှာနေပါသည်...")
        try:
            bot.copy_message(chat_id=user_id, from_chat_id=CHANNEL_3_ID, message_id=real_msg_id)
            bot.delete_message(chat_id=user_id, message_id=waiting.message_id)
        except:
            bot.reply_to(message, "❌ File ပို့မရပါ (Original File ပျက်နေနိုင်သည်)")
    else:
        bot.reply_to(message, f"❌ ID '{custom_id}' မတွေ့ပါ။")

# --- Run Bot ---
# Web Server ကို အရင်ဖွင့်ပြီးမှ Bot ကို run မယ်
keep_alive() 
print("Bot is running on Koyeb with Webhook support...")
bot.infinity_polling()
