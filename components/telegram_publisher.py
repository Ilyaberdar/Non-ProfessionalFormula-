from __future__ import annotations
import asyncio
import json
import time 
import urllib.error  
import urllib.request
from html import escape as html_escape


class TelegramPublisher:
    def __init__(self, telegram_token: str, chat_id: str):
        self.token = telegram_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{telegram_token}"

    async def _post(self, method: str, payload: dict):
        return await asyncio.to_thread(self._post_sync, method, payload)

    def _post_sync(self, method: str, payload: dict):
        last_error = None
        for attempt in range(3):
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url=f"{self.base_url}/{method}",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read().decode("utf-8")
                    parsed = json.loads(body)
                    if not parsed.get("ok"):
                        raise RuntimeError(f"Telegram API error: {parsed}")
                    return parsed.get("result")
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_error = e
                if attempt == 2:
                    break
                time.sleep(2 * (attempt + 1))
        raise last_error if last_error else RuntimeError("Unknown Telegram API error")

    async def publish(self, title: str, full_output: str, article_url: str):
        try:
            safe_title = html_escape(title or "")
            safe_output = html_escape(full_output or "")
            safe_link = html_escape(article_url or "")
            source_link = f'\n\n<a href="{safe_link}">Читать источник</a>' if safe_link else ""
            text = f"<b>{safe_title}</b>\n\n{safe_output}{source_link}"
            await self._post(
                "sendMessage",
                {
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        except Exception as e:
            print(f"[TelegramPublisher] Error: {e}")

    async def send_log(self, log: str, chat_id: str | None = None, reply_to_message_id: int | None = None):
        try:
            payload = {
                "chat_id": chat_id or self.chat_id,
                "text": log,
                "parse_mode": "HTML",
            }
            if reply_to_message_id is not None:
                payload["reply_to_message_id"] = reply_to_message_id
            await self._post(
                "sendMessage",
                payload,
            )
        except Exception as e:
            print(f"[TelegramPublisher] Error: {e}")

    async def send_review(self, review_chat_id: str, text: str, article_id: str):
        keyboard = [
            [
                {"text": "Accept", "callback_data": f"accept:{article_id}"},
                {"text": "Decline", "callback_data": f"decline:{article_id}"},
            ],
            [
                {"text": "Next", "callback_data": "next"},
                {"text": "Skip all", "callback_data": "skipall"},
            ],
        ]
        return await self.send_inline_message(review_chat_id, text, keyboard)

    async def send_inline_message(self, chat_id: str, text: str, buttons: list[list[dict]]):
        try:
            return await self._post(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": {"inline_keyboard": buttons},
                    "disable_web_page_preview": True,
                },
            )
        except Exception as e:
            print(f"[TelegramPublisher] Error: {e}")
            return None

    async def edit_inline_message(self, chat_id: str, message_id: int, text: str, buttons: list[list[dict]]):
        try:
            return await self._post(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": {"inline_keyboard": buttons},
                    "disable_web_page_preview": True,
                },
            )
        except Exception as e:
            print(f"[TelegramPublisher] Error: {e}")
            return None

    async def get_updates(self, offset: int | None = None, timeout: int = 20):
        payload = {"timeout": timeout, "allowed_updates": ["callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        try:
            return await self._post("getUpdates", payload)
        except Exception as e:
            print(f"[TelegramPublisher] Error: {e}")
            return []

    async def answer_callback(self, callback_query_id: str, text: str = ""):
        try:
            await self._post(
                "answerCallbackQuery",
                {
                    "callback_query_id": callback_query_id,
                    "text": text,
                },
            )
        except Exception as e:
            print(f"[TelegramPublisher] Error: {e}")
