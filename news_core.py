"""News collection core: feeds, filtering, classification. Shared by the PDF brief and the live app."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, wait
from functools import partial
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import quote_plus, urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

from text_utils import clean_text, has_arabic, sentence_safe_excerpt, word_safe_excerpt

try:
    from googlenewsdecoder import GoogleDecoder
except ImportError as exc:  # a broken optional dependency must not take the whole brief down
    GoogleDecoder = None
    print(f"Warning: googlenewsdecoder unavailable ({exc}); Google News links will not be decoded.")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")



BRIEF_MAX_CHARS = 560
BRIEF_MIN_CHARS = 80
MAX_ENTRIES_PER_FEED = 12
MAX_ENTRIES_PER_WORLD_FEED = 8
REQUEST_TIMEOUT_SECONDS = 8
FETCH_RETRIES = 2
FETCH_WORKERS = 12
# Worldwide coverage is on by default. Set WORLD_NEWS=0 to get the old UAE-only brief.
WORLD_NEWS_ENABLED = os.environ.get("WORLD_NEWS", "1").strip().lower() not in {"0", "false", "no", "off"}
MAX_WORLD_ARTICLE_AGE_DAYS = 3
REQUIRE_ARABIC_HEADLINES = False
GLOBAL_UAE_COVERAGE = True
MAX_ARTICLE_AGE_DAYS = 7

UAE_TIMEZONE = timezone(timedelta(hours=4), "GST")

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    )
}


@dataclass(frozen=True)
class RssFeed:
    label: str
    url: str
    priority: int
    scope: str = "uae"  # "uae": keep only UAE-related stories; "world": keep everything newsworthy
    category: str = ""  # section hint for world feeds, one of CATEGORY_ORDER
    topic: str = ""  # optional topic hint (a key of TOPIC_KEYWORDS) for feeds that are about one subject


@dataclass(frozen=True)
class Article:
    title: str
    source: str
    feed_label: str
    category: str
    score: int
    published_at: datetime | None
    link: str
    summary: str
    topics: tuple[str, ...] = ()
    region: str = "world"  # "uae", "middle_east" or "world"
    uae_mention: bool = False
    image: str = ""  # image URL taken from the feed entry when it carries one
    also: tuple[tuple[str, str, str], ...] = ()  # (source, link, title) of the same story from other outlets


def google_news_rss_url(query: str, language: str = "ar") -> str:
    encoded_query = quote_plus(f"{query} when:{MAX_ARTICLE_AGE_DAYS}d")
    if language == "en":
        return f"https://news.google.com/rss/search?q={encoded_query}&hl=en-AE&gl=AE&ceid=AE:en"
    return f"https://news.google.com/rss/search?q={encoded_query}&hl=ar-AE&gl=AE&ceid=AE:ar"


GLOBAL_UAE_TERMS_EN = '("UAE" OR "United Arab Emirates" OR Emirati OR "Abu Dhabi" OR Dubai OR ADNOC OR Mubadala OR "Mohamed bin Zayed")'
GLOBAL_UAE_TERMS_AR = '(الإمارات OR إماراتي OR أبوظبي OR "أبو ظبي" OR دبي OR أدنوك OR مبادلة OR "محمد بن زايد")'


def global_source_feed(label: str, domain: str, priority: int = 5, language: str = "en") -> RssFeed:
    terms = GLOBAL_UAE_TERMS_AR if language == "ar" else GLOBAL_UAE_TERMS_EN
    return RssFeed(label, google_news_rss_url(f"site:{domain} {terms}", language=language), priority)


RSS_FEEDS = [
    RssFeed("كل العالم - الإمارات", google_news_rss_url(GLOBAL_UAE_TERMS_AR, language="ar"), 8),
    RssFeed("Global UAE coverage", google_news_rss_url(GLOBAL_UAE_TERMS_EN, language="en"), 8),
    RssFeed("وام", google_news_rss_url("site:wam.ae/ar الإمارات"), 9),
    RssFeed("وام - القيادة", google_news_rss_url('site:wam.ae/ar "محمد بن زايد"'), 9),
    RssFeed("رئيس الدولة", google_news_rss_url('"محمد بن زايد" الإمارات'), 8),
    RssFeed("حكومة الإمارات", google_news_rss_url("الإمارات حكومة OR مجلس الوزراء"), 8),
    RssFeed("الدفاع والأمن", google_news_rss_url("الإمارات دفاع OR القوات المسلحة الإماراتية OR الأمن"), 7),
    RssFeed("اقتصاد الإمارات", google_news_rss_url("أدنوك OR مبادلة OR اقتصاد الإمارات OR استثمار الإمارات"), 7),
    RssFeed("العلاقات الخارجية", google_news_rss_url("الإمارات علاقات خارجية OR دبلوماسية OR اتفاقية"), 7),
    global_source_feed("WAM English", "wam.ae/en", 9, "en"),
    global_source_feed("The National", "thenationalnews.com", 7, "en"),
    global_source_feed("Gulf News", "gulfnews.com", 6, "en"),
    global_source_feed("Khaleej Times", "khaleejtimes.com", 6, "en"),
    global_source_feed("البيان", "albayan.ae", 7, "ar"),
    global_source_feed("الإمارات اليوم", "emaratalyoum.com", 7, "ar"),
    global_source_feed("الخليج", "alkhaleej.ae", 7, "ar"),
    global_source_feed("الاتحاد", "aletihad.ae", 7, "ar"),
    global_source_feed("مكتب أبوظبي الإعلامي", "mediaoffice.abudhabi", 8, "ar"),
    global_source_feed("Abu Dhabi Media Office", "mediaoffice.abudhabi", 8, "en"),
    global_source_feed("مكتب دبي الإعلامي", "mediaoffice.ae", 8, "ar"),
    global_source_feed("Dubai Media Office", "mediaoffice.ae", 8, "en"),
    global_source_feed("وزارة الخارجية الإماراتية", "mofa.gov.ae", 8, "ar"),
    global_source_feed("UAE Ministry of Foreign Affairs", "mofa.gov.ae", 8, "en"),
    global_source_feed("بوابة حكومة الإمارات", "u.ae", 7, "ar"),
    global_source_feed("UAE Government Portal", "u.ae", 7, "en"),
    global_source_feed("مجلس الوزراء الإماراتي", "uaecabinet.ae", 7, "ar"),
    global_source_feed("UAE Cabinet", "uaecabinet.ae", 7, "en"),
    global_source_feed("وزارة الاقتصاد الإماراتية", "economy.ae", 7, "ar"),
    global_source_feed("UAE Ministry of Economy", "economy.ae", 7, "en"),
    global_source_feed("وزارة المالية الإماراتية", "mof.gov.ae", 7, "ar"),
    global_source_feed("UAE Ministry of Finance", "mof.gov.ae", 7, "en"),
    global_source_feed("Central Bank of the UAE", "centralbank.ae", 6, "en"),
    global_source_feed("ADNOC", "adnoc.ae", 6, "en"),
    global_source_feed("Mubadala", "mubadala.com", 6, "en"),
    global_source_feed("EDGE Group", "edgegroup.ae", 5, "en"),
    global_source_feed("Dubai Chambers", "dubaichambers.com", 5, "en"),
    global_source_feed("Dubai Future Foundation", "dubaifuture.ae", 5, "en"),
    global_source_feed("Sharjah24", "sharjah24.ae", 6, "ar"),
    global_source_feed("Emirates 24|7", "emirates247.com", 5, "en"),
    global_source_feed("Arabian Business", "arabianbusiness.com", 5, "en"),
    global_source_feed("Gulf Business", "gulfbusiness.com", 5, "en"),
    global_source_feed("Economy Middle East", "economymiddleeast.com", 5, "en"),
    global_source_feed("AGBI", "agbi.com", 5, "en"),
    global_source_feed("MEED", "meed.com", 5, "en"),
    global_source_feed("The Circuit", "thecircuit.news", 5, "en"),
    global_source_feed("Reuters", "reuters.com", 8, "en"),
    global_source_feed("Associated Press", "apnews.com", 7, "en"),
    global_source_feed("Bloomberg", "bloomberg.com", 7, "en"),
    global_source_feed("CNBC", "cnbc.com", 6, "en"),
    global_source_feed("Financial Times", "ft.com", 6, "en"),
    global_source_feed("Wall Street Journal", "wsj.com", 6, "en"),
    global_source_feed("BBC", "bbc.com", 6, "en"),
    global_source_feed("CNN", "cnn.com", 6, "en"),
    global_source_feed("The Guardian", "theguardian.com", 5, "en"),
    global_source_feed("New York Times", "nytimes.com", 5, "en"),
    global_source_feed("Washington Post", "washingtonpost.com", 5, "en"),
    global_source_feed("France 24", "france24.com", 5, "en"),
    global_source_feed("DW", "dw.com", 5, "en"),
    global_source_feed("VOA", "voanews.com", 5, "en"),
    global_source_feed("Euronews", "euronews.com", 4, "en"),
    global_source_feed("Nikkei Asia", "asia.nikkei.com", 4, "en"),
    global_source_feed("South China Morning Post", "scmp.com", 4, "en"),
    global_source_feed("Al-Monitor", "al-monitor.com", 5, "en"),
    global_source_feed("Al Jazeera", "aljazeera.com", 6, "en"),
    global_source_feed("Al Arabiya", "alarabiya.net", 6, "ar"),
    global_source_feed("Sky News Arabia", "skynewsarabia.com", 6, "ar"),
    global_source_feed("Asharq", "asharq.com", 6, "ar"),
    global_source_feed("Asharq Al-Awsat", "aawsat.com", 6, "ar"),
    global_source_feed("Arab News", "arabnews.com", 5, "en"),
    global_source_feed("Middle East Eye", "middleeasteye.net", 5, "en"),
    global_source_feed("The New Arab", "newarab.com", 5, "en"),
    global_source_feed("Zawya", "zawya.com", 5, "en"),
    global_source_feed("Forbes Middle East", "forbesmiddleeast.com", 5, "en"),
]


def world_feed(label: str, url: str, category: str, priority: int = 6, topic: str = "") -> RssFeed:
    return RssFeed(label, url, priority, scope="world", category=category, topic=topic)


def google_topic_feed(topic: str, category: str, language: str = "en") -> RssFeed:
    if language == "ar":
        url = f"https://news.google.com/rss/headlines/section/topic/{topic}?hl=ar&gl=AE&ceid=AE:ar"
        label = f"Google News {topic} (AR)"
    else:
        url = f"https://news.google.com/rss/headlines/section/topic/{topic}?hl=en&gl=US&ceid=US:en"
        label = f"Google News {topic}"
    return world_feed(label, url, category, 6)


def google_world_source_feed(label: str, domain: str, query: str, category: str, priority: int = 7) -> RssFeed:
    url = google_news_rss_url(f"site:{domain} {query}", language="en").replace("hl=en-AE&gl=AE&ceid=AE:en", "hl=en&gl=US&ceid=US:en")
    return world_feed(label, url, category, priority)


# Worldwide sources. Direct publisher feeds are preferred because they need no Google redirect
# decoding; Google News topic and site feeds fill in agencies that no longer publish RSS.
WORLD_RSS_FEEDS = [
    world_feed("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", "World Affairs", 8),
    world_feed("BBC Middle East", "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml", "Middle East", 8),
    world_feed("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml", "Global Business", 7),
    world_feed("BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml", "Tech & Science", 6),
    world_feed("BBC Science", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "Tech & Science", 6),
    world_feed("BBC Arabic", "https://feeds.bbci.co.uk/arabic/rss.xml", "World Affairs", 7),
    world_feed("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", "Middle East", 7),
    world_feed("The Guardian World", "https://www.theguardian.com/world/rss", "World Affairs", 7),
    world_feed("The Guardian Business", "https://www.theguardian.com/business/rss", "Global Business", 6),
    world_feed("The Guardian Technology", "https://www.theguardian.com/technology/rss", "Tech & Science", 6),
    world_feed("The Guardian Science", "https://www.theguardian.com/science/rss", "Tech & Science", 6),
    world_feed("NPR World", "https://feeds.npr.org/1004/rss.xml", "World Affairs", 6),
    world_feed("DW", "https://rss.dw.com/rdf/rss-en-all", "World Affairs", 6),
    world_feed("France 24", "https://www.france24.com/en/rss", "World Affairs", 6),
    world_feed("Sky News World", "https://feeds.skynews.com/feeds/rss/world.xml", "World Affairs", 6),
    world_feed("ABC News Australia", "https://www.abc.net.au/news/feed/2942460/rss.xml", "World Affairs", 5),
    world_feed("New York Times World", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "World Affairs", 7),
    world_feed("New York Times Business", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "Global Business", 6),
    world_feed("New York Times Technology", "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml", "Tech & Science", 6),
    world_feed("CNBC World", "https://www.cnbc.com/id/100727362/device/rss/rss.html", "Global Business", 6),
    world_feed("CNBC Business", "https://www.cnbc.com/id/10001147/device/rss/rss.html", "Global Business", 6),
    world_feed("Arab News", "https://www.arabnews.com/rss.xml", "Middle East", 5),
    world_feed("Al Arabiya", "https://www.alarabiya.net/feed/rss2/ar.xml", "Middle East", 6),
    world_feed("The Guardian Politics", "https://www.theguardian.com/politics/rss", "World Affairs", 6, "politics"),
    world_feed("New York Times Politics", "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml", "World Affairs", 6, "politics"),
    world_feed("NPR Politics", "https://feeds.npr.org/1014/rss.xml", "World Affairs", 6, "politics"),
    world_feed("BBC Politics", "https://feeds.bbci.co.uk/news/politics/rss.xml", "World Affairs", 5, "politics"),
    google_topic_feed("NATION", "World Affairs"),
    google_topic_feed("WORLD", "World Affairs"),
    google_topic_feed("BUSINESS", "Global Business"),
    google_topic_feed("TECHNOLOGY", "Tech & Science"),
    google_topic_feed("SCIENCE", "Tech & Science"),
    google_topic_feed("HEALTH", "Tech & Science"),
    google_topic_feed("WORLD", "World Affairs", "ar"),
    google_topic_feed("BUSINESS", "Global Business", "ar"),
    google_topic_feed("TECHNOLOGY", "Tech & Science", "ar"),
    google_world_source_feed("Reuters World", "reuters.com", "world", "World Affairs", 8),
    google_world_source_feed("Reuters Business", "reuters.com", "markets OR economy OR oil", "Global Business", 8),
    google_world_source_feed("Associated Press", "apnews.com", "world", "World Affairs", 7),
    google_world_source_feed("Bloomberg", "bloomberg.com", "markets OR economy", "Global Business", 7),
    google_world_source_feed("Financial Times", "ft.com", "world OR economy", "Global Business", 6),
]

WORLD_BAD_KEYWORDS = [
    "رياضة",
    "كرة القدم",
    "مشاهير",
    "ترفيه",
    "برج",
    "sport",
    "sports",
    "football",
    "soccer",
    "cricket",
    "tennis",
    "premier league",
    "nba",
    "nfl",
    "celebrity",
    "entertainment",
    "horoscope",
    "box office",
    "gossip",
    "royal wedding",
    "fact check",
    "quiz",
    "crossword",
    "recipe",
    "newsletter",
]

TOPIC_KEYWORDS = {
    "politics": [
        "president", "prime minister", "government", "parliament", "election", "elections", "vote", "senate",
        "congress", "minister", "sanctions", "diplomat", "diplomacy", "summit", "treaty", "coalition", "cabinet",
        "policy", "lawmakers", "ceasefire", "talks", "referendum", "opposition", "white house", "kremlin",
        "الرئيس", "رئيس الوزراء", "حكومة", "برلمان", "انتخابات", "وزير", "عقوبات", "دبلوماسية", "قمة",
        "مجلس الوزراء", "مباحثات", "وقف إطلاق النار", "سياسة", "المعارضة",
    ],
    "business": [
        "market", "markets", "stocks", "shares", "economy", "economic", "inflation", "central bank", "interest rate",
        "tariff", "trade", "bank", "earnings", "gdp", "currency", "investment", "investors", "ipo", "merger",
        "اقتصاد", "الأسواق", "الأسهم", "التضخم", "الفائدة", "تجارة", "استثمار", "بنك", "أعمال", "عملة",
    ],
    "security": [
        "military", "army", "defense", "defence", "war", "attack", "missile", "drone", "terror", "police",
        "security", "troops", "strike", "strikes", "conflict", "navy", "weapons",
        "عسكري", "الجيش", "دفاع", "حرب", "هجوم", "صاروخ", "طائرة مسيرة", "إرهاب", "شرطة", "أمن", "قوات",
    ],
    "tech": [
        "ai", "artificial intelligence", "chip", "chips", "semiconductor", "software", "cyber", "startup",
        "robot", "quantum", "smartphone", "app", "tech", "technology", "data center",
        "ذكاء اصطناعي", "تقنية", "تكنولوجيا", "رقمي", "شريحة", "أمن سيبراني", "روبوت",
    ],
    "science_health": [
        "scientists", "study", "research", "space", "nasa", "vaccine", "health", "disease", "hospital", "virus",
        "cancer", "medicine", "satellite", "planet", "discovery",
        "علماء", "دراسة", "أبحاث", "فضاء", "ناسا", "لقاح", "صحة", "مرض", "مستشفى", "فيروس", "اكتشاف",
    ],
    "energy_climate": [
        "oil", "gas", "opec", "energy", "solar", "renewable", "nuclear", "climate", "emissions", "wildfire",
        "flood", "hurricane", "earthquake", "cop", "adnoc",
        "النفط", "الغاز", "أوبك", "الطاقة", "الطاقة المتجددة", "نووي", "المناخ", "انبعاثات", "فيضانات", "زلزال", "أدنوك",
    ],
}

WORLD_TOPIC_KEYWORDS = {
    "Middle East": [
        "gaza", "israel", "iran", "iraq", "syria", "lebanon", "yemen", "saudi", "qatar", "kuwait", "oman",
        "bahrain", "egypt", "jordan", "hezbollah", "hamas", "houthi", "red sea", "middle east", "gulf",
        "غزة", "إسرائيل", "إيران", "العراق", "سوريا", "لبنان", "اليمن", "السعودية", "قطر", "الكويت",
        "عمان", "البحرين", "مصر", "الأردن", "حزب الله", "حماس", "الحوثي", "الشرق الأوسط", "الخليج",
    ],
    "Global Business": [
        "market", "markets", "stocks", "oil", "opec", "inflation", "economy", "central bank", "interest rate",
        "tariff", "trade", "bank", "earnings", "gdp", "currency", "bitcoin", "crypto",
        "الأسواق", "النفط", "أوبك", "التضخم", "اقتصاد", "الفائدة", "تجارة", "بنك", "الأسهم", "الذهب",
    ],
    "Tech & Science": [
        "ai", "artificial intelligence", "chip", "chips", "semiconductor", "software", "cyber", "space", "nasa",
        "climate", "vaccine", "health", "study", "scientists", "robot", "quantum", "satellite",
        "ذكاء اصطناعي", "تقنية", "تكنولوجيا", "فضاء", "ناسا", "مناخ", "لقاح", "صحة", "علماء", "دراسة",
    ],
}

BAD_KEYWORDS = [
    "رياضة",
    "بطولة",
    "زفاف",
    "طلاق",
    "زوجة سابقة",
    "قصيدة",
    "شعر",
    "قصة حب",
    "شائعة",
    "شائعات",
    "شائعات صحية",
    "توفي",
    "وفاة",
    "وظائف",
    "توظيف",
    "فرص عمل",
    "غير صحيح",
    "مضلل",
    "تحقق",
    "فحص الحقائق",
    "بيسا تشيك",
    "دراجات",
    "كرة القدم",
    "ترفيه",
    "مشاهير",
    "sports",
    "championship",
    "wedding",
    "divorce",
    "ex-wife",
    "former wife",
    "custody",
    "princess haya",
    "zeynab",
    "poem",
    "love story",
    "rumor",
    "rumour",
    "health rumor",
    "health rumors",
    "passed away",
    "job",
    "jobs",
    "career",
    "careers",
    "vacancy",
    "vacancies",
    "false",
    "fact check",
    "pesacheck",
    "cycling",
    "football",
    "soccer",
    "entertainment",
    "celebrity",
]

IMPORTANT_KEYWORDS = [
    "الرئيس",
    "محمد بن زايد",
    "حكومة",
    "مجلس الوزراء",
    "قانون",
    "سياسة",
    "وزير",
    "وزارة",
    "وزارة الخارجية",
    "دبلوماسية",
    "اتفاق",
    "اتفاقية",
    "استراتيجي",
    "أمن",
    "الأمن",
    "دفاع",
    "القوات المسلحة",
    "عسكري",
    "اقتصاد",
    "اقتصادي",
    "تجارة",
    "استثمار",
    "أدنوك",
    "مبادلة",
    "طاقة",
    "ذكاء اصطناعي",
    "تكنولوجيا",
    "تقنية",
    "president",
    "government",
    "cabinet",
    "law",
    "policy",
    "minister",
    "foreign affairs",
    "diplomacy",
    "agreement",
    "strategic",
    "security",
    "defense",
    "defence",
    "military",
    "armed forces",
    "economy",
    "economic",
    "trade",
    "investment",
    "adnoc",
    "mubadala",
    "energy",
    "ai",
    "technology",
]

WORLD_CATEGORIES = ["World Affairs", "Middle East", "Global Business", "Tech & Science"]

CATEGORY_ORDER = [
    "Leadership",
    "Government",
    "Defense & Security",
    "Economy",
    "Foreign Relations",
    "Other Important UAE News",
    *WORLD_CATEGORIES,
]

CATEGORY_KEYWORDS = {
    "Leadership": [
        "الرئيس",
        "محمد بن زايد",
        "الشيخ محمد",
        "رئيس الدولة",
        "ولي عهد",
        "حاكم",
        "president",
        "mohamed bin zayed",
        "mbz",
        "sheikh mohamed",
        "crown prince",
        "ruler",
    ],
    "Government": [
        "حكومة",
        "مجلس الوزراء",
        "قانون",
        "سياسة",
        "وزير",
        "وزارة",
        "اتحادي",
        "هيئة",
        "government",
        "cabinet",
        "law",
        "policy",
        "minister",
        "ministry",
        "federal",
        "authority",
    ],
    "Defense & Security": [
        "أمن",
        "الأمن",
        "دفاع",
        "القوات المسلحة",
        "عسكري",
        "شرطة",
        "الداخلية",
        "security",
        "defense",
        "defence",
        "military",
        "armed forces",
        "police",
        "interior",
    ],
    "Economy": [
        "اقتصاد",
        "اقتصادي",
        "تجارة",
        "استثمار",
        "أدنوك",
        "مبادلة",
        "طاقة",
        "ذكاء اصطناعي",
        "تكنولوجيا",
        "تقنية",
        "أعمال",
        "economy",
        "economic",
        "trade",
        "investment",
        "adnoc",
        "mubadala",
        "energy",
        "ai",
        "technology",
        "business",
    ],
    "Foreign Relations": [
        "وزارة الخارجية",
        "الشؤون الخارجية",
        "دبلوماسية",
        "اتفاق",
        "اتفاقية",
        "استراتيجي",
        "قمة",
        "ثنائي",
        "تعاون",
        "شراكة",
        "سفير",
        "مباحثات",
        "زيارة",
        "foreign affairs",
        "diplomacy",
        "agreement",
        "strategic",
        "summit",
        "bilateral",
        "cooperation",
        "partnership",
        "ambassador",
        "talks",
        "visit",
    ],
}

SOURCE_SUFFIXES = [
    "وام",
    "وكالة أنباء الإمارات",
    "WAM",
    "Emirates News Agency",
    "The National",
    "Gulf News",
    "Khaleej Times",
    "UAE Government Portal",
]

TRUSTED_SOURCE_NAMES = [
    "وام",
    "وكالة أنباء الإمارات",
    "wam",
    "emirates news agency",
    "the national",
    "gulf news",
    "khaleej times",
    "البيان",
    "الإمارات اليوم",
    "الخليج",
    "الاتحاد",
    "sharjah24",
    "media office",
    "مكتب أبوظبي الإعلامي",
    "مكتب دبي الإعلامي",
    "mofa",
    "وزارة الخارجية",
    "uae government portal",
    "u.ae",
    "uae cabinet",
    "مجلس الوزراء",
    "ministry of economy",
    "ministry of finance",
    "central bank",
    "adnoc",
    "mubadala",
]

UAE_SIGNALS = [
    "الإمارات",
    "الإماراتي",
    "الإماراتية",
    "الدولة",
    "أبوظبي",
    "أبو ظبي",
    "دبي",
    "الشارقة",
    "محمد بن زايد",
    "الشيخ محمد",
    "أدنوك",
    "مبادلة",
    "uae",
    "u.a.e",
    "united arab emirates",
    "emirati",
    "emirates",
    "abu dhabi",
    "dubai",
    "sharjah",
    "mohamed bin zayed",
    "mbz",
    "sheikh mohamed",
    "adnoc",
    "mubadala",
]

def keyword_pattern(keyword: str) -> re.Pattern[str]:
    escaped = re.escape(keyword.lower()).replace(r"\ ", r"\s+")
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


def contains_keyword(text: str, keyword: str) -> bool:
    if has_arabic(keyword):
        return clean_text(keyword).lower() in clean_text(text).lower()
    return bool(keyword_pattern(keyword).search(text))


def contains_any_keyword(text: str, keywords: Iterable[str]) -> bool:
    normalized = text.lower()
    return any(contains_keyword(normalized, keyword) for keyword in keywords)


def strip_google_source_suffix(title: str, source: str) -> str:
    cleaned = clean_text(title)
    candidates = [source, *SOURCE_SUFFIXES]
    for candidate in candidates:
        candidate = clean_text(candidate)
        if not candidate:
            continue
        suffix = f" - {candidate}"
        if cleaned.lower().endswith(suffix.lower()):
            return cleaned[: -len(suffix)].strip()
    return cleaned


def normalize_for_dedupe(title: str) -> str:
    title = strip_google_source_suffix(title, "")
    title = title.lower()
    title = re.sub(r"[^\w]+", " ", title, flags=re.UNICODE)
    return re.sub(r"\s+", " ", title).strip()


DEDUP_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "uae",
    "united",
    "arab",
    "emirates",
    "dubai",
    "abu",
    "dhabi",
    "says",
    "new",
    "news",
    "الإمارات",
    "الإماراتي",
    "الإماراتية",
    "دولة",
    "دبي",
    "أبوظبي",
    "أبو",
    "ظبي",
    "قال",
    "عن",
    "على",
    "في",
    "من",
    "إلى",
    "مع",
    "هذا",
    "هذه",
    "بن",
    "آل",
}


def story_tokens(title: str) -> set[str]:
    normalized = normalize_for_dedupe(title)
    tokens = set(re.findall(r"[\w\u0600-\u06FF]+", normalized, flags=re.UNICODE))
    return {token for token in tokens if len(token) > 2 and token not in DEDUP_STOPWORDS}


def find_near_duplicate(tokens: set[str], seen: list[tuple[set[str], int]]) -> int | None:
    """Index of the already-kept story that `tokens` repeats, or None."""
    if len(tokens) < 5:
        return None

    for seen_tokens, index in seen:
        if len(seen_tokens) < 5:
            continue
        intersection = len(tokens & seen_tokens)
        if intersection < 5:
            continue

        smaller_overlap = intersection / min(len(tokens), len(seen_tokens))
        jaccard = intersection / len(tokens | seen_tokens)
        if smaller_overlap >= 0.82 or jaccard >= 0.72:
            return index

    return None


def source_from_entry(entry: object, fallback: str) -> str:
    source = ""
    entry_source = entry.get("source", {}) if hasattr(entry, "get") else {}
    if isinstance(entry_source, dict):
        source = clean_text(entry_source.get("title", ""))
    if source:
        return source

    title = clean_text(entry.get("title", "")) if hasattr(entry, "get") else ""
    if " - " in title:
        suffix = title.rsplit(" - ", 1)[-1].strip()
        if 2 <= len(suffix) <= 45:
            return suffix
    return fallback


def parsed_datetime(entry: object) -> datetime | None:
    if not hasattr(entry, "get"):
        return None
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc).astimezone(UAE_TIMEZONE)
    except (TypeError, ValueError):
        return None


def category_for(text: str) -> str:
    scores: dict[str, int] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        scores[category] = sum(1 for keyword in keywords if contains_keyword(text, keyword))

    best_category = "Other Important UAE News"
    best_score = 0
    for category in CATEGORY_ORDER:
        score = scores.get(category, 0)
        if score > best_score:
            best_category = category
            best_score = score
    return best_category


def world_category_for(text: str, feed: RssFeed) -> str:
    """Pick a world-news section: the feed's topic hint counts as one keyword hit, so two real hits override it."""
    best_category = feed.category if feed.category in WORLD_CATEGORIES else "World Affairs"
    best_score = 1
    for category, keywords in WORLD_TOPIC_KEYWORDS.items():
        score = sum(1 for keyword in keywords if contains_keyword(text, keyword))
        if score > best_score:
            best_category, best_score = category, score
    return best_category


def topics_for(text: str, feed: RssFeed) -> tuple[str, ...]:
    """Topics whose keywords appear in the text (strongest first, at most three), plus the feed's own hint."""
    scored = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if contains_keyword(text, keyword))
        if feed.topic == topic:
            hits += 2
        if hits:
            scored.append((hits, topic))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return tuple(topic for _hits, topic in scored[:3])


def region_for(uae_related: bool, category: str) -> str:
    if uae_related:
        return "uae"
    return "middle_east" if category == "Middle East" else "world"


def entry_image_url(entry: object, base_url: str) -> str:
    """Pick an image straight from the feed entry (media tags, enclosures or the summary's <img>)."""
    if not hasattr(entry, "get"):
        return ""
    candidates: list[tuple[int, str]] = []
    for key in ("media_content", "media_thumbnail"):
        for media in entry.get(key, []) or []:
            if isinstance(media, dict) and media.get("url"):
                width = int(media["width"]) if str(media.get("width", "")).isdigit() else 0
                candidates.append((width, media["url"]))
    for link in entry.get("links", []) or []:
        if isinstance(link, dict) and str(link.get("type", "")).startswith("image/") and link.get("href"):
            candidates.append((0, link["href"]))
    for _width, url in sorted(candidates, key=lambda pair: -pair[0]):
        url = prefer_larger_image(absolute_url(url, base_url))
        if url and not is_placeholder_image_url(url):
            return url
    return image_url_from_summary(entry.get("summary", ""), base_url)


def article_score(text: str, source: str, feed: RssFeed, published_at: datetime | None) -> int:
    score = feed.priority
    score += sum(2 for keyword in IMPORTANT_KEYWORDS if contains_keyword(text, keyword))

    source_lower = source.lower()
    if any(name in source_lower for name in TRUSTED_SOURCE_NAMES):
        score += 4

    if published_at:
        age_hours = (datetime.now(UAE_TIMEZONE) - published_at).total_seconds() / 3600
        if age_hours <= 24:
            score += 4
        elif age_hours <= 72:
            score += 2
    return score


def is_uae_related(text: str) -> bool:
    return contains_any_keyword(text, UAE_SIGNALS)


def absolute_url(url: str, base_url: str) -> str:
    url = clean_text(url)
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    return urljoin(base_url, url)


def prefer_larger_image(url: str) -> str:
    if "googleusercontent.com" in url:
        return re.sub(r"=s0-w\d+(?:-h\d+)?", "=s0-w1200", url)
    return url


def is_placeholder_image_url(url: str) -> bool:
    lowered = url.lower()
    placeholder_parts = [
        "gnews/logo",
        "google_news_",
        "j6_cofbogxhri9i",
        "-dr60l-k8vnyi99nzovm9hlxyzwq85gmd",
        "/assets/images/logo/",
        "/logo/",
        "logo.png",
        "logo.jpg",
        "logo.svg",
        "mofaicuaelogo",
        "uaelogo",
        "favicon",
    ]
    return any(part in lowered for part in placeholder_parts)


def image_url_from_summary(summary: str, base_url: str) -> str:
    if not summary:
        return ""
    soup = BeautifulSoup(summary, "html.parser")
    image = soup.find("img")
    if not image:
        return ""
    image_url = prefer_larger_image(absolute_url(image.get("src", ""), base_url))
    return "" if is_placeholder_image_url(image_url) else image_url


def image_url_from_soup(soup: BeautifulSoup, base_url: str) -> str:
    selectors = [
        ("property", "og:image"),
        ("property", "og:image:url"),
        ("name", "twitter:image"),
        ("name", "twitter:image:src"),
    ]

    for attr, value in selectors:
        tag = soup.find("meta", attrs={attr: value})
        if tag and tag.get("content"):
            image_url = prefer_larger_image(absolute_url(tag["content"], base_url))
            if not is_placeholder_image_url(image_url):
                return image_url

    tag = soup.find("link", rel=lambda rel: rel and "image_src" in rel)
    if tag and tag.get("href"):
        image_url = prefer_larger_image(absolute_url(tag["href"], base_url))
        if not is_placeholder_image_url(image_url):
            return image_url

    return ""


def text_from_html(value: str) -> str:
    if not value:
        return ""
    return clean_text(BeautifulSoup(value, "html.parser").get_text(" "))


def trim_brief(text: str, max_chars: int = BRIEF_MAX_CHARS) -> str:
    text = clean_text(text)
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    sentence_excerpt = sentence_safe_excerpt(text, max_chars=max_chars, max_sentences=3)
    if sentence_excerpt:
        return sentence_excerpt
    return word_safe_excerpt(text, max_chars)


def description_from_soup(soup: BeautifulSoup) -> str:
    selectors = [
        ("property", "og:description"),
        ("name", "description"),
        ("name", "twitter:description"),
    ]
    for attr, value in selectors:
        tag = soup.find("meta", attrs={attr: value})
        if tag and tag.get("content"):
            return trim_brief(tag["content"])
    return ""


def brief_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[\w\u0600-\u06FF]+", text.lower(), flags=re.UNICODE) if len(token) > 2}


def brief_is_weak(brief: str, title: str) -> bool:
    brief = clean_text(brief)
    if not brief:
        return True
    if len(brief) < BRIEF_MIN_CHARS:
        return True

    lowered = brief.lower()
    generic_phrases = [
        "read more",
        "click here",
        "subscribe",
        "follow us",
        "all rights reserved",
        "cookie",
        "javascript",
        "تابعونا",
        "اقرأ المزيد",
        "للمزيد",
        "جميع الحقوق محفوظة",
        "اشترك",
        "ملفات تعريف الارتباط",
    ]
    if any(phrase in lowered for phrase in generic_phrases):
        return True

    title_tokens = brief_tokens(title)
    brief_word_tokens = brief_tokens(brief)
    if title_tokens:
        overlap = len(title_tokens & brief_word_tokens) / len(title_tokens)
        if overlap >= 0.82 and len(brief) < len(title) + 90:
            return True

    return False


def json_ld_candidates(data: object) -> list[str]:
    candidates: list[str] = []
    if isinstance(data, list):
        for item in data:
            candidates.extend(json_ld_candidates(item))
        return candidates

    if not isinstance(data, dict):
        return candidates

    graph = data.get("@graph")
    if graph:
        candidates.extend(json_ld_candidates(graph))

    item_type = data.get("@type", "")
    if isinstance(item_type, list):
        type_text = " ".join(str(item) for item in item_type)
    else:
        type_text = str(item_type)

    if any(kind in type_text.lower() for kind in ["newsarticle", "article", "reportagenewsarticle"]):
        for key in ["description", "articleBody"]:
            value = data.get(key)
            if isinstance(value, str):
                candidates.append(value)

    for key in ["mainEntity", "mainEntityOfPage"]:
        if key in data:
            candidates.extend(json_ld_candidates(data[key]))

    return candidates


def json_ld_briefs_from_soup(soup: BeautifulSoup) -> list[str]:
    candidates: list[str] = []
    for script in soup.find_all("script", attrs={"type": lambda value: value and "ld+json" in value}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates.extend(trim_brief(text_from_html(candidate)) for candidate in json_ld_candidates(data))
    return [candidate for candidate in candidates if candidate]


def paragraph_is_noise(text: str) -> bool:
    text = clean_text(text)
    if len(text) < BRIEF_MIN_CHARS:
        return True
    lowered = text.lower()
    noise_phrases = [
        "read more",
        "related stories",
        "advertisement",
        "subscribe",
        "sign up",
        "follow us",
        "cookies",
        "all rights reserved",
        "اقرأ أيضا",
        "اقرأ المزيد",
        "موضوعات متعلقة",
        "إعلان",
        "تابعونا",
        "اشترك",
        "جميع الحقوق محفوظة",
    ]
    return any(phrase in lowered for phrase in noise_phrases)


def paragraph_briefs_from_soup(soup: BeautifulSoup) -> list[str]:
    soup_copy = BeautifulSoup(str(soup), "html.parser")
    for tag in soup_copy(["script", "style", "nav", "footer", "header", "form", "aside"]):
        tag.decompose()

    selectors = [
        "article p",
        "[itemprop='articleBody'] p",
        ".article-content p",
        ".story-content p",
        ".entry-content p",
        ".post-content p",
        ".content p",
        "p",
    ]
    candidates: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        for paragraph in soup_copy.select(selector):
            text = trim_brief(paragraph.get_text(" "))
            key = normalize_for_dedupe(text)
            if not key or key in seen or paragraph_is_noise(text):
                continue
            seen.add(key)
            candidates.append(text)
        if candidates:
            break
    return candidates


def combine_paragraph_brief(paragraphs: list[str], max_chars: int = BRIEF_MAX_CHARS) -> str:
    combined_parts: list[str] = []
    current_length = 0

    for paragraph in paragraphs:
        paragraph = clean_text(paragraph)
        if not paragraph:
            continue

        projected_length = current_length + len(paragraph) + (1 if combined_parts else 0)
        if combined_parts and projected_length > max_chars:
            break

        combined_parts.append(paragraph)
        current_length = projected_length

        if current_length >= int(max_chars * 0.72):
            break

    return trim_brief(" ".join(combined_parts), max_chars=max_chars)


def best_available_brief(candidates: list[str], title: str) -> str:
    cleaned = [trim_brief(candidate) for candidate in candidates if clean_text(candidate)]
    strong = [candidate for candidate in cleaned if not brief_is_weak(candidate, title)]
    if strong:
        return max(strong, key=len)
    return max(cleaned, key=len) if cleaned else ""


def best_brief_from_soup(article: Article, soup: BeautifulSoup, fallback: str) -> str:
    metadata_brief = description_from_soup(soup)
    json_ld_briefs = json_ld_briefs_from_soup(soup)
    paragraph_briefs = paragraph_briefs_from_soup(soup)
    combined_paragraph_brief = combine_paragraph_brief(paragraph_briefs)

    preferred_brief = best_available_brief(
        [combined_paragraph_brief, *json_ld_briefs, metadata_brief],
        article.title,
    )
    if preferred_brief:
        return preferred_brief

    return trim_brief(fallback)


def is_google_news_article_url(link: str) -> bool:
    return "news.google.com" in link and "/rss/articles/" in link


def decode_google_news_url(session: requests.Session, link: str) -> str:
    if not is_google_news_article_url(link):
        return link

    if GoogleDecoder is None:
        return ""
    try:
        result = GoogleDecoder().decode_google_news_url(link)
    except Exception:
        return ""
    if not isinstance(result, dict) or not result.get("status"):
        return ""
    return clean_text(result.get("decoded_url", ""))


def publisher_article_details(session: requests.Session, article: Article) -> tuple[str, str, str]:
    publisher_url = decode_google_news_url(session, article.link) or article.link
    brief = trim_brief(text_from_html(article.summary))
    image_url = image_url_from_summary(article.summary, article.link)

    if publisher_url:
        try:
            response = session.get(publisher_url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
        except requests.RequestException:
            return publisher_url, image_url, brief

        soup = BeautifulSoup(response.text, "html.parser")
        page_image_url = image_url_from_soup(soup, response.url)
        if page_image_url:
            image_url = page_image_url

        brief = best_brief_from_soup(article, soup, brief)

    return publisher_url, image_url, brief


def fetch_feed_entries(
    feed: RssFeed,
    session: requests.Session | None = None,
    timeout: float | None = None,
    retries: int | None = None,
) -> list[object] | None:
    """Return a feed's entries, or None when every attempt failed (so outages are not mistaken for quiet days)."""
    timeout = timeout or REQUEST_TIMEOUT_SECONDS
    retries = retries or FETCH_RETRIES
    limit = MAX_ENTRIES_PER_WORLD_FEED if feed.scope == "world" else MAX_ENTRIES_PER_FEED
    owns_session = session is None
    session = session or requests.Session()
    last_error: object = "unknown error"
    try:
        for attempt in range(retries):
            try:
                response = session.get(feed.url, headers=REQUEST_HEADERS, timeout=timeout)
                response.raise_for_status()
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 < retries:
                    time.sleep(1 + attempt)
                continue

            parsed = feedparser.parse(response.content)
            entries = list(getattr(parsed, "entries", []))
            if not entries and getattr(parsed, "bozo", False):
                last_error = getattr(parsed, "bozo_exception", "unparseable feed")
                continue
            return entries[:limit]
    finally:
        if owns_session:
            session.close()

    print(f"Warning: RSS feed failed for {feed.label}: {last_error}")
    return None


def fetch_all_feeds(
    feeds: list[RssFeed],
    workers: int = FETCH_WORKERS,
    timeout: float | None = None,
    retries: int | None = None,
    deadline: float | None = None,
) -> list[tuple[RssFeed, list[object] | None]]:
    """Fetch every feed at the same time. Results keep the order of `feeds`; feeds still running at
    `deadline` seconds are reported as failed so one slow publisher cannot hold up the rest."""
    pool = ThreadPoolExecutor(max_workers=max(1, min(workers, len(feeds))))
    futures = [pool.submit(partial(fetch_feed_entries, feed, None, timeout, retries)) for feed in feeds]
    wait(futures, timeout=deadline)
    pool.shutdown(wait=False, cancel_futures=True)
    results = [future.result() if future.done() and not future.exception() else None for future in futures]
    return list(zip(feeds, results))


def active_feeds() -> list[RssFeed]:
    return [*RSS_FEEDS, *WORLD_RSS_FEEDS] if WORLD_NEWS_ENABLED else list(RSS_FEEDS)


def app_feeds() -> list[RssFeed]:
    """The lighter feed set the live app refreshes: general UAE queries and main UAE outlets, plus all world feeds."""
    return [*RSS_FEEDS[:24], *WORLD_RSS_FEEDS]


def collect_articles(
    feeds: list[RssFeed] | None = None,
    workers: int = FETCH_WORKERS,
    timeout: float | None = None,
    retries: int | None = None,
    deadline: float | None = None,
    stats: dict | None = None,
) -> list[Article]:
    articles: list[Article] = []
    key_index: dict[str, int] = {}  # normalized title -> index in `articles`
    story_sets: list[tuple[set[str], int]] = []
    also_map: dict[int, list[tuple[str, str, str]]] = {}
    now = datetime.now(UAE_TIMEZONE)

    feeds = feeds if feeds is not None else active_feeds()
    fetched = fetch_all_feeds(feeds, workers, timeout, retries, deadline)
    failed = [feed.label for feed, entries in fetched if entries is None]
    if stats is not None:
        stats.update(total=len(feeds), ok=len(feeds) - len(failed), failed=failed)
    print(f"المصادر: {len(feeds) - len(failed)} تعمل من أصل {len(feeds)}")
    if failed:
        print(f"Warning: {len(failed)} feeds failed: {', '.join(failed[:12])}{' ...' if len(failed) > 12 else ''}")
    if len(failed) == len(feeds):
        raise RuntimeError("Every news feed failed - check the network connection before sending a brief.")

    for feed, entries in fetched:
        is_world_feed = feed.scope == "world"
        for entry in entries or []:
            raw_title = clean_text(entry.get("title", "")) if hasattr(entry, "get") else ""
            if not raw_title:
                continue

            source = source_from_entry(entry, feed.label)
            title = strip_google_source_suffix(raw_title, source)
            if REQUIRE_ARABIC_HEADLINES and not has_arabic(title):
                continue
            dedupe_key = normalize_for_dedupe(title)
            if not dedupe_key:
                continue
            link = clean_text(entry.get("link", "")) if hasattr(entry, "get") else ""
            tokens = story_tokens(title)
            repeat_of = key_index.get(dedupe_key)
            if repeat_of is None:
                repeat_of = find_near_duplicate(tokens, story_sets)
            if repeat_of is not None:
                # Same story from another outlet: keep it as extra coverage instead of dropping it silently.
                coverage = also_map.setdefault(repeat_of, [])
                if source != articles[repeat_of].source and all(source != name for name, _l, _t in coverage):
                    coverage.append((source, link, title))
                continue

            keyword_text = f"{title} {source}"
            uae_related = is_uae_related(keyword_text)
            if is_world_feed:
                if contains_any_keyword(title, WORLD_BAD_KEYWORDS):
                    continue
                if uae_related and contains_any_keyword(keyword_text, BAD_KEYWORDS):
                    continue
            else:
                if not uae_related:
                    continue
                if contains_any_keyword(keyword_text, BAD_KEYWORDS):
                    continue
                if not GLOBAL_UAE_COVERAGE and not contains_any_keyword(keyword_text, IMPORTANT_KEYWORDS):
                    continue

            published_at = parsed_datetime(entry)
            max_age_days = MAX_WORLD_ARTICLE_AGE_DAYS if is_world_feed and not uae_related else MAX_ARTICLE_AGE_DAYS
            if published_at and now - published_at > timedelta(days=max_age_days):
                continue

            if is_world_feed and not uae_related:
                category = world_category_for(keyword_text, feed)
            else:
                category = category_for(keyword_text)
            score = article_score(keyword_text, source, feed, published_at)
            if is_world_feed and uae_related:
                score += 6  # a world story that mentions the UAE outranks generic world news
            summary = entry.get("summary", "") if hasattr(entry, "get") else ""

            key_index[dedupe_key] = len(articles)
            if tokens:
                story_sets.append((tokens, len(articles)))
            articles.append(
                Article(
                    title=title,
                    source=source,
                    feed_label=feed.label,
                    category=category,
                    score=score,
                    published_at=published_at,
                    link=link,
                    summary=summary,
                    topics=topics_for(keyword_text, feed),
                    region=region_for(uae_related, category),
                    uae_mention=uae_related,
                    image=entry_image_url(entry, link),
                )
            )

    for index, coverage in also_map.items():
        article = articles[index]
        # Stories many outlets carry matter more: +2 per extra outlet, capped.
        articles[index] = replace(article, also=tuple(coverage[:8]), score=article.score + 2 * min(len(coverage), 6))

    articles.sort(
        key=lambda article: (
            CATEGORY_ORDER.index(article.category),
            -article.score,
            -(article.published_at.timestamp() if article.published_at else 0),
            article.title.lower(),
        )
    )
    return articles
