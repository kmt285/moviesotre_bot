import motor.motor_asyncio
from pyrogram import Client, filters
from pyrogram.errors import UserNotParticipant
import logging
from flask import Flask
from threading import Thread
import os

# --- (၁) အချက်အလက်များ သတ်မှတ်ခြင်း ---
# MongoDB URL ထဲက <db_password> နေရာမှာ သင့် Password အစစ်ကို ပြောင်းထည့်ပေးထားပါတယ်
API_ID = 35287678
API_HASH = "0b665ada43d12930d92f00827edf79da"
BOT_TOKEN = "8221461909:AAGZB6sR1evyaqivvQ4WBjNTLxkEpo-m8nU"
# <db_password> နေရာမှာ kyaw123 လို့ ပြောင်းလဲပြင်ဆင်ပေးထားပါတယ်
MONGO_URI = "mongodb+srv://kyawmintuntg_admin_db:Www.kmt285476.com@cluster0.vll2nc2.mongodb.net/?appName=Cluster0"

MEMBER_CHANNEL_ID = -1003193370007
PORTAL_CHANNEL_ID = -1003216556662
OWNER_ID = 7812553563

# --- (၂) Bot Client ကို အပေါ်ဆုံးမှာ အရင် သတ်မှတ်ရပါမည် (အရေးကြီးဆုံး) ---
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
def home():
    return "Bot is Running!"

def run_web():
    # Koyeb Port ကို အသုံးပြုရန်
    port = int(os.environ.get("PORT", 8000))
    web_app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# --- (၄) Bot Functions & Commands ---

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text(
        "👋 မင်္ဂလာပါ! ရုပ်ရှင်ရှာဖွေရေး Bot မှ ကြိုဆိုပါတယ်။\n\n"
        "🔎 ရုပ်ရှင်ရှာဖွေရန် နာမည် သို့မဟုတ် ID (ဥပမာ- 15092) ကို ရိုက်ပို့ပေးပါ။"
    )

@app.on_message(filters.command("index") & filters.user(OWNER_ID))
async def index_files(client, message):
    status = await message.reply_text("🔄 Indexing စတင်နေပါပြီ... ခဏစောင့်ပါ။")
    count = 0
    # Portal Channel ထဲက ဗီဒီယိုများကို ရှာဖွေမှတ်သားခြင်း
    async for msg in client.search_messages(PORTAL_CHANNEL_ID, filter="video"):
        if msg.caption:
            await collection.update_one(
                {"msg_id": msg.id},
                {"$set": {"file_name": msg.caption.lower(), "msg_id": msg.id}},
                upsert=True
            )
            count += 1
    await status.edit(f"✅ လုပ်ငန်းပြီးဆုံးပါပြီ။ စုစုပေါင်း ရုပ်ရှင် {count} ကားကို မှတ်သားပြီးပါပြီ။")

@app.on_message(filters.text & filters.private)
async def handle_search(client, message):
    user_id = message.from_user.id
    # Member ဟုတ်မဟုတ် စစ်ဆေးခြင်း
    try:
        await client.get_chat_member(MEMBER_CHANNEL_ID, user_id)
    except UserNotParticipant:
        return await message.reply_text("⛔️ သင်သည် Member မဟုတ်သေးပါ။ Channel တွင် Member အရင်ဝင်ပေးပါ။")
    except Exception as e:
        logging.error(f"Member check error: {e}")
        return

    query = message.text.lower()
    # နာမည်တူတာကို MongoDB ထဲမှာ ရှာဖွေခြင်း
    results = collection.find({"file_name": {"$regex": query}})
    
    found = False
    async for movie in results:
        found = True
        try:
            # ဖိုင်ကို User ထံသို့ Copy ကူးပို့ခြင်း (Forward ပိတ်၍)
            await client.copy_message(
                chat_id=message.chat.id,
                from_chat_id=PORTAL_CHANNEL_ID,
                message_id=movie["msg_id"],
                protect_content=True
            )
        except Exception as e:
            logging.error(f"Copy message error: {e}")

    if not found:
        await message.reply_text("🔍 တောင်းပန်ပါတယ်။ ရုပ်ရှင်ရှာမတွေ့ပါ။ နာမည်/ID မှန်ကန်အောင် ပြန်ရိုက်ကြည့်ပါ။")

# --- (၅) Main Execution (ဤနေရာတွင် app.run() ကို ခေါ်ရပါမည်) ---
if __name__ == "__main__":
    keep_alive()  # Flask server ကို အရင်စမည်
    print("Bot စတင်လည်ပတ်နေပါပြီ...")
    app.run()     # Bot စတင်မည်

