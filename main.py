from __future__ import annotations
import asyncio
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from datetime import timezone
from html import escape
from html import unescape

from components.analyzer_openAI import GPTAnalyzer
from components.news_fetcher import FetcherNews
from components.telegram_publisher import TelegramPublisher


def load_local_env(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def fetch_json(url: str) -> list[dict]:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_url(base: str, params: dict) -> str:
    filtered = {k: v for k, v in params.items() if v not in (None, "")}
    return f"{base}?{urllib.parse.urlencode(filtered)}"


def parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_active_openf1_session(meeting_key: str | None = None) -> tuple[bool, str]:
    params = {}
    if meeting_key:
        params["meeting_key"] = meeting_key

    sessions_url = build_url("https://api.openf1.org/v1/sessions", params)
    sessions = fetch_json(sessions_url)
    now = datetime.now(timezone.utc)

    for row in sessions:
        start = parse_dt(row.get("date_start"))
        end = parse_dt(row.get("date_end"))
        if not start or not end:
            continue
        if start <= now <= end:
            name = str(row.get("session_name") or row.get("session_type") or "Active F1 session")
            return True, name
    return False, ""


def clean_summary(summary_html: str) -> str:
    try:
        summary_html = unescape(summary_html or "")
        summary_html = re.sub(r"<a\b[^>]*>.*?</a>", " ", summary_html, flags=re.IGNORECASE | re.DOTALL)
        clean_text = re.sub(r"<[^>]+>", " ", summary_html)
        clean_text = re.sub(r"\s+", " ", clean_text)
        return clean_text.strip()
    except Exception:
        return summary_html or ""


def make_article_id(article: dict) -> str:
    seed = article.get("link") or f"{article.get('title', '')}|{article.get('published', '')}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_raw_review_text(article: dict, position: int, total: int) -> str:
    title = escape(article.get("title") or "Без заголовка")
    source = escape(article.get("source") or "Unknown")
    link = article.get("link") or ""
    summary = escape((article.get("summary_clean") or "")[:900])

    lines = [
        f"<b>Review Queue</b> ({position}/{total})",
        f"<b>{title}</b>",
        f"Source: {source}",
    ]

    if link:
        lines.append(f'<a href="{link}">Открыть источник</a>')
    if summary:
        lines.append("")
        lines.append(summary)

    return "\n".join(lines)


def format_draft_review_text(article: dict, position: int, total: int) -> str:
    title = escape(article.get("translated_title") or article.get("title") or "Без заголовка")
    link = article.get("link") or ""
    draft = escape((article.get("generated_post") or "")[:3500])
    lines = [
        f"<b>Review Queue</b> ({position}/{total})",
        f"<b>Draft for:</b> {title}",
    ]
    if link:
        lines.append(f'<a href="{link}">Открыть источник</a>')
    lines.extend(["", draft or "Draft is empty"])
    return "\n".join(lines)


def build_generation_prompt(article: dict) -> str:
    return (
        "Сделай пост для Telegram на русском про новость Формулы-1.\n"
        "Требования:\n"
        "1) Структура поста строго такая:\n"
        "   - Первая строка: перефразированный заголовок новости, обёрнутый в тег <b> </b>.\n"
        "   - Пустая строка.\n"
        "   - Текст новости: от 1 до 4 абзацев по 3-5 строк каждый — объём подбирай под количество фактов в источнике, не растягивай если фактов мало.\n"
        "2) Тон сухой, только факты из источника — ничего не придумывай и не додумывай.\n"
        "3) Никаких вопросительных предложений.\n"
        "4) Не используй HTML-теги кроме <b> для заголовка.\n"
        "5) Без хэштегов.\n\n"
        "Формат ответа строго такой:\n"
        "TITLE_RU: <переведенный заголовок>\n"
        "POST_RU:\n"
        "<текст поста>\n\n"
        f"Источник: {article.get('source', '')}\n"
        f"Заголовок: {article.get('title', '')}\n"
        f"Кратко: {article.get('summary_clean', '')}"
    )


def build_final_post(post_text: str, article: dict) -> str:
    channel_url = "https://t.me/nonprofessional_f1"
    source_url = article.get('url', '')

    footer = (
        f'<a href="{channel_url}">(Не)профессиональная формула • Подписаться</a>'
        f' | 📰 <a href="{source_url}">Источник</a>'
    )


def parse_generated_output(raw: str, fallback_title: str) -> tuple[str, str]:
    text = (raw or "").strip()
    title = fallback_title
    post = text

    title_match = re.search(r"TITLE_RU:\s*(.+)", text)
    if title_match:
        parsed_title = title_match.group(1).strip()
        if parsed_title:
            title = parsed_title

    post_match = re.search(r"POST_RU:\s*(.*)", text, flags=re.DOTALL)
    if post_match:
        parsed_post = post_match.group(1).strip()
        if parsed_post:
            post = parsed_post

    if not post:
        post = text
    return title, post


def upsert_article_status(collection, article: dict, status: str, reviewer=None) -> None:
    link = article.get("link")
    if not link:
        return

    now = utc_now_iso()
    set_fields = {
        "source": article.get("source", ""),
        "title": article.get("title", ""),
        "link": link,
        "summary": article.get("summary", ""),
        "summary_clean": article.get("summary_clean", ""),
        "translated_title": article.get("translated_title", ""),
        "published": article.get("published", ""),
        "published_parsed": article.get("published_parsed", ""),
        "generated_post": article.get("generated_post", ""),
        "status": status,
        "updated_at": now,
    }

    if status == "queued":
        set_fields["queued_at"] = now
    if status in {"accepted", "declined", "skipped"}:
        set_fields["decision_at"] = now
        set_fields["reviewer"] = reviewer or "unknown"

    collection.update_one(
        {"link": link},
        {
            "$set": set_fields,
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


def load_pending_queue(collection, limit: int = 300) -> list[dict]:
    docs = list(
        collection.find({"status": {"$in": ["queued", "draft_ready"]}})
        .sort("queued_at", 1)
        .limit(limit)
    )

    queue = []
    for doc in docs:
        queue.append(
            {
                "id": make_article_id(doc),
                "source": doc.get("source", ""),
                "title": doc.get("title", ""),
                "link": doc.get("link", ""),
                "summary": doc.get("summary", ""),
                "summary_clean": doc.get("summary_clean", ""),
                "translated_title": doc.get("translated_title", ""),
                "published": doc.get("published", ""),
                "published_parsed": doc.get("published_parsed", ""),
                "generated_post": doc.get("generated_post", ""),
                "status": doc.get("status", "queued"),
            }
        )
    return queue


def get_review_payload(queue: list[dict], current_index: int) -> tuple[str, list[list[dict]], str]:
    total = len(queue)
    article = queue[current_index]
    article_id = article["id"]

    if article.get("status") == "draft_ready" and article.get("generated_post"):
        text = format_draft_review_text(article, current_index + 1, total)
        buttons = [
            [
                {"text": "Accept", "callback_data": f"final_accept:{article_id}"},
                {"text": "Decline", "callback_data": f"final_decline:{article_id}"},
            ]
        ]
        key = f"draft:{article_id}:{current_index}:{total}:{hash(article.get('generated_post', ''))}"
        return text, buttons, key

    text = format_raw_review_text(article, current_index + 1, total)
    rows = [
        [
            {"text": "Accept", "callback_data": f"raw_accept:{article_id}"},
            {"text": "Decline", "callback_data": f"raw_decline:{article_id}"},
        ]
    ]
    rows.append(
        [
            {"text": "Next", "callback_data": "raw_next"},
            {"text": "Skip all", "callback_data": "raw_skipall"},
        ]
    )

    key = f"raw:{article_id}:{current_index}:{total}"
    return text, rows, key


async def main() -> None:
    load_local_env()

    telegram_token = os.getenv("TELEGRAM_TOKEN", "").strip()
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    telegram_log_chat_id = os.getenv("TELEGRAM_LOG_CHAT_ID", "").strip()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not telegram_token or not telegram_chat_id or not telegram_log_chat_id:
        raise RuntimeError("Set TELEGRAM_TOKEN, TELEGRAM_CHAT_ID and TELEGRAM_LOG_CHAT_ID")

    fetch_interval_sec = int(os.getenv("FETCH_INTERVAL_SEC", "300"))
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    block_news_during_openf1 = os.getenv("BLOCK_NEWS_DURING_OPENF1", "1").strip() == "1"
    openf1_meeting_key = os.getenv("OPENF1_MEETING_KEY", "").strip() or None
    openf1_check_interval_sec = int(os.getenv("OPENF1_CHECK_INTERVAL_SEC", "60"))

    fetcher = FetcherNews("config/sources.json", "config/keywords.json", "config/mongo.json", 30, 50)
    if fetcher.mongo_collection is None:
        raise RuntimeError("MongoDB is required for review workflow")

    telegram = TelegramPublisher(telegram_token=telegram_token, chat_id=telegram_chat_id)
    analyzer = GPTAnalyzer(api_key=openai_api_key, model=openai_model, temperature=0.5, max_tokens=500) if openai_api_key else None

    pending_queue = load_pending_queue(fetcher.mongo_collection)
    queued_ids = {item["id"] for item in pending_queue}

    print(f"Loaded {len(pending_queue)} queued items from DB")

    offset = None
    current_index = 0
    review_message_id = None
    rendered_key = None
    last_fetch_at = 0.0
    news_blocked_for_session = False
    active_session_name = ""
    last_openf1_check_at = 0.0

    bootstrap_updates = await telegram.get_updates(timeout=0)
    if bootstrap_updates:
        offset = max(update.get("update_id", 0) for update in bootstrap_updates) + 1

    while True:
        if block_news_during_openf1 and (time.monotonic() - last_openf1_check_at >= openf1_check_interval_sec):
            try:
                is_active, session_name = await asyncio.to_thread(get_active_openf1_session, openf1_meeting_key)
                last_openf1_check_at = time.monotonic()
                if is_active and not news_blocked_for_session:
                    news_blocked_for_session = True
                    active_session_name = session_name
                    await telegram.send_log(
                        f"News posting paused: active F1 session ({escape(active_session_name)}).",
                        chat_id=telegram_log_chat_id,
                    )
                elif (not is_active) and news_blocked_for_session:
                    news_blocked_for_session = False
                    active_session_name = ""
                    await telegram.send_log("News posting resumed: no active F1 session.", chat_id=telegram_log_chat_id)
            except Exception as e:
                last_openf1_check_at = time.monotonic()
                print(f"[openf1-check] Error: {e}")

        if pending_queue:
            if current_index >= len(pending_queue):
                current_index = 0

            text, buttons, key = get_review_payload(pending_queue, current_index)
            if review_message_id is None:
                sent = await telegram.send_inline_message(telegram_log_chat_id, text, buttons)
                review_message_id = sent.get("message_id") if isinstance(sent, dict) else None
                rendered_key = key if review_message_id is not None else None
            elif rendered_key != key:
                edited = await telegram.edit_inline_message(telegram_log_chat_id, review_message_id, text, buttons)
                if edited is not None:
                    rendered_key = key
                else:
                    sent = await telegram.send_inline_message(telegram_log_chat_id, text, buttons)
                    review_message_id = sent.get("message_id") if isinstance(sent, dict) else None
                    rendered_key = key if review_message_id is not None else None
        else:
            review_message_id = None
            rendered_key = None
            current_index = 0

        updates = await telegram.get_updates(offset=offset, timeout=2)
        for update in updates:
            offset = update.get("update_id", 0) + 1
            callback = update.get("callback_query")
            if callback is None:
                continue

            data = callback.get("data") or ""
            from_user = callback.get("from", {})
            reviewer = from_user.get("username") or str(from_user.get("id", "unknown"))
            message = callback.get("message") or {}
            cb_id = callback.get("id", "")

            if str(message.get("chat", {}).get("id")) != str(telegram_log_chat_id):
                await telegram.answer_callback(cb_id, "Wrong chat")
                continue
            if not pending_queue:
                await telegram.answer_callback(cb_id, "Queue is empty")
                continue

            current = pending_queue[current_index]
            current_id = current["id"]

            if data.startswith("raw_accept:"):
                article_id = data.split(":", 1)[1]
                if article_id != current_id:
                    await telegram.answer_callback(cb_id, "Item is outdated")
                    continue
                if not analyzer:
                    await telegram.answer_callback(cb_id, "OPENAI_API_KEY is missing")
                    continue

                await telegram.answer_callback(cb_id, "Generating draft...")
                prompt = build_generation_prompt(current)
                draft = await asyncio.to_thread(analyzer.analyze, prompt)
                draft = (draft or "").strip()
                if not draft:
                    await telegram.send_log("OpenAI returned empty draft", chat_id=telegram_log_chat_id)
                    continue

                translated_title, generated_post = parse_generated_output(draft, current.get("title") or "Без заголовка")
                current["translated_title"] = translated_title
                current["generated_post"] = generated_post
                current["status"] = "draft_ready"
                upsert_article_status(fetcher.mongo_collection, current, "draft_ready", reviewer=reviewer)
                rendered_key = None

            elif data.startswith("raw_decline:"):
                article_id = data.split(":", 1)[1]
                if article_id != current_id:
                    await telegram.answer_callback(cb_id, "Item is outdated")
                    continue

                removed = pending_queue.pop(current_index)
                queued_ids.discard(removed["id"])
                upsert_article_status(fetcher.mongo_collection, removed, "declined", reviewer=reviewer)
                if current_index >= len(pending_queue):
                    current_index = 0
                rendered_key = None
                await telegram.answer_callback(cb_id, "Declined")

            elif data == "raw_next":
                if len(pending_queue) <= 1:
                    await telegram.answer_callback(cb_id, "Only one item in queue")
                    continue
                current_index = (current_index + 1) % len(pending_queue)
                rendered_key = None
                await telegram.answer_callback(cb_id, "Next")

            elif data == "raw_skipall":
                for article in pending_queue:
                    upsert_article_status(fetcher.mongo_collection, article, "skipped", reviewer=reviewer)
                skipped_count = len(pending_queue)
                pending_queue.clear()
                queued_ids.clear()
                current_index = 0
                review_message_id = None
                rendered_key = None
                await telegram.answer_callback(cb_id, f"Skipped {skipped_count}")

            elif data.startswith("final_accept:"):
                article_id = data.split(":", 1)[1]
                if article_id != current_id:
                    await telegram.answer_callback(cb_id, "Item is outdated")
                    continue
                if current.get("status") != "draft_ready":
                    await telegram.answer_callback(cb_id, "Draft is not ready")
                    continue
                if news_blocked_for_session:
                    await telegram.answer_callback(
                        cb_id,
                        f"Paused during {active_session_name or 'active F1 session'}",
                    )
                    await telegram.send_log(
                        f"Publish blocked during active session: {escape(active_session_name or 'F1 session')}",
                        chat_id=telegram_log_chat_id,
                        reply_to_message_id=message.get("message_id"),
                    )
                    continue

                await telegram.publish(
                    title=current.get("translated_title") or current.get("title") or "Без заголовка",
                    full_output=current.get("generated_post") or "",
                    article_url=current.get("link") or "",
                )
                removed = pending_queue.pop(current_index)
                queued_ids.discard(removed["id"])
                upsert_article_status(fetcher.mongo_collection, removed, "accepted", reviewer=reviewer)
                await telegram.send_log(
                    "<b>Decision:</b> accepted",
                    chat_id=telegram_log_chat_id,
                    reply_to_message_id=message.get("message_id"),
                )
                if current_index >= len(pending_queue):
                    current_index = 0
                rendered_key = None
                await telegram.answer_callback(cb_id, "Posted")

            elif data.startswith("final_decline:"):
                article_id = data.split(":", 1)[1]
                if article_id != current_id:
                    await telegram.answer_callback(cb_id, "Item is outdated")
                    continue

                removed = pending_queue.pop(current_index)
                queued_ids.discard(removed["id"])
                upsert_article_status(fetcher.mongo_collection, removed, "declined", reviewer=reviewer)
                await telegram.send_log(
                    "<b>Decision:</b> declined",
                    chat_id=telegram_log_chat_id,
                    reply_to_message_id=message.get("message_id"),
                )
                if current_index >= len(pending_queue):
                    current_index = 0
                rendered_key = None
                await telegram.answer_callback(cb_id, "Declined")

            else:
                await telegram.answer_callback(cb_id, "Unknown action")

        if time.monotonic() - last_fetch_at >= fetch_interval_sec:
            articles = fetcher.getLatestNews()
            added = 0
            for article in articles:
                article["summary_clean"] = clean_summary(article.get("summary", ""))
                article["translated_title"] = ""
                article["generated_post"] = ""
                article["status"] = "queued"
                article_id = make_article_id(article)
                if article_id in queued_ids:
                    continue

                upsert_article_status(fetcher.mongo_collection, article, "queued")
                article["id"] = article_id
                pending_queue.append(article)
                queued_ids.add(article_id)
                added += 1

            last_fetch_at = time.monotonic()
            if added:
                rendered_key = None
                await telegram.send_log(
                    f"Queued {added} new items. Pending now: {len(pending_queue)}",
                    chat_id=telegram_log_chat_id,
                )

        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
