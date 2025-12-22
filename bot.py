import telebot
from telebot import types
import pymongo
import os
import re

# --- Configuration (Environment Variables မှ ယူပါမည်) ---
# Koyeb မှာ ဒီတန်ဖိုးတွေကို ဖြည့်ပေးရပါမယ်
API_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URL = os.getenv('MONGO_URL')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
CHANNEL_2_ID = int(os.getenv('CHANNEL_2_ID')) # Movie Channel (Private)
CHANNEL_2_LINK = os.getenv('CHANNEL_2_LINK') # Invite Link
CHANNEL_3_ID = int(os.getenv('CHANNEL_3_ID')) # Storage Channel

# --- Database Connection ---
try:
    client = pymongo.MongoClient(MONGO_URL)
    db = client['movie_bot_db'] # Database Name
    collection = db['movies']   # Collection Name
    print("MongoDB Connected Successfully!")
except Exception as e:
    print(f"MongoDB Connection Error: {e}")

bot = telebot.TeleBot(API_TOKEN)

# --- Check Member Function ---
def is_subscribed(user_id):
    try:
        # User က Channel 2 မှာ Member ဖြစ်မဖြစ် စစ်ဆေးခြင်း
        status = bot.get_chat_member(CHANNEL_2_ID, user_id).status
        if status in ['creator', 'administrator', 'member']:
            return True
        return False
    except Exception as e:
        print(f"Subscription Check Error: {e}")
        return False

# --- Admin Section (Save Movie) ---
# Admin က Channel 3 ထဲက Video ကို Bot ဆီ Forward လုပ်ရင် Database ထဲသိမ်းမယ်
@bot.message_handler(content_types=['video', 'document'], func=lambda m: m.from_user.id == ADMIN_ID)
def handle_admin_forward(message):
    caption = message.caption if message.caption else ""
    
    # Caption ထဲက ID (ဥပမာ 16042) ကို Regex နဲ့ရှာမယ်
    match = re.search(r'(\d+)', caption)
    
    if match:
        custom_id = match.group(1) # 16042
        real_msg_id = message.forward_from_message_id # Channel 3 Message ID
        
        if not real_msg_id:
             bot.reply_to(message, "⚠️ Channel 3 ထဲကနေ Forward လုပ်ပေးမှ အဆင်ပြေပါမယ်။")
             return

        # MongoDB ထဲကို Save မယ် (ရှိပြီးသားဆို Update လုပ်မယ်)
        data = {
            '_id': custom_id,
            'msg_id': real_msg_id,
            'file_name': caption[:50] # နာမည် အနည်းငယ်မှတ်ထားမယ်
        }
        
        # Upsert=True ဆိုတာ မရှိရင်အသစ်ထည့်၊ ရှိရင် update လုပ်တာပါ
        collection.update_one({'_id': custom_id}, {'$set': data}, upsert=True)
        
        bot.reply_to(message, f"✅ Database မှာ သိမ်းလိုက်ပါပြီ!\nCustom ID: {custom_id}\nReal ID: {real_msg_id}")
    else:
        bot.reply_to(message, "⚠️ Caption ထဲမှာ ID နံပါတ် မတွေ့ပါ။ (ဥပမာ: '16042- Movie Name')")

# --- User Section (Get Movie) ---
@bot.message_handler(func=lambda message: True)
def handle_user_request(message):
    user_id = message.from_user.id
    
    # 1. Start Command ဆိုရင် နှုတ်ဆက်မယ်
    if message.text == '/start':
        bot.reply_to(message, "မင်္ဂလာပါ! Movie ID နံပါတ်ကို ရိုက်ထည့်ပါ။")
        return

    # 2. Member စစ်ဆေးခြင်း
    if not is_subscribed(user_id):
        markup = types.InlineKeyboardMarkup()
        btn = types.InlineKeyboardButton("Join Movie Channel First", url=CHANNEL_2_LINK)
        markup.add(btn)
        bot.reply_to(message, 
                     "⚠️ မိတ်ဆွေက Movie Channel ကို Join မထားပါဘူး။\nအောက်က Link ကိုနှိပ်ပြီး အရင် Join ပေးပါ။ ပြီးမှ ID ပြန်ရိုက်ပါ။", 
                     reply_markup=markup)
        return

    # 3. Database မှာ ရှာပြီး ပို့ပေးခြင်း
    custom_id = message.text.strip()
    
    # MongoDB ထဲမှာ ရှာမယ်
    movie_data = collection.find_one({'_id': custom_id})
    
    if movie_data:
        real_msg_id = movie_data['msg_id']
        waiting = bot.reply_to(message, "🔍 Movie ရှာနေပါသည်... ပို့ပေးနေပါပြီ...")
        
        try:
            bot.copy_message(chat_id=user_id, from_chat_id=CHANNEL_3_ID, message_id=real_msg_id)
            bot.delete_message(chat_id=user_id, message_id=waiting.message_id)
        except Exception as e:
            bot.reply_to(message, "❌ File ပို့မရပါ (Original File ဖျက်လိုက်ခြင်း ဖြစ်နိုင်သည်)")
    else:
        bot.reply_to(message, f"❌ ID '{custom_id}' နှင့် Movie ရှာမတွေ့ပါ။ ID မှန်ကန်ကြောင်း ပြန်စစ်ပါ (သို့) Admin မှ မထည့်ရသေးခြင်း ဖြစ်နိုင်ပါသည်။")

# --- Run Bot ---
print("Bot is running on Koyeb...")
bot.infinity_polling()