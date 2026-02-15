from telegram import Bot

class TelegramPublisher:
    def __init__(self, telegram_token: str, chat_id: str):
        self.bot = Bot(token=telegram_token)
        self.chat_id = chat_id

    async def publish(self, title: str, full_output: str, article_url: str):
        try:
            caption_text_and_output = f"<b>{title}</b>\n\n{full_output}\n\n <a href=\"{article_url}\">Читать источник</a>"

            await self.bot.send_message(
                chat_id=self.chat_id,
                text=caption_text_and_output,
                parse_mode="HTML"
            )

        except Exception as e:
            print(f"[TelegramPublisher] Error: {e}")

    async def sendLog(self, log: str):
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=log,
                parse_mode="HTML"
            )

        except Exception as e:
            print(f"[TelegramPublisher] Error: {e}")
