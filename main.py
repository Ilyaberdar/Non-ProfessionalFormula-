import json
import re
from html import unescape
from bs4 import BeautifulSoup
import time
import asyncio
import traceback
from deep_translator import GoogleTranslator
from components.news_fwtcher import FetcherNews
from components.analyzer_openAI import GPTAnalyzer
from components.telegram_publisher import TelegramPublisher

API_KEY = "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"
telegram = TelegramPublisher(telegram_token="7666384903:AAETh0eJWqWH4huy9h9Bpoyz45D0T7hJuoQ", chat_id="@war_analytics_u")
telegramLog = TelegramPublisher(telegram_token="7666384903:AAETh0eJWqWH4huy9h9Bpoyz45D0T7hJuoQ", chat_id="-1002729684571")

with open("config/prompts/prompts.json", "r", encoding="utf-8") as f:
    prompts = json.load(f)

def clean_summary(summary_html: str) -> str:
    try:
        summary_html = unescape(summary_html)
        soup = BeautifulSoup(summary_html, "html.parser")
        for a in soup.find_all("a"):
            a.decompose()
        clean_text = soup.get_text(separator=" ", strip=True)
        clean_text = re.sub(r"\s+", " ", clean_text)
        return clean_text
    except Exception as e:
        print(f"[clean_summary] Error: {e}")
        return summary_html

async def main():
    while True:
        try:
            fetcher = FetcherNews("config/sources.json", "config/keywords.json", "config/mongo.json", 30, 50)
            openAIAnalyzer = GPTAnalyzer(api_key=API_KEY)
            articles = fetcher.getLatestNews()

            for article in articles:
                title = article.get("title")
                link = article.get("link")
                raw_summary = article.get("summary")
                if not title and not raw_summary:
                    continue

                prompt_template = prompts #TODO: change to real promt

                final_prompt = prompt_template["text"].format(claster_text=title)
                final_summary = clean_summary(raw_summary)

                if not final_prompt and not final_summary:
                    continue

                full_input = f"{prompt_template['text']}\n\nNews:\n{final_summary}"
                output = openAIAnalyzer.analyze(full_input)

                #translated_title = translate(title)
                clean_output = convert_markers_to_html(output)

                await telegram.publish(title=title, full_output=clean_output, article_url=link)

                print("Sleeping for 1 minute...")
                await asyncio.sleep(60)

            fetcher.save_to_mongo(articles)

        except Exception as e:
            await telegramLog.sendLog(f"Exception:\n<pre>{traceback.format_exc()}</pre>")
            print(f"Error: {e}")

        print("Sleeping for 1 hour...")
        await asyncio.sleep(60 * 60)


def convert_markers_to_html(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"^###\s*(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    return text.strip()

def translate(text_to_translate):
    translator = GoogleTranslator(source='en', target='ru')
    return translator.translate(text_to_translate)

if __name__ == "__main__":
    asyncio.run(main())