import motor.motor_asyncio
from pyrogram import Client, filters
from pyrogram.errors import UserNotParticipant
import logging
from flask import Flask
from threading import Thread
import os

# Web Server ဆောက်ခြင်း (Koyeb အတွက်)
web_app = Flask('')

@web_app.route('/')
def home():
    return "Bot is Running!"

def run():
    # Koyeb သည် $PORT အား အသုံးပြုသောကြောင့် ပတ်ဝန်းကျင်မှ Port ကိုယူပါ
    port = int(os.environ.get("PORT", 8000))
    web_app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- သင်၏ အရင် Code ဟောင်းများ ဤအောက်တွင် ဆက်လက်ရှိရမည် ---
# ... (Client, Mongo, Start command စသည်တို့)

if __name__ == "__main__":
    keep_alive()  # Web server ကို အရင်ဖွင့်မည်
    print("Bot is starting...")
    app.run()     # Bot ကို run မည်

# --- ပြင်ဆင်ရန် အချက်အလက်များ (Config) ---
API_ID = 35287678               # သင့် API ID
API_HASH = "0b665ada43d12930d92f00827edf79da"    # သင့် API Hash
BOT_TOKEN = "8221461909:AAGZB6sR1evyaqivvQ4WBjNTLxkEpo-m8nU"   # သင့် Bot Token
MONGO_URI = "mongodb+srv://kyawmintuntg_admin_db:<db_password>@cluster0.vll2nc2.mongodb.net/?appName=Cluster0" # MongoDB Connection String

MEMBER_CHANNEL_ID = -1003193370007   # Member ဝင်ထားသူများရှိသော Channel (Restrict content: ON ထားသောနေရာ)
PORTAL_CHANNEL_ID = -1003216556662   # ရုပ်ရှင်ဖိုင်များရှိသော Channel (Restrict content: OFF ထားသောနေရာ)
OWNER_ID = 7812553563            # သင့်ရဲ့ Telegram User ID (Index လုပ်ရန်အတွက်သာ)

# Logging Setup (Error များ စစ်ဆေးရန်)
logging.basicConfig(level=logging.INFO)

# MongoDB Setup
db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = db_client["movie_db"]
collection = db["movies"]

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ၁။ Start Command
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text(
        "👋 မင်္ဂလာပါ! ရုပ်ရှင်ရှာဖွေရေး Bot မှ ကြိုဆိုပါတယ်။\n\n"
        "🔎 ရုပ်ရှင်ရှာဖွေရန် နာမည် သို့မဟုတ် ID (ဥပမာ- 15092) ကို ရိုက်ပို့ပေးပါ။"
    )

# ၂။ Indexing လုပ်ခြင်း (Portal Channel ထဲမှဖိုင်များကို Database ထဲမှတ်သားခြင်း)
@app.on_message(filters.command("index") & filters.user(OWNER_ID))
async def index_files(client, message):
    status = await message.reply_text("🔄 Indexing စတင်နေပါပြီ... ခဏစောင့်ပါ။")
    count = 0
    
    # Portal Channel ထဲမှာရှိသမျှ Video များကို ရှာဖွေမှတ်သားခြင်း
    async for msg in client.search_messages(PORTAL_CHANNEL_ID, filter="video"):
        if msg.caption:
            await collection.update_one(
                {"msg_id": msg.id},
                {"$set": {"file_name": msg.caption.lower(), "msg_id": msg.id}},
                upsert=True
            )
            count += 1
    
    await status.edit(f"✅ လုပ်ငန်းပြီးဆုံးပါပြီ။ စုစုပေါင်း ရုပ်ရှင် {count} ကားကို မှတ်သားပြီးပါပြီ။")

# ၃။ Search နှင့် Secure Delivery Logic
@app.on_message(filters.text & filters.private)
async def handle_search(client, message):
    user_id = message.from_user.id
    
    # Member ဟုတ်မဟုတ် အရင်စစ်ဆေးခြင်း
    try:
        await client.get_chat_member(MEMBER_CHANNEL_ID, user_id)
    except UserNotParticipant:
        return await message.reply_text("⛔️ သင်သည် Member မဟုတ်သေးပါ။ Channel တွင် Member အရင်ဝင်ပေးပါ။")
    except Exception as e:
        logging.error(f"Member check error: {e}")
        return

    query = message.text.lower()
    
    # MongoDB ထဲတွင် ရိုက်လိုက်သောစာသား သို့မဟုတ် ID ပါဝင်သည်များကို ရှာခြင်း
    results = collection.find({"file_name": {"$regex": query}})
    
    found = False
    async for movie in results:
        found = True
        try:
            # Portal Channel မှတစ်ဆင့် User ဆီသို့ Copy ကူးပို့ခြင်း
            await client.copy_message(
                chat_id=message.chat.id,
                from_chat_id=PORTAL_CHANNEL_ID,
                message_id=movie["msg_id"],
                protect_content=True  # 👈 အရေးကြီးဆုံးအပိုင်း - Forward လုပ်မရအောင် ပိတ်ခြင်း
            )
        except Exception as e:
            logging.error(f"Copy message error: {e}")

    if not found:
        await message.reply_text("🔍 တောင်းပန်ပါတယ်။ ရုပ်ရှင်ရှာမတွေ့ပါ။ နာမည်/ID မှန်ကန်အောင် ပြန်ရိုက်ကြည့်ပါ။")

print("Bot စတင်လည်ပတ်နေပါပြီ...")

app.run()

