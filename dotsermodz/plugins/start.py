# pyrefly: ignore [missing-import]
from pyrogram import Client, filters
from dotsermodz import app

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("Hello, I am a bot that can convert EAN to QR code. Send me an image with EAN code and I will convert it to QR code.")