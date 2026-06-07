"""Gửi bản tin qua Telegram bot. Tự chia nhỏ tin >4096 ký tự."""
import os
import requests

API = "https://api.telegram.org/bot{token}/sendMessage"
LIMIT = 4000  # dưới mức 4096 của Telegram cho an toàn


def send(text: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = API.format(token=token)

    chunks = [text[i:i + LIMIT] for i in range(0, len(text), LIMIT)] or ["(rỗng)"]
    for chunk in chunks:
        r = requests.post(url, data={
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }, timeout=30)
        if r.status_code != 200:
            print(f"[telegram] lỗi {r.status_code}: {r.text}")
            r.raise_for_status()
