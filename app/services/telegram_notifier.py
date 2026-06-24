import logging
import urllib.request
import json
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    """Send a message via Telegram Bot API. Returns True on success."""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.warning("Telegram send failed: %s", e)
        return False

def notify_critical(bot_token: str | None, chat_id: str | None, title: str, body: str) -> None:
    if not bot_token or not chat_id:
        return
    text = f"<b>🏥 Склад — {title}</b>\n{body}"
    send_telegram_message(bot_token, chat_id, text)
