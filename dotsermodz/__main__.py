# Version: 1.0 Beta
# ©️ 2025 DOTSERMODZ ALL RIGHTS RESERVED
from dotsermodz.keep import web 
from config import UPTIME_URL
from pyrogram import idle
import logging
import asyncio
import requests 
from dotsermodz import app

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# Function to start the bot and keep it alive
async def main():
     await app.start() 
     web.yuji_itadori()
     if UPTIME_URL:                                    # Edit there if you are not using render.com or not required    
        asyncio.create_task(web.luffy(UPTIME_URL))     # Keep pinging the host Only if bot is hosted on render.com                
     await idle()      

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())          
