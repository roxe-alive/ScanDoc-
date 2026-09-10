from dotenv import load_dotenv
import os
import time


load_dotenv("config.env")

# Retrieve environment variables with safe defaults
API_ID = os.environ.get('API_ID')
API_HASH = os.environ.get('API_HASH')
BOT_TOKEN = os.environ.get('BOT_TOKEN')
BOT_NAME = os.environ.get('BOT_NAME',"Roxe Beta")
SUDO = list(map(int, os.environ.get("SUDO", "0").split(',')))
PORT = int(os.environ.get('PORT', 8080))  # Default to 8080 if not set
OG_BOT_NAME = ('𝑅𝒐𝒛𝒆𝒔𓆩♡𓆪')
UPTIME_URL = os.environ.get("UPTIME_URL") # Don't Edit
if not API_ID or not API_HASH or not BOT_TOKEN:
    raise ValueError("Missing required environment variables! Check your .env file.")