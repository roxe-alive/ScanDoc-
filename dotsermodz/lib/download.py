# Version: 1.0 Beta
# ©️ 2025 DOTSERMODZ ALL RIGHTS RESERVED
import os,  re, random, requests
from urllib.parse import urlparse, parse_qs ,quote_plus


# qr code
def fetch_qr(text):
    # Encode text safely for URLs
    encoded_text = quote_plus(text)
    api_url = f"https://quickchart.io/qr?text={encoded_text}"
    
    try:
        response = requests.get(api_url, timeout=10)
        if response.status_code == 200:
            file_path = f"qr_{encoded_text}.png"
            with open(file_path, "wb") as file:
                file.write(response.content)
            return file_path
    except Exception as e:
        print(f"[QR ERROR] {e}")
    return None


def qr_del(file_path):
    if os.path.exists(file_path):
        os.remove(file_path)

