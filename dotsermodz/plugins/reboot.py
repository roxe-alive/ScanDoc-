# Version: 1.0 Beta
# ©️ 2025 DOTSERMODZ ALL RIGHTS RESERVED
from dotsermodz import app
from config import BOT_NAME , SUDO
from pyrogram import filters
import os
import sys
import logging
import asyncio
from dotsermodz import app 
from subprocess import getoutput as run
import os
import io

# Configure logging
logging.basicConfig(level=logging.INFO)

# Define the command for rebooting the bot
@app.on_message(filters.command("reboot") & filters.user(SUDO))
async def reboot_bot(client, message):
    await message.react("🦄")
    await message.reply_text(f"Rebooting the bot...")
    os.execl(sys.executable, sys.executable, *sys.argv)
    logging.info("Bot is restarting...")


# Command for shutting down the bot
@app.on_message(filters.command("shutdown") & filters.user(SUDO))
async def shutdown_bot(client, message):
    await message.reply_text(f"Reboot now to prevent shutdown....")
    countdown = 5
    countdown_message = await message.reply_text("⚠️ **Warning!** Shutting down in 5 seconds... ⏳")

    for i in range(countdown, 0, -1):
        await countdown_message.edit_text(f"⚠️ **Warning!** {i} seconds remaining before shutting down... ⏳")
        await asyncio.sleep(1) 

    await message.reply_text(f"The bot is shutting down now... Goodbye! 😢")
    await app.stop()
    logging.info("Bot is shutting down...")


# Shell command to run shell commands  
@app.on_message(filters.command(["cmd", "shell"]) & filters.user(SUDO))
async def shell(client, message):    
    if len(message.command) < 2:
        await message.reply("Give an input!")
        return
    code = message.text.split(None, 1)[1]
    message_text = await message.reply_text("Running")
    output = run(code)
    if len(output) > 4096:
        with io.BytesIO(str.encode(output)) as out_file:
            out_file.name = "shell.txt"
            await message.reply_document(
                document=out_file, disable_notification=True
            )
            await message_text.delete()
    else:
        await message_text.edit(f"**{BOT_NAME} **\nOutput: ```\n\n{output}```")