import motor.motor_asyncio
from pyrogram import Client, filters
from pyrogram.errors import UserNotParticipant, FloodWait
import logging
from flask import Flask
from threading import Thread
import os
import asyncio

# --- Config ---
API_ID = 35287678
API_HASH = "0b665ada43d12930d92f00827edf79da"
BOT_TOKEN = "8221461909:AAGZB6sR1evyaqivvQ4WBjNTLxkEpo-m8nU"
MONGO_URI = "mongodb+srv://kyawmintuntg_admin_db:Wwwkmt285@cluster0.vll2nc2.mongodb.net/?appName=Cluster0"

MEMBER_CHANNEL_ID = -1003193370007
PORTAL_CHANNEL_ID = -1003276114220 
OWNER_ID = 7812553563

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Bot Client ---
app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- Database ---
db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = db_client["movie_db"]
collection = db["movies"]

# --- Health Check Server (For Koyeb) ---
web_app = Flask('')
@web_app.route('/')
def home(): return "Bot is Alive!"

def run_web():
    port = int(os.environ.get("PORT", 8000))
    web_app.run(host='0.0.0.0', port=port)

# --- Handlers ---
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text("👋 မင်္ဂလာပါ! ရုပ်ရှင်ရှာဖွေရန် နာမည် သို့မဟုတ် ID ရိုက်ပို့ပေးပါ။")

@app.on_message(filters.command("index") & filters.user(OWNER_ID))
async def index_files(client, message):
    status = await message.reply_text("🔄 Indexing စတင်နေပါပြီ...")
    count = 0
    try:
        async for msg in client.get_chat_history(PORTAL_CHANNEL_ID, limit=1000):
            if msg.video and msg.caption:
                await collection.update_one(
                    {"msg_id": msg.id},
                    {"$set": {"file_name": msg.caption.lower(), "msg_id": msg.id}},
                    upsert=True
                )
                count += 1
        await status.edit(f"✅ စုစုပေါင်း ရုပ်ရှင် {count} ကား မှတ်သားပြီးပါပြီ။")
    except Exception as e:
        await status.edit(f"❌ Error: {e}")

@app.on_message(filters.text & filters.private)
async def handle_search(client, message):
    user_id = message.from_user.id
    # Force Join Check
    try:
        await client.get_chat_member(MEMBER_CHANNEL_ID, user_id)
    except UserNotParticipant:
        return await message.reply_text("⛔️ Member ဝင်ရန်: " + str(MEMBER_CHANNEL_ID))
    except Exception: pass

    query = message.text.lower()
    results = collection.find({"file_name": {"$regex": query}})
    found = False
    async for movie in results:
        found = True
        try:
            await client.copy_message(
                chat_id=message.chat.id,
                from_chat_id=PORTAL_CHANNEL_ID,
                message_id=movie["msg_id"]
            )
        except: pass

    if not found:
        await message.reply_text("🔍 ရှာမတွေ့ပါ။")

# --- Main Run ---
if __name__ == "__main__":
    # Web server ကို background မှာ run မယ်
    Thread(target=run_web, daemon=True).start()
    
    # Bot ကို run မယ်
    print("🚀 Bot is starting...")
    app.run()


