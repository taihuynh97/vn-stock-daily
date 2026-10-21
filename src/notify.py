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
        # Không để URL (chứa token) lọt vào log: lỗi của requests in nguyên URL,
        # bản mã hoá ":" → "%3A" GitHub không che được (repo public 21/10/2026).
        try:
            r = requests.post(url, data={
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }, timeout=30)
        except requests.RequestException as e:
            raise RuntimeError(f"[telegram] lỗi mạng: {type(e).__name__}") from None
        if r.status_code != 200:
            msg = f"[telegram] lỗi {r.status_code}: {_scrub(r.text, token)}"
            print(msg)
            raise RuntimeError(msg)


def _scrub(s: str, token: str) -> str:
    for t in (token, requests.utils.quote(token, safe="")):
        s = s.replace(t, "***")
    return s
