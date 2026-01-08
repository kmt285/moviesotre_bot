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
# Channel 3 အပြင် တခြား Channel တွေပါ ဒီမှာကော်မာ (,) ခံပြီး ထည့်လို့ရပါပြီ
SOURCE_CHANNELS = [CHANNEL_3_ID, -1003344611532]
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
# (1.5) BACKUP SYSTEM (IMPROVED LOGIC)
# ==========================================

# Global Variables to control backup process
is_backup_running = False
stop_backup_flag = False

def run_backup_logic(admin_chat_id):
    global is_backup_running, stop_backup_flag
    
    # Flag ဖွင့်မည်
    is_backup_running = True
    stop_backup_flag = False
    
    try:
        # Backup မလုပ်ရသေးသော ဖိုင်များကို ရှာမည်
        pending_cursor = collection.find({'backup_msg_id': {'$exists': False}})
        pending_count = collection.count_documents({'backup_msg_id': {'$exists': False}})
        total_in_db = collection.count_documents({})
        
        if pending_count == 0:
            bot.send_message(admin_chat_id, "✅ **All Up to Date!**\n\nBackup လုပ်ရန် ဖိုင်အသစ် မရှိပါ။")
            is_backup_running = False
            return

        success = 0
        failed = 0
        processed = 0
        
        status_msg = bot.send_message(
            admin_chat_id, 
            f"🚀 **Backup Started...**\n\n"
            f"📂 Total Movies: {total_in_db}\n"
            f"🆕 Target Copy: {pending_count}\n\n"
            f"💡 ရပ်ချင်ရင် /backup_stop ကိုနှိပ်ပါ"
        )

        for movie in pending_cursor:
            # STOP Command နှိပ်ထားခြင်း ရှိမရှိ စစ်မယ်
            if stop_backup_flag:
                bot.send_message(admin_chat_id, "🛑 **Backup Process Stopped by Admin!**")
                break

            movie_db_id = movie['_id']
            original_msg_id = movie['msg_id']
            caption = movie.get('file_name', 'Movie')
            
            # 🔥 FIX: Database ထဲက မှတ်ထားတဲ့ channel_id ကို ယူမယ်
            # မရှိရင် (အဟောင်းတွေအတွက်) CHANNEL_3_ID ကို default သုံးမယ်
            source_chat_id = movie.get('channel_id', CHANNEL_3_ID)

            try:
                # Copy Message (Correct Source Channel)
                backup_msg = bot.copy_message(
                    chat_id=int(BACKUP_CHANNEL_ID),
                    from_chat_id=source_chat_id, # <--- ပြင်ထားသော နေရာ (Dynamic Channel ID)
                    message_id=original_msg_id,
                    caption=f"{caption}\n\n admin🌵@moviestoreadmin"
                )
                
                # Success ဖြစ်ရင် Database မှာ Update လုပ်မယ်
                collection.update_one(
                    {'_id': movie_db_id},
                    {'$set': {'backup_msg_id': backup_msg.message_id}}
                )
                success += 1
                
                time.sleep(1.5)

            except Exception as e:
                err_str = str(e)
                if "Too Many Requests" in err_str:
                    try:
                        wait_time = int(re.search(r'retry after (\d+)', err_str).group(1)) + 1
                        print(f"😴 Sleeping for {wait_time}s due to FloodWait...")
                        time.sleep(wait_time)
                    except:
                        time.sleep(30)
                else:
                    print(f"Failed ID {movie_db_id}: {e}")
                    failed += 1
                    time.sleep(1) 

            processed += 1
            
            # Progress Update
            if processed % 20 == 0:
                try:
                    bot.edit_message_text(
                        f"🚀 **Backup Running...**\n\n"
                        f"📊 Progress: {processed}/{pending_count}\n"
                        f"✅ Success: {success}\n"
                        f"❌ Failed: {failed}\n\n"
                        f"🛑 Stop: /backup_stop", 
                        chat_id=admin_chat_id, 
                        message_id=status_msg.message_id
                    )
                except: pass

        final_text = (f"✅ **Backup Job Finished!**\n\n"
                      f"🆕 Copied: {success}\n"
                      f"❌ Failed: {failed}\n"
                      f"🏁 Processed: {processed}")
        
        bot.send_message(admin_chat_id, final_text)

    except Exception as e:
        bot.send_message(admin_chat_id, f"❌ Backup System Critical Error: {e}")
    
    finally:
        is_backup_running = False
        
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

# ==========================================
# 🔥 NEW COMMAND: DELETE RANGE (ID အလိုက် ဖျက်ခြင်း)
# ==========================================
@bot.message_handler(commands=['delrange'])
def delete_range_movies(message):
    if message.from_user.id != ADMIN_ID: return
    
    # Command: /delrange 8100 8899
    try:
        parts = message.text.split()
        if len(parts) < 3:
            bot.reply_to(message, "⚠️ Usage: `/delrange [Start_ID] [End_ID]`\nEg: `/delrange 8100 8899`")
            return

        start_id = int(parts[1])
        end_id = int(parts[2])
        
        if start_id > end_id:
            bot.reply_to(message, "❌ Start ID cannot be greater than End ID.")
            return

        # ID များကို String အဖြစ်ပြောင်း၍ List တည်ဆောက်ခြင်း
        ids_to_delete = [str(i) for i in range(start_id, end_id + 1)]
        
        # Confirmation Message
        wait_msg = bot.reply_to(message, f"🗑 Deleting movies from ID `{start_id}` to `{end_id}`...")

        # MongoDB Delete Many
        result = collection.delete_many({'_id': {'$in': ids_to_delete}})
        
        bot.edit_message_text(
            f"✅ **Deletion Complete!**\n\n"
            f"🔢 Range: `{start_id}` - `{end_id}`\n"
            f"🗑 Deleted Count: `{result.deleted_count}` movies.",
            chat_id=message.chat.id,
            message_id=wait_msg.message_id,
            parse_mode="Markdown"
        )

    except ValueError:
        bot.reply_to(message, "❌ IDs must be numbers.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# ==========================================
# REPLACED BROADCAST FUNCTION (Threaded)
# ==========================================

def run_broadcast(admin_chat_id, source_message, text_message):
    """Background Thread ဖြင့် Broadcast လုပ်ခြင်း"""
    users = user_stats.find({}, {'_id': 1})
    total_users = user_stats.count_documents({})
    
    success = 0
    blocked = 0
    deleted = 0
    
    # Admin ကို စပြီဖြစ်ကြောင်း အကြောင်းကြား
    status_msg = bot.send_message(admin_chat_id, f"🚀 Broadcast Started to {total_users} users...")
    
    start_time = time.time()
    
    for user in users:
        user_id = user['_id']
        try:
            if source_message:
                # Reply လုပ်ထားတဲ့ Message ကို Forward/Copy လုပ်မယ်
                bot.copy_message(user_id, admin_chat_id, source_message.message_id)
            elif text_message:
                # စာသားသီးသန့် ပို့မယ်
                bot.send_message(user_id, text_message)
            
            success += 1
            time.sleep(0.05) # Spam မဖြစ်အောင် အနည်းငယ်စောင့်
            
        except Exception as e:
            err = str(e).lower()
            if "blocked" in err:
                blocked += 1
            elif "user is deactivated" in err:
                deleted += 1
                # Account ဖျက်သွားတဲ့ User ကို Database ကနေ ဖယ်ရှားခြင်း (Optional)
                user_stats.delete_one({'_id': user_id})
            pass

        # User 100 ပြီးတိုင်း Admin ကို Update လုပ်မယ်
        if (success + blocked + deleted) % 100 == 0:
            try:
                bot.edit_message_text(
                    f"🚀 Broadcasting...\n\n"
                    f"✅ Sent: {success}\n"
                    f"🚫 Blocked: {blocked}\n"
                    f"🗑 Deleted: {deleted}\n"
                    f"📊 Progress: {success + blocked + deleted}/{total_users}",
                    chat_id=admin_chat_id,
                    message_id=status_msg.message_id
                )
            except: pass

    # ပြီးသွားရင် Final Report ပို့မယ်
    duration = round(time.time() - start_time, 2)
    final_text = (f"🏁 **Broadcast Completed!**\n\n"
                  f"✅ Success: {success}\n"
                  f"🚫 Blocked: {blocked}\n"
                  f"🗑 Deleted Account: {deleted}\n"
                  f"⏱ Duration: {duration}s")
    
    bot.send_message(admin_chat_id, final_text, parse_mode="Markdown")

@bot.message_handler(commands=['broadcast'])
def trigger_broadcast(message):
    if message.from_user.id != ADMIN_ID: return
    
    reply_msg = message.reply_to_message
    text_to_send = message.text.replace('/broadcast', '').strip()
    
    if not reply_msg and not text_to_send:
        bot.reply_to(message, "⚠️ Usage:\n1. Reply to a message with /broadcast\n2. Or type /broadcast [Your Message]")
        return
    
    # Thread အသစ်ဖြင့် စမယ် (Main Bot မလေးအောင်)
    bot.reply_to(message, "🔄 Broadcast logic started in background...")
    Thread(target=run_broadcast, args=(message.chat.id, reply_msg, text_to_send)).start()
    

# BACKUP COMMANDS (Start, Stop, Reset)
# ==========================================

@bot.message_handler(commands=['backup_start'])
def start_backup_handler(message):
    if message.from_user.id != ADMIN_ID: return
    
    # Run နေမနေ စစ်မယ်
    if is_backup_running:
        bot.reply_to(message, "⚠️ **Backup is ALREADY running!**\n\nရပ်ချင်ရင် /backup_stop ကိုနှိပ်ပါ။")
        return

    # မ run သေးရင် Thread အသစ်နဲ့ စမယ်
    Thread(target=run_backup_logic, args=(message.chat.id,)).start()

@bot.message_handler(commands=['backup_stop'])
def stop_backup_handler(message):
    if message.from_user.id != ADMIN_ID: return
    global stop_backup_flag
    
    if not is_backup_running:
        bot.reply_to(message, "⚠️ Backup process is NOT running.")
        return

    stop_backup_flag = True
    bot.reply_to(message, "🛑 Stopping backup process... (Please wait a few seconds)")

@bot.message_handler(commands=['reset_backup_database'])
def reset_backup_data(message):
    if message.from_user.id != ADMIN_ID: return
    
    # Run နေတုန်းဆိုရင် အရင်ရပ်ခိုင်းမယ်
    if is_backup_running:
        bot.reply_to(message, "⚠️ Backup လုပ်နေစဉ် Reset ချ၍ မရပါ။\nအရင်ဆုံး /backup_stop လုပ်ပါ။")
        return

    msg = bot.reply_to(message, "♻️ Database အတွင်းရှိ Backup မှတ်တမ်းဟောင်းများကို ဖျက်နေပါသည်...")

    try:
        # Database ထဲရှိ Movie အားလုံးမှ backup_msg_id ကို ဖျက်မည် ($unset)
        result = collection.update_many(
            {},  # {} ဆိုတာ အားလုံးကို ရွေးတာပါ
            {'$unset': {'backup_msg_id': ""}} 
        )
        
        # (ပြင်ဆင်ချက်) /backup_start ကို `` ကြားထဲထည့်လိုက်ပါသည် (Error မတက်အောင်)
        txt = (f"✅ **Database Reset Successful!**\n\n"
               f"🗑 Cleared Records: `{result.modified_count}`\n\n"
               f"ယခုအခါ `/backup_start` ပြန်နှိပ်ပါက အစကနေ ပြန်လည် Backup လုပ်ပါလိမ့်မည်။")
        
        bot.edit_message_text(txt, chat_id=message.chat.id, message_id=msg.message_id, parse_mode="Markdown")
        
    except Exception as e:
        # Markdown Error တက်ခဲ့ရင် ရိုးရိုးစာနဲ့ ပြန်ပို့ပေးမည့် အရန် Plan
        bot.send_message(message.chat.id, f"✅ Database Reset Done!\nCleared: {result.modified_count}")
        print(f"Error: {e}")
        
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

# ==========================================
# (NEW) EXPLORE / LIST COMMAND
# ==========================================
@bot.message_handler(commands=['list', 'explore', 'top'])
def show_catalog(message):
    # 1. Loading Message (တွက်ချက်ချိန်ကြာနိုင်လို့ပါ)
    wait_msg = bot.reply_to(message, "🔄 Loading Movies Data...")

    try:
        # A. စုစုပေါင်း ဇာတ်ကားအရေအတွက်
        total_movies = collection.count_documents({})

        # B. အကြည့်အများဆုံး Top 10 (View Count အများဆုံးကို ရှာမည်)
        # views မရှိသေးတဲ့ ကားတွေကို 0 လို့ သတ်မှတ်ပြီး ယူပါမယ်
        top_cursor = collection.find().sort('views', -1).limit(10)
        
        top_text = ""
        rank = 1
        for m in top_cursor:
            v_count = m.get('views', 0)
            name = m.get('file_name', 'Unknown')
            # နာမည်ရှည်လွန်းရင် ဖြတ်မည်
            if len(name) > 25: name = name[:25] + "..."
            
            top_text += f"{rank}. {name} - ({v_count} views)\n"
            rank += 1
            
        if not top_text: top_text = "No data yet."

        # C. Categories (File Name ထဲက စာသားကို ရှာပြီး ခွဲခြားခြင်း)
        # Database မှာ Genre မရှိလို့ နာမည်နဲ့ ခန့်မှန်းရပါမယ်
        # Regex 'i' flag က အကြီးအသေး မရွေးပါ (Action = action)
        cat_action = collection.count_documents({'file_name': {'$regex': 'action', '$options': 'i'}})
        cat_drama = collection.count_documents({'file_name': {'$regex': 'drama|romance', '$options': 'i'}})
        cat_horror = collection.count_documents({'file_name': {'$regex': 'horror|ghost', '$options': 'i'}})
        cat_comedy = collection.count_documents({'file_name': {'$regex': 'comedy|funny', '$options': 'i'}})

        # Report စာသား ပြင်ဆင်ခြင်း
        final_msg = (
            f"📊 **Movie Database Report** 📊\n\n"
            f"🎬 **Total Movies:** `{total_movies}`\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"🏆 **Top 10 Most Viewed:**\n"
            f"{top_text}\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"📂 **Categories (Estimate):**\n"
            f"👊 Action: `{cat_action}`\n"
            f"🎭 Drama/Romance: `{cat_drama}`\n"
            f"👻 Horror: `{cat_horror}`\n"
            f"😂 Comedy: `{cat_comedy}`\n"
            f"⚠️ *Note: Categories are estimated from filenames.*"
        )
        
        # ရလာတဲ့ Result ကို ပြန်ပို့မည်
        bot.edit_message_text(final_msg, chat_id=message.chat.id, message_id=wait_msg.message_id, parse_mode="Markdown")

    except Exception as e:
        bot.edit_message_text(f"❌ Error: {e}", chat_id=message.chat.id, message_id=wait_msg.message_id)

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
# (3) SAVE MOVIE (UPDATED FOR MULTI-CHANNEL)
# ==========================================
@bot.message_handler(content_types=['video', 'document'], func=lambda m: m.from_user.id == ADMIN_ID)
def save_movie(message):
    # Forward ဟုတ်မဟုတ် စစ်မယ်
    if not message.forward_from_message_id:
        return

    # 🔥 Check if Forward is from one of the Allowed SOURCE_CHANNELS
    forward_chat_id = message.forward_from_chat.id if message.forward_from_chat else None
    
    # အကယ်၍ Forward လုပ်တဲ့ Channel က စာရင်းထဲမှာ မရှိရင် Admin ကို သတိပေးမယ်
    if forward_chat_id not in SOURCE_CHANNELS:
        bot.reply_to(message, f"⚠️ This channel ID `{forward_chat_id}` is not in SOURCE_CHANNELS list.")
        return

    caption = message.caption if message.caption else ""
    match = re.search(r'^\s*(\d+)', caption) 
    
    if match:
        custom_id = match.group(1)
        file_name = caption 
        
        data = {
            '_id': custom_id, 
            'msg_id': message.forward_from_message_id, 
            'channel_id': forward_chat_id,  # 🔥 Save Source Channel ID (ဘယ် Channel ကလဲဆိုတာ မှတ်မယ်)
            'file_name': file_name
        }
        
        collection.update_one({'_id': custom_id}, {'$set': data}, upsert=True)
        bot.reply_to(message, f"✅ **Saved from Channel!**\n🆔 ID: `{custom_id}`\n📢 Source: `{forward_chat_id}`", parse_mode="Markdown")
    
    else:
        bot.reply_to(message, "⚠️ **Failed!** No ID found in caption.")
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

# (NEW) USER USEFUL COMMANDS
# ==========================================

# 1. User Profile & Limit Check
@bot.message_handler(commands=['me', 'profile'])
def check_my_profile(message):
    user_id = message.from_user.id
    user = user_stats.find_one({'_id': user_id})
    
    if not user:
        bot.reply_to(message, "⚠️ User Data Not Found! Please type /start")
        return

    status = user.get('status', 'free').upper()
    daily_count = user.get('usage', {}).get('daily_count', 0)
    
    # Text ပြင်ဆင်ခြင်း
    if status == 'VIP':
        expiry = user.get('vip_info', {}).get('expiry', 0)
        exp_date = datetime.fromtimestamp(expiry).strftime('%d/%m/%Y') if expiry else "Unknown"
        limit_txt = "✅ Unlimited Access"
        status_txt = f"💎 VIP Member (Exp: {exp_date})"
    else:
        limit_txt = f"📊 Daily Usage: {daily_count} / {FREE_DAILY_LIMIT}"
        status_txt = "🐼 Free Member"

    msg = (f"👤 **User Profile**\n\n"
           f"🆔 ID: `{user_id}`\n"
           f"🏷 Status: {status_txt}\n"
           f"{limit_txt}\n\n"
           f"💡 Upgrade to VIP: /vip")
    
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

# 2. VIP Pricing Shortcut
@bot.message_handler(commands=['vip', 'plan'])
def show_vip_plans(message):
    markup = types.InlineKeyboardMarkup()
    btn = types.InlineKeyboardButton("💎 Buy Now (Contact Admin)", url="https://t.me/moviestoreadmin") # Link ပြင်ပါ
    markup.add(btn)
    
    txt = (
        "💎 **VIP Premium Plan** 💎\n\n"
        "✅ ကြော်ငြာမရှိ၊ Daily Limit မရှိ။\n"
        "✅ Direct File ဖြင့် စိတ်ကြိုက်ကြည့်ရှုနိုင်မည်။\n\n"
        "💰 **Pricing:**\n"
        "• 1 Month  -  3,000 MMK\n"
        "• 6 Month  - 10,000 MMK\n"
        "• Lifetime - 20,000 MMK\n\n"
        "Payment: KBZPay, WavePay"
    )
    bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")

# 3. Help / Guide
@bot.message_handler(commands=['help'])
def help_guide(message):
    txt = (
        "❓ **How to use?**\n\n"
        "1️⃣ **Search Movie:**\n"
        "Channel ထဲရှိ Movie ID နံပါတ်ကို ရိုက်ထည့်ပါ။\n"
        "(Example: `1001`)\n\n"
        "2️⃣ **Check Profile:**\n"
        "မိမိ Limit ကြည့်ရန် `/me` ဟု ရိုက်ပါ။\n\n"
        "3️⃣ **Contact Admin:**\n"
        "အခက်အခဲရှိပါက @moviestoreadmin သို့ ဆက်သွယ်ပါ။"
    )
    bot.send_message(message.chat.id, txt, parse_mode="Markdown")
        
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
               f"{vip_dates}\n\n" 
               f"==============\n"
               f"ဇာတ်ကား ID နှင့် ပိုစတာများကြည့်ရန်\n"
               f"👑 @moviesbydatahouse\n\n"
               f"ရရှိနိုင်သော telegram services များစုံစမ်းရန်\n"
               f"👑 Admin - @moviestoreadmin\n"
               
               f"🎬ကြည့်ရှုလိုသော Movie ID နံပါတ်ပို့ပေးပါ")
        
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

    # အရင် save ထားတဲ့ ကားဟောင်းတွေမှာ channel_id မပါရင် Default CHANNEL_3 ကိုသုံးမယ် (Error မတက်အောင်ပါ)
    try:
        source_chat_id = movie.get('channel_id', CHANNEL_3_ID)
        
        sent_msg = bot.copy_message(
            chat_id=user_id,
            from_chat_id=source_chat_id, # 🔥 Dynamic Channel ID (ပြောင်းလိုက်တဲ့နေရာ)
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
        
        # 🔥 (NEW) MOVIE VIEW COUNT UPDATE 🔥
        # ဒီဇာတ်ကားကို ကြည့်သူ ၁ ယောက်တိုးမယ်
        collection.update_one(
            {'_id': movie_id},
            {'$inc': {'views': 1}}
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

# ========================================
    
# ==========================================
# (6) SERVER & AUTO DELETE WORKER
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "Bot Running"

def run_http():
    app.run(host='0.0.0.0', port=8000)

def auto_delete_worker():
    """
    Auto Delete System (Optimized)
    """
    print("♻️ Auto Delete Worker Started...")
    while True:
        try:
            now = time.time()
            
            # (1) ဖျက်ရမည့် စာများကို ရှာမည် (Batch Size 100)
            tasks = list(delete_queue.find({"delete_time": {"$lte": now}}).limit(100))
            
            if not tasks:
                time.sleep(10) # ဖျက်စရာမရှိရင် ခဏနားမည်
                continue

            ids_to_remove_from_db = []

            for msg in tasks:
                try:
                    # Telegram Channel/Chat ထဲမှ စာကို ဖျက်မည်
                    bot.delete_message(msg['chat_id'], msg['message_id'])
                except Exception as e:
                    # User Block သွားရင်လည်း Database ထဲကတော့ ဖျက်ရမည်
                    pass
                
                # Database မှ ဖျက်ရန် ID မှတ်ထားမည်
                ids_to_remove_from_db.append(msg['_id'])
                
                # API Spam မဖြစ်အောင် အနည်းငယ်စောင့်မည်
                time.sleep(0.05) 

            # (2) Database ထဲမှ Bulk Delete လုပ်မည် (ပိုမြန်သည်)
            if ids_to_remove_from_db:
                delete_queue.delete_many({'_id': {'$in': ids_to_remove_from_db}})
                print(f"♻️ Auto Deleted: {len(ids_to_remove_from_db)} messages")

        except Exception as e:
            print(f"❌ Auto Delete Error: {e}")
            time.sleep(5)

def keep_alive():
    t1 = Thread(target=run_http)
    t2 = Thread(target=auto_delete_worker)
    t1.start()
    t2.start()

# ==========================================
# (7) SET MENU COMMANDS (AUTO)
# ==========================================
def set_bot_commands():
    # ၁. User များအတွက် Command အသစ်များ
    user_commands = [
        types.BotCommand("start", "🏠 Home / Restart"),
        types.BotCommand("list", "🔥 Top Movies"),
        types.BotCommand("me", "👤 My Profile & Limit"),  # <--- Added
        types.BotCommand("vip", "💎 VIP Pricing"),        # <--- Added
        types.BotCommand("help", "❓ How to use"),        # <--- Added
    ]
    
    # ၂. Admin တစ်ယောက်တည်းသာ မြင်ရမည့် Command များ
    admin_commands = [
        # User Commands များကိုလည်း Admin မြင်အောင် ထည့်ထားပေးခြင်း
        types.BotCommand("start", "Restart Bot"),
        types.BotCommand("list", "Explore Movies"),
        
        # Admin Only Commands
        types.BotCommand("stats", "View Server Statistics"),
        types.BotCommand("users", "Get User List File"),
        types.BotCommand("broadcast", "Broadcast Message"),
        types.BotCommand("addvip", "Add VIP User"),
        types.BotCommand("delvip", "Remove VIP User"),
        types.BotCommand("backup_start", "Start Backup Process"),
        types.BotCommand("backup_stop", "Stop Backup Process"),
    ]

    try:
        # User အားလုံးအတွက် (Default Scope)
        bot.set_my_commands(user_commands, scope=types.BotCommandScopeDefault())
        
        # Admin ID အတွက်သီးသန့် (Chat Scope)
        # ADMIN_ID က environment variable ကနေ ယူထားတဲ့ int ဖြစ်ရပါမယ်
        bot.set_my_commands(admin_commands, scope=types.BotCommandScopeChat(chat_id=ADMIN_ID))
        
        print("✅ Bot Commands Menu Updated!")
    except Exception as e:
        print(f"❌ Failed to set commands: {e}")

# ==========================================
# RUN SECTION
# ==========================================
if __name__ == "__main__":
    keep_alive()      # Web Server Start
    set_bot_commands() # <--- ဒီ Function ကို ဒီနေရာမှာ ခေါ်ပေးရပါမယ်
    print("🤖 Bot Started...")
    bot.infinity_polling()


