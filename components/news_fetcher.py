import os
import re
import json
import time
from datetime import datetime
from html import unescape

import feedparser
from pymongo import MongoClient

from components.logger import setup_logger


class FetcherNews:
    DEFAULT_F1_PATTERNS = [
        r"\bf1\b",
        r"\bformula[\s-]?1\b",
        r"\bgrand prix\b",
        r"\bfia\b",
        r"\bverstappen\b",
        r"\bhamilton\b",
        r"\bleclerc\b",
        r"\bnorris\b",
        r"\bred bull\b",
        r"\bmercedes\b",
        r"\bferrari\b",
        r"\bmclaren\b",
    ]

    def __init__(self, source_links, keywords_file, mongo_config, pool_interval, max_items_per_feed):
        self.logger = setup_logger()
        self.logger.info("Initializing FetcherNews")

        self.source_links = source_links
        self.keywords_file = keywords_file
        self.pool_interval = pool_interval
        self.max_items_per_feed = max_items_per_feed
        self.mongo_client = None
        self.mongo_collection = None
        self.mongo_enabled = bool(mongo_config)
        if mongo_config:
            self._connect_to_mongo(mongo_config)
        else:
            self.logger.info("MongoDB connection disabled.")

        try:
            self.sources = self._load_sources(source_links)
            self.logger.info(f"Loaded {len(self.sources)} RSS sources.")
        except Exception as e:
            self.logger.error(f"Failed to load sources from {source_links}: {e}")
            self.sources = {}

        try:
            raw_keywords = self._load_sources(keywords_file)
            source = raw_keywords.get("keywords") if isinstance(raw_keywords, dict) else raw_keywords
            source = source if isinstance(source, list) else []

            self.keywords = [kw.strip().lower() for kw in source if isinstance(kw, str) and kw.strip()]
            self.logger.info(f"Loaded {len(self.keywords)} keywords.")
        except Exception as e:
            self.logger.error(f"Failed to load keywords from {keywords_file}: {e}")
            self.keywords = []

    def _connect_to_mongo(self, config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            client = MongoClient(config["uri"])
            db = client[config["db"]]
            self.mongo_collection = db[config["collection"]]
            self.mongo_client = client
            self.logger.info(f"Connected to MongoDB: {config['db']}.{config['collection']}")
        except Exception as e:
            self.logger.error(f"MongoDB connection failed: {e}")

    def _load_sources(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_existing_links_from_mongo(self):
        if self.mongo_collection is None:
            if self.mongo_enabled:
                self.logger.warning("MongoDB not connected. Cannot check for duplicates.")
            else:
                self.logger.info("MongoDB duplicate check disabled.")
            return set()
        try:
            links = {doc["link"] for doc in self.mongo_collection.find({}, {"link": 1}) if "link" in doc}
            self.logger.info(f"Loaded {len(links)} existing links from MongoDB.")
            return links
        except Exception as e:
            self.logger.error(f"Failed to load existing links from MongoDB: {e}")
            return set()

    def _load_existing_links(self, path="news_dump.json"):
        if not os.path.exists(path):
            self.logger.info("No existing news file found.")
            return set()

        try:
            with open(path, "r", encoding="utf-8") as f:
                articles = json.load(f)
                links = {article.get("link", "") for article in articles if "link" in article}
                self.logger.info(f"Loaded {len(links)} existing articles from {path}")
                return links
        except Exception as e:
            self.logger.error(f"Failed to load existing news: {e}")
            return set()

    def _is_relevant(self, title, summary):
        try:
            text = (title + " " + self._strip_html(summary)).lower()
            matched = [kw for kw in self.keywords if kw in text]
            if not matched:
                regex_match = any(re.search(pattern, text) for pattern in self.DEFAULT_F1_PATTERNS)
                if regex_match:
                    return True
            if matched:
                self.logger.debug(f"[MATCH] '{title}' -> {matched}")
            return bool(matched)
        except Exception as e:
            self.logger.error(f"Failed relevance check: {e}")
            return False

    def _strip_html(self, text):
        try:
            return re.sub(r"<[^>]+>", "", unescape(text or ""))
        except Exception as e:
            self.logger.error(f"HTML stripping error: {e}")
            return text

    def getLatestNews(self):
        relevant_articles = []
        existing_links = self._load_existing_links_from_mongo()

        for source_name, feed_url in self.sources.items():
            try:
                self.logger.info(f"Parsing: {source_name}")
                feed = feedparser.parse(feed_url)
                if getattr(feed, "bozo", False):
                    self.logger.warning(f"Malformed feed {source_name}: {getattr(feed, 'bozo_exception', '')}")

                count = 0
                for entry in feed.entries:
                    if count >= self.max_items_per_feed:
                        break

                    if entry.get("link", "") in existing_links:
                        continue

                    try:
                        title = entry.get("title", "")
                        summary = entry.get("summary", "")
                        if not self._is_relevant(title, summary):
                            continue

                        published_struct = entry.get("published_parsed")
                        if isinstance(published_struct, time.struct_time):
                            published_parsed = datetime(*published_struct[:6]).isoformat()
                        else:
                            published_parsed = ""

                        relevant_articles.append(
                            {
                                "source": source_name,
                                "title": title,
                                "link": entry.get("link", ""),
                                "summary": summary,
                                "published": entry.get("published", ""),
                                "published_parsed": published_parsed,
                            }
                        )
                        count += 1
                    except Exception as e:
                        self.logger.warning(f"Failed to parse article from {source_name}: {e}")
            except Exception as e:
                self.logger.error(f"Failed to parse feed {source_name}: {e}")

        self.logger.info(f"Collected {len(relevant_articles)} relevant articles.")
        return relevant_articles

    def save_to_json(self, new_articles, output_path="news_dump.json"):
        try:
            existing = []
            if os.path.exists(output_path):
                with open(output_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)

            all_articles = existing + new_articles
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(all_articles, f, indent=2, ensure_ascii=False)

            self.logger.info(f"Appended {len(new_articles)} new articles. Total now: {len(all_articles)}")
        except Exception as e:
            self.logger.error(f"Failed to save articles: {e}")

    def save_to_mongo(self, articles):
        if self.mongo_collection is None:
            self.logger.warning("MongoDB not connected. Skipping save.")
            return

        count_inserted = 0
        for article in articles:
            link = article.get("link")
            if not link:
                continue
            if self.mongo_collection.find_one({"link": link}):
                continue
            try:
                self.mongo_collection.insert_one(article)
                count_inserted += 1
            except Exception as e:
                self.logger.error(f"Mongo insert failed for {link}: {e}")

        self.logger.info(f"Inserted {count_inserted} new articles into MongoDB.")
