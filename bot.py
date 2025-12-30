import telebot
from telebot import types
import pymongo
import os
import re
from flask import Flask
from threading import Thread
import time
from datetime import datetime

# --- Configuration (Koyeb Environment Variables) ---
API_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URL = os.getenv('MONGO_URL')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

# Channel IDs
CHANNEL_2_ID = int(os.getenv('CHANNEL_2_ID')) # Poster Channel
CHANNEL_2_LINK = os.getenv('CHANNEL_2_LINK')
CHANNEL_3_ID = int(os.getenv('CHANNEL_3_ID')) # Database Channel
BACKUP_CHANNEL_ID = os.getenv('BACKUP_CHANNEL_ID')

# --- SETTINGS ---
FREE_DAILY_LIMIT = 5
FREE_DELETE_TIME = 86400     # 24 Hours
FREE_COOLDOWN = 120           # 120 Seconds

VIP_SAVE_LIMIT = 15          # 15 Files Save Limit
VIP_DELETE_TIME = 86400      # 24 Hours

CAPTION_SUFFIX = "\n\n🌵admin @moviestoreadmin🌵" 

# --- Database Connection ---
try:
    client = pymongo.MongoClient(MONGO_URL)
    db = client['movie_bot_db']
    collection = db['movies']
    delete_queue = db['delete_queue']
    user_stats = db['user_stats']
    print("✅ MongoDB Connected!")
    
    # Indexing (ရှာဖွေမှု မြန်ဆန်စေရန်) - ဒီမှာ တစ်ခါတည်းပေါင်းထည့်ပါ
    collection.create_index([("_id", pymongo.ASCENDING)]) 
    user_stats.create_index([("_id", pymongo.ASCENDING)]) 
    collection.create_index("backup_msg_id")
    
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

# ==========================================
def run_backup_logic(admin_chat_id):
    try:
        # (ပြင်ဆင်ချက်) Backup မလုပ်ရသေးသော ဖိုင်များကိုသာ ရှာမည်
        # backup_msg_id မရှိသော (False ဖြစ်သော) ဖိုင်များကို filter လုပ်သည်
        movies_cursor = collection.find({'backup_msg_id': {'$exists': False}})
        
        # မလုပ်ရသေးတာ ဘယ်နှစ်ပုဒ်ကျန်လဲ ရေတွက်မယ်
        pending_count = collection.count_documents({'backup_msg_id': {'$exists': False}})
        total_in_db = collection.count_documents({})
        
        if pending_count == 0:
            bot.send_message(admin_chat_id, "✅ **All Up to Date!**\n\nBackup လုပ်ရန် ဖိုင်အသစ် မရှိပါ။")
            return

        success = 0
        failed = 0
        processed = 0
        
        start_msg = bot.send_message(admin_chat_id, f"🚀 **Backup Started...**\n\n📂 Total Movies: {total_in_db}\n🆕 New Files to Copy: {pending_count}")

        for movie in movies_cursor:
            movie_db_id = movie['_id']
            original_msg_id = movie['msg_id']
            caption = movie.get('file_name', 'Movie')

            try:
                # Copy Message
                backup_msg = bot.copy_message(
                    chat_id=int(BACKUP_CHANNEL_ID),
                    from_chat_id=CHANNEL_3_ID,
                    message_id=original_msg_id,
                    caption=f"{caption}\n\n admin🌵@moviestoreadmin"
                )
                
                # Success ဖြစ်ရင် Database မှာ Update လုပ်မယ်
                collection.update_one(
                    {'_id': movie_db_id},
                    {'$set': {'backup_msg_id': backup_msg.message_id}}
                )
                success += 1
                
                # FloodWait ကာကွယ်ရန် ၃ စက္ကန့် စောင့်မယ်
                time.sleep(3) 

            except Exception as e:
                print(f"Failed ID {movie_db_id}: {e}")
                failed += 1
                time.sleep(2)

            processed += 1
            
            # အပုဒ် ၂၀ ပြီးတိုင်း Admin ကို Progress ပြမယ်
            if processed % 20 == 0:
                try:
                    bot.edit_message_text(
                        f"🔄 Progress: {processed}/{pending_count}\n✅ Success: {success}\n❌ Failed: {failed}", 
                        chat_id=admin_chat_id, 
                        message_id=start_msg.message_id
                    )
                except: pass

        # အားလုံးပြီးသွားရင်
        bot.send_message(admin_chat_id, f"✅ **Backup Job Finished!**\n\n🆕 New Copied: {success}\n❌ Failed: {failed}")

    except Exception as e:
        bot.send_message(admin_chat_id, f"❌ Backup System Error: {e}")
        
def is_vip(user_id):
    """VIP စစ်ဆေးခြင်း + Auto Expire Notification"""
    user = user_stats.find_one({'_id': user_id})
    
    if user and user.get('status') == 'vip':
        expiry = user.get('vip_info', {}).get('expiry', 0)
        
        # သက်တမ်း ကျန်သေးရင် True ပြန်မယ်
        if expiry and expiry > time.time():
            return True
            
        # သက်တမ်း ကုန်သွားရင် (Expire ဖြစ်ရင်)
        else:
            # 1. Database မှာ Free User ပြန်ပြောင်းမယ်
            user_stats.update_one(
                {'_id': user_id}, 
                {'$set': {'status': 'free', 'vip_info.expiry': None}}
            )
            
            # 2. User ဆီကို စာလှမ်းပို့မယ် (NEW FEATURE)
            try:
                bot.send_message(
                    user_id, 
                    "⚠️ **VIP Expired**\n\n"
                    "လူကြီးမင်း၏ VIP Member သက်တမ်း ကုန်ဆုံးသွားပါပြီ။ ⏳\n"
                    "Free Member အဖြစ် ပြန်လည်သတ်မှတ်လိုက်ပါသည်။ 🐼", 
                    parse_mode="Markdown"
                )
            except:
                pass # User က Block ထားရင် ကျော်သွားမယ်
                
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
        
        # 1. Database Update လုပ်မယ်
        user_stats.update_one(
            {'_id': uid}, 
            {'$set': {'status': 'vip', 'vip_info': {'expiry': expiry, 'start_date': time.time()}}}, 
            upsert=True
        )
        
        # 2. Admin ကို Success ဖြစ်ကြောင်း ပြန်ပြောမယ်
        bot.reply_to(message, f"✅ User `{uid}` is now VIP for {days} days.", parse_mode="Markdown")
        
        # 3. User ဆီကို VIP ရပြီဖြစ်ကြောင်း လှမ်းပြောမယ် (Notification)
        user_msg = (f"🎉 **Congratulations!** 🎉\n\n"
                    f"လူကြီးမင်း၏ အကောင့်အား VIP Member အဖြစ် အဆင့်မြှင့်တင်လိုက်ပါပြီ။ 💎\n\n"
                    f"🗓 သက်တမ်း: **{days} ရက်**\n"
                    f"✅ ယခုမှစ၍ Daily Limit မရှိ စိတ်ကြိုက်ကြည့်ရှုနိုင်ပါပြီ။\n\n"
                    f"Enjoy Movies! 🎬")
        
        bot.send_message(uid, user_msg, parse_mode="Markdown")
        
    except Exception as e:
        # User က Bot ကို Block ထားရင် Error တက်နိုင်လို့ try-except ခံထားတာပါ
        bot.reply_to(message, f"⚠️ Error or User Blocked Bot: {e}\nUsage: `/addvip [UserID] [Days]`")

# ... (addvip function အပေါ်မှာ ရှိနေမယ်) ...

# ==========================================
# INSERT HERE (ဒီနေရာမှာ ထည့်ပါ)
# ==========================================

@bot.message_handler(commands=['delvip'])
def delete_vip(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        # Command ကို ခွဲထုတ်ခြင်း (Example: /delvip 123456)
        parts = message.text.split()
        
        # ID မပါရင် Error ပြမယ်
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ Usage: `/delvip [UserID]`")
            return

        uid = int(parts[1])
        
        # 1. Database Update (Free ပြန်ပြောင်း၊ VIP info ရှင်းထုတ်)
        result = user_stats.update_one(
            {'_id': uid}, 
            {'$set': {'status': 'free', 'vip_info': {}}}
        )
        
        # Database မှာ User မရှိရင် ပြောမယ်
        if result.matched_count == 0:
            bot.reply_to(message, "❌ User ID ရှာမတွေ့ပါ။")
            return

        # 2. Admin ကို Success Message ပြ
        bot.reply_to(message, f"🗑️ User `{uid}` is now Free User.", parse_mode="Markdown")
        
        # 3. User ကို VIP ပျက်သွားကြောင်း လှမ်းပြော (Notification)
        try:
            bot.send_message(uid, "⚠️ **VIP Ended**\n\nလူကြီးမင်း၏ VIP Member သက်တမ်း ကုန်ဆုံးသွားပါပြီ။\nFree Member အဖြစ် ပြန်လည်သတ်မှတ်လိုက်ပါသည်။", parse_mode="Markdown")
        except:
            pass # User က Bot ကို Block ထားရင် ကျော်သွားမယ်

    except ValueError:
        bot.reply_to(message, "❌ User ID သည် ကိန်းဂဏန်း (Number) ဖြစ်ရပါမည်။")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# ... (broadcast function က ဒီအောက်မှာ ဆက်ရှိနေမယ်) ...

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
    
# BACKUP COMMAND
@bot.message_handler(commands=['backup_start'])
def start_backup_handler(message):
    if message.from_user.id != ADMIN_ID: return
    
    # Backup က ကြာနိုင်တဲ့အတွက် Thread ခွဲပြီး Run ပေးရပါမယ်
    # ဒါမှ Bot က မရပ်သွားဘဲ တခြားဟာတွေ ဆက်လုပ်လို့ရမှာပါ
    Thread(target=run_backup_logic, args=(message.chat.id,)).start()

# --- NEW COMMAND: SERVER STATS ---
@bot.message_handler(commands=['stats'])
def bot_stats(message):
    if message.from_user.id != ADMIN_ID: return
    
    # Database မှ စာရင်းများကို ရေတွက်ခြင်း
    total_users = user_stats.count_documents({})
    vip_users = user_stats.count_documents({'status': 'vip'})
    free_users = total_users - vip_users
    
    # ဒီနေ့ Bot သုံးသွားတဲ့ သူအရေအတွက် (daily_count > 0)
    active_today = user_stats.count_documents({'usage.daily_count': {'$gt': 0}})
    
    txt = (f"📊 **Bot Statistics**\n\n"
           f"👥 Total Users: `{total_users}`\n"
           f"🏆 VIP Members: `{vip_users}`\n"
           f"🐼 Free Users: `{free_users}`\n"
           f"🔥 Active Today: `{active_today}`")
    
    bot.reply_to(message, txt, parse_mode="Markdown")

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
        bot.send_message(message.chat.id, "✅ Add to Contact Successful!", reply_markup=remove_kb)

# ==========================================
# ==========================================
# (4.5) PAYMENT & SLIP HANDLER (NEW)
# ==========================================

# (A) Buy VIP Button နှိပ်လိုက်ရင် Payment စာပြမည်
@bot.callback_query_handler(func=lambda call: call.data == 'buy_vip')
def send_payment_info(call):
    # Payment အချက်အလက်များကို ဒီမှာ ပြင်ပါ
    payment_text = (
        "💎 **VIP Premium Plan** 💎\n\n"
        "🔥 Daily Limit မရှိ ကြိုက်သလောက်ကြည့်နိုင်ပါမည်။\n\n"
        "💸 **Pricing:**\n"
        "• 1 Month  -  3,000 MMK\n"
        "• 6 Month  - 10,000 MMK\n"
        "• Lifetime  - 20,000 MMK\n\n"
        "Available Payment 🏦 KBZPay & Wave Pay\n\n"
        "ဆက်သွယ်ရန် admin🌵@moviestoreadmin"
    )
    bot.send_message(call.message.chat.id, payment_text, parse_mode="Markdown")

# (B) User က Slip (Photo) ပို့လာရင် Admin ဆီ Forward လုပ်မည်
@bot.message_handler(content_types=['photo'])
def handle_payment_slip(message):
    # Admin ပို့တာဆိုရင် ဘာမှမလုပ်ဘူး (User ပို့တာကိုဘဲ ဖမ်းမယ်)
    if message.from_user.id == ADMIN_ID: return

    user_id = message.from_user.id
    username = message.from_user.username if message.from_user.username else "No Username"
    first_name = message.from_user.first_name

    # Admin ဆီပို့မည့် ပုံစံ
    caption_to_admin = (
        f"📩 **New Payment Slip Received!**\n\n"
        f"👤 Name: {first_name}\n"
        f"🆔 ID:  `{user_id}`\n"
        f"🔗 Username: @{username}\n\n"
        f"⚠️ Check payment and use:\n"
        f"`/addvip {user_id} 30`"
    )

    # Admin ဆီသို့ Forward လုပ်ခြင်း
    try:
        bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption_to_admin, parse_mode="Markdown")
        bot.reply_to(message, "✅ Payment Slip လက်ခံရရှိပါသည်။ Admin မှ စစ်ဆေးပြီး မကြာမီ VIP ထည့်ပေးပါမည်။")
    except Exception as e:
        print(f"Error forwarding slip: {e}")
        
# (5) MAIN LOGIC & START
# ==========================================
@bot.message_handler(func=lambda m: True)
def handle_message(message):
    user_id = message.from_user.id
    user_data = get_or_register_user(message) # Register & Update Info

    # START COMMAND
    if message.text == '/start':
        vip_status = is_vip(user_id)
        user_name = message.from_user.first_name
        
        # VIP Status စာသားနှင့် ရက်စွဲများ ပြင်ဆင်ခြင်း
        if vip_status:
            status_text = "VIP Member 🏆"
            
            # Database ထဲက VIP Info ကို ယူမယ်
            vip_info = user_data.get('vip_info', {})
            start_ts = vip_info.get('start_date')
            expiry_ts = vip_info.get('expiry')
            
            # Timestamp ကို လူနားလည်တဲ့ ရက်စွဲပြောင်းမယ် (DD-MM-YYYY)
            try:
                s_date = datetime.fromtimestamp(start_ts).strftime('%d/%m/%Y')
                e_date = datetime.fromtimestamp(expiry_ts).strftime('%d/%m/%Y')
                vip_dates = f"\n🗓 Started: {s_date}\n⏳ Expires: {e_date}"
            except:
                vip_dates = "" # Error တက်ရင် ဘာမှမပြဘူး
        else:
            status_text = "Free Member 🐼"
            vip_dates = ""

        # Phone Number မရှိသေးရင် Button ပြမည် (မူရင်းအတိုင်း)
        markup = types.ReplyKeyboardRemove()
        if user_data.get('phone_number') is None:
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            btn = types.KeyboardButton("Add to Contact", request_contact=True)
            markup.add(btn)
        
        # User ဆီပို့မည့် စာသား
        txt = (f"👋 Hello {user_name}\n\n"
               f"🪪 Your ID - `{user_id}`\n"
               f"💎 Status   -  {status_text}"
               f"{vip_dates}\n\n"  # VIP ဆိုရင် ရက်စွဲတွေ ဒီမှာ ပေါ်လာမယ်
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
        bot.send_message(message.chat.id, "❌ ID မှားယွင်းနေပါသည်။")
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
            note = f"🏆 VIP Mode:  ({daily_count+1})" #/{VIP_SAVE_LIMIT}
        else:
            protect_content = True
            note = "⚠️ VIP Mode: Unlimited View Only"
        delete_delay = VIP_DELETE_TIME
    else:
        if daily_count >= FREE_DAILY_LIMIT:
            # VIP ဝယ်ရန် Button ဖန်တီးခြင်း
            markup = types.InlineKeyboardMarkup()
            vip_btn = types.InlineKeyboardButton("💎 Buy VIP Package", callback_data='buy_vip')
            markup.add(vip_btn)
            
            bot.send_message(
                message.chat.id, 
                "❌ Daily Limit Reached.\n\n"
                "ဒီနေ့အတွက် Request Limit ပြည့်သွားပါပြီ။\n"
                "(၂၄ နာရီပြည့်မှ ပြန်လည် Request ပြုလုပ်နိုင်မည်။)\n\n"
                "Join VIP for Unlimited!", 
                reply_markup=markup
            )
            return
        if (current_time - last_req) < FREE_COOLDOWN:
            bot.send_message(message.chat.id, f"⏳ Free Mode Wait ({int(FREE_COOLDOWN - (current_time - last_req))})s စောင့်ပါ။")
            return
        protect_content = True 
        delete_delay = FREE_DELETE_TIME
        note = f"🔴 Free Mode: Save Restricted ({daily_count+1}/{FREE_DAILY_LIMIT})"

    # SEND
    # (Update: Finding... အစား Chat Action သုံးခြင်း)
    bot.send_chat_action(message.chat.id, 'upload_video') 
    
    try:
        sent_msg = bot.copy_message(
            chat_id=user_id,
            from_chat_id=CHANNEL_3_ID,
            message_id=movie['msg_id'],
            caption=f"{movie.get('file_name', '')}{CAPTION_SUFFIX}",
            protect_content=protect_content
        )
        
        # Limit စာသားပို့ခြင်း
        bot.send_message(message.chat.id, f"{note}\n")

        # Database Update
        user_stats.update_one(
            {'_id': user_id},
            {
                '$inc': {'usage.daily_count': 1}, 
                '$set': {'usage.last_request_time': current_time, 'usage.reset_time': reset_time}
            }
        )
        # Auto Delete Queue ထဲထည့်ခြင်း
        delete_queue.insert_one({
            'chat_id': user_id,
            'message_id': sent_msg.message_id,
            'delete_time': current_time + delete_delay
        })
        
    except Exception as e:
        # Error တက်ခဲ့လျှင် (ဥပမာ - Admin က Channel ထဲက ဇာတ်ကားဖျက်လိုက်မိရင်)
        print(f"Send Error: {e}")
        error_msg = str(e).lower()
        
        if "message to copy not found" in error_msg or "message not found" in error_msg:
            bot.send_message(message.chat.id, "❌ တောင်းဆိုထားသော ဇာတ်ကားဖိုင် မရှိတော့ပါ (Deleted)။\nAdmin သို့ ဆက်သွယ်ပေးပါ။")
        elif "bot was blocked by the user" in error_msg:
            pass # User က Block ထားရင် ဘာမှဆက်မလုပ်
        else:
            bot.send_message(message.chat.id, "❌ Error sending movie. Please try again later.")
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

















