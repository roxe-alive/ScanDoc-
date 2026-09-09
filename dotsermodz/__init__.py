# Version: 1.0 Beta
# ©️ 2021 DOTSERMODZ ALL RIGHTS RESERVED
from pyrogram import Client
from config import (
    API_ID,
    API_HASH,
    BOT_TOKEN,
)



# Connect to MongoDB for accessing plugin database


app = Client(
    "dotsermodz-basebot",
    bot_token=BOT_TOKEN,
    api_id=API_ID,
    api_hash=API_HASH,
    plugins=dict(root="dotsermodz"), 
)

