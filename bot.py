import motor.motor_asyncio
from pyrogram import Client, filters, enums  # enums ကို ဤနေရာတွင် import လုပ်ထားရပါမည်
from pyrogram.errors import UserNotParticipant
import logging
from flask import Flask
from threading import Thread
import os

# --- (၁) Config အပိုင်း ---
API_ID = 35287678
API_HASH = "0b665ada43d12930d92f00827edf79da"
BOT_TOKEN = "8221461909:AAGZB6sR1evyaqivvQ4WBjNTLxkEpo-m8nU"
# Password ကို kyaw123 အဖြစ် အသေအချာ ထည့်ပေးထားသည်
MONGO_URI = "mongodb+srv://kyawmintuntg_admin_db:Www.285476@cluster0.vll2nc2.mongodb.net/?appName=Cluster0"

MEMBER_CHANNEL_ID = -1003193370007
PORTAL_CHANNEL_ID = -1003276114220
OWNER_ID = 7812553563

# --- (၂) Bot Client သတ်မှတ်ခြင်း ---
app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Logging Setup
logging.basicConfig(level=logging.INFO)

# MongoDB Setup
db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = db_client["movie_db"]
collection = db["movies"]

# --- (၃) Web Server Setup (Koyeb အတွက်) ---
web_app = Flask('')
@web_app.route('/')
def home(): return "Bot is Alive!"

def run_web():
    port = int(os.environ.get("PORT", 8000))
    web_app.run(host='0.0.0.0', port=port)

def keep_alive():
    Thread(target=run_web).start()

# --- (၄) Bot Commands ---

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text("👋 မင်္ဂလာပါ! ရုပ်ရှင်ရှာဖွေရန် နာမည် သို့မဟုတ် ID ရိုက်ပို့ပေးပါ။")

@app.on_message(filters.command("index") & filters.user(OWNER_ID))
async def index_files(client, message):
    status = await message.reply_text("🔄 Indexing စတင်နေပါပြီ... ခဏစောင့်ပါ။")
    count = 0
    try:
        # filter နေရာတွင် enums ကို အသုံးပြုထားပါသည်
        async for msg in client.get_chat_history(PORTAL_CHANNEL_ID, filter=enums.MessagesFilter.VIDEO):
            if msg.caption:
                await collection.update_one(
                    {"msg_id": msg.id},
                    {"$set": {"file_name": msg.caption.lower(), "msg_id": msg.id}},
                    upsert=True
                )
                count += 1
        await status.edit(f"✅ လုပ်ငန်းပြီးဆုံးပါပြီ။ စုစုပေါင်း ရုပ်ရှင် {count} ကားကို မှတ်သားပြီးပါပြီ။")
    except Exception as e:
        await status.edit(f"❌ Error: {e}")
        logging.error(f"Index error: {e}")

@app.on_message(filters.text & filters.private)
async def handle_search(client, message):
    user_id = message.from_user.id
    try:
        await client.get_chat_member(MEMBER_CHANNEL_ID, user_id)
    except UserNotParticipant:
        return await message.reply_text("⛔️ သင်သည် Member မဟုတ်သေးပါ။ Channel တွင် Member အရင်ဝင်ပေးပါ။")
    except Exception as e:
        # Peer id invalid ဖြစ်နေပါက အောက်ပါအတိုင်း ပြန်ပြောပါမည်
        logging.error(f"Member check error: {e}")
        return

    query = message.text.lower()
    results = collection.find({"file_name": {"$regex": query}})
    
    found = False
    async for movie in results:
        found = True
        try:
            await client.copy_message(
                chat_id=message.chat.id,
                from_chat_id=PORTAL_CHANNEL_ID,
                message_id=movie["msg_id"],
                protect_content=True
            )
        except Exception as e:
            logging.error(f"Copy message error: {e}")

    if not found:
        await message.reply_text("🔍 တောင်းပန်ပါတယ်။ ရုပ်ရှင်ရှာမတွေ့ပါ။")

# --- (၅) Main Execution ---
if __name__ == "__main__":
    keep_alive()
    print("Bot is starting...")
    app.run()



