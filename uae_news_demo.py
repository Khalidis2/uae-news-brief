from __future__ import annotations

import html
import io
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus, urljoin

import arabic_reshaper
import feedparser
import requests
from bs4 import BeautifulSoup
from bidi.algorithm import get_display
from googlenewsdecoder import GoogleDecoder
from PIL import Image, ImageDraw, ImageFont, ImageOps, features
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


PROJECT_DIR = Path(__file__).resolve().parent
BRIEFS_DIR = PROJECT_DIR / "briefs"
LATEST_OUTPUT_PATH = PROJECT_DIR / "uae_daily_brief.pdf"
OUTPUT_PATH = LATEST_OUTPUT_PATH
FONT_DIR = PROJECT_DIR / "assets" / "fonts"
RAQM_AVAILABLE = features.check("raqm")
FONT_LAYOUT_ENGINE = getattr(getattr(ImageFont, "Layout", object), "RAQM", None) if RAQM_AVAILABLE else None

IMAGE_WIDTH = 1080
IMAGE_HEIGHT = 1600
MARGIN_X = 68
HEADER_BOTTOM = 205
FOOTER_TOP = 1510
HERO_IMAGE_TOP = 210
HERO_IMAGE_HEIGHT = 300
HERO_TEXT_GAP = 24
HERO_BOTTOM_GAP = 36
HERO_LOOKUP_LIMIT = 25
MAX_PDF_ARTICLES = 24
MAX_PDF_ARTICLES_PER_CATEGORY = 4
PDF_CARD_GAP = 18
PDF_CARD_PADDING = 22
PDF_CARD_RADIUS = 8
PDF_LEAD_IMAGE_HEIGHT = 395
PDF_LEAD_PADDING = 28
PDF_TITLE_MAX_LINES = 3
PDF_LEAD_TITLE_MAX_LINES = 3
PDF_LEAD_BRIEF_MAX_LINES = 3
PDF_THUMBNAIL_WIDTH = 300
PDF_THUMBNAIL_HEIGHT = 190
PDF_CONTENT_TOP = 210
PDF_SUMMARY_HERO_HEIGHT = 340
PDF_SUMMARY_STAT_HEIGHT = 76
PDF_SUMMARY_CATEGORY_HEIGHT = 152
PDF_SUMMARY_CATEGORY_GAP = 14
PDF_SECTION_HEADER_HEIGHT = 86
PDF_SECTION_FEATURE_HEIGHT = 360
PDF_SECTION_COMPACT_HEIGHT = 190
PDF_SECTION_PAGE_GAP = 18
PDF_SECTION_IMAGE_WIDTH = 372
PDF_RESOLUTION = 144.0
PDF_LINK_SCALE = 72.0 / PDF_RESOLUTION
BRIEF_MAX_CHARS = 560
BRIEF_MIN_CHARS = 80
PDF_BRIEF_MAX_LINES = 4
MAX_HEADLINES_PER_SECTION = 3
MAX_ENTRIES_PER_FEED = 12
REQUEST_TIMEOUT_SECONDS = 8
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


@dataclass(frozen=True)
class PdfArticle:
    article: Article
    image: Image.Image | None
    publisher_url: str
    brief: str


@dataclass(frozen=True)
class PdfLinkArea:
    page_index: int
    rect: tuple[int, int, int, int]
    url: str


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
    global_source_feed("The National", "thenationalnews.com", 7, "en"),
    global_source_feed("Gulf News", "gulfnews.com", 6, "en"),
    global_source_feed("Khaleej Times", "khaleejtimes.com", 6, "en"),
    global_source_feed("البيان", "albayan.ae", 7, "ar"),
    global_source_feed("الإمارات اليوم", "emaratalyoum.com", 7, "ar"),
    global_source_feed("الخليج", "alkhaleej.ae", 7, "ar"),
    global_source_feed("مكتب أبوظبي الإعلامي", "mediaoffice.abudhabi", 8, "ar"),
    global_source_feed("وزارة الخارجية الإماراتية", "mofa.gov.ae", 8, "ar"),
    global_source_feed("Sharjah24", "sharjah24.ae", 6, "ar"),
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

CATEGORY_ORDER = [
    "Leadership",
    "Government",
    "Defense & Security",
    "Economy",
    "Foreign Relations",
    "Other Important UAE News",
]

CATEGORY_LABELS = {
    "Leadership": "القيادة",
    "Government": "الحكومة",
    "Defense & Security": "الدفاع والأمن",
    "Economy": "الاقتصاد",
    "Foreign Relations": "العلاقات الخارجية",
    "Other Important UAE News": "أخبار إماراتية مهمة",
}

CATEGORY_SUBTITLES = {
    "Leadership": "تحركات القيادة والرسائل الرسمية الأبرز.",
    "Government": "قرارات وسياسات وخدمات تؤثر على الدولة.",
    "Defense & Security": "ملفات الأمن والدفاع والتعاون الشرطي.",
    "Economy": "الأعمال والاستثمار والطاقة والتقنية.",
    "Foreign Relations": "الدبلوماسية والشراكات والتحركات الخارجية.",
    "Other Important UAE News": "قصص إماراتية مهمة خارج الأقسام الرئيسية.",
}

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

COLORS = {
    "paper": (246, 248, 250),
    "surface": (255, 255, 255),
    "shadow": (226, 233, 238),
    "ink": (28, 38, 51),
    "muted": (98, 111, 128),
    "soft_muted": (132, 145, 160),
    "line": (222, 228, 235),
    "light_line": (238, 242, 246),
    "accent": (0, 115, 125),
    "accent_soft": (230, 246, 247),
    "flag_red": (196, 45, 54),
    "Leadership": (130, 88, 34),
    "Government": (0, 112, 150),
    "Defense & Security": (67, 98, 80),
    "Economy": (27, 125, 72),
    "Foreign Relations": (77, 95, 166),
    "Other Important UAE News": (94, 103, 115),
}

ARABIC_CHAR_RE = re.compile(r"[\u0600-\u06FF]")

ARABIC_DAYS = [
    "الإثنين",
    "الثلاثاء",
    "الأربعاء",
    "الخميس",
    "الجمعة",
    "السبت",
    "الأحد",
]

ARABIC_MONTHS = {
    1: "يناير",
    2: "فبراير",
    3: "مارس",
    4: "أبريل",
    5: "مايو",
    6: "يونيو",
    7: "يوليو",
    8: "أغسطس",
    9: "سبتمبر",
    10: "أكتوبر",
    11: "نوفمبر",
    12: "ديسمبر",
}


def dated_output_path(value: datetime | None = None) -> Path:
    value = value or datetime.now(UAE_TIMEZONE)
    day_name = value.strftime("%A").lower()
    return BRIEFS_DIR / f"uae_daily_brief_{value:%Y-%m-%d}_{day_name}.pdf"


def arabic_brief_title(value: datetime | None = None) -> str:
    value = value or datetime.now(UAE_TIMEZONE)
    return f"موجز الإمارات اليومي - {ARABIC_DAYS[value.weekday()]} {value.day:02d} {ARABIC_MONTHS[value.month]} {value.year}"


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def complete_sentence_chunks(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    return [match.group(0).strip() for match in re.finditer(r"[^.!?؟]+[.!?؟]+", text) if match.group(0).strip()]


def sentence_safe_excerpt(
    text: str,
    max_chars: int,
    max_sentences: int = 2,
    allow_short_unsentenced: bool = False,
) -> str:
    text = clean_text(text)
    if not text:
        return ""
    if len(text) <= max_chars and (text[-1] in ".!?؟" or allow_short_unsentenced):
        return text

    selected: list[str] = []
    for sentence in complete_sentence_chunks(text):
        candidate = " ".join([*selected, sentence]).strip()
        if selected and len(candidate) > max_chars:
            break
        if not selected and len(sentence) > max_chars:
            break
        selected.append(sentence)
        if len(selected) >= max_sentences:
            break
    return " ".join(selected).strip()


def word_safe_excerpt(text: str, max_chars: int) -> str:
    text = clean_text(text)
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars].rsplit(" ", 1)[0].strip()
    return f"{clipped}..." if clipped else f"{text[:max_chars].strip()}..."


def has_arabic(text: str) -> bool:
    return bool(ARABIC_CHAR_RE.search(text))


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


def is_near_duplicate_story(tokens: set[str], seen_token_sets: list[set[str]]) -> bool:
    if len(tokens) < 5:
        return False

    for seen_tokens in seen_token_sets:
        if len(seen_tokens) < 5:
            continue
        intersection = len(tokens & seen_tokens)
        if intersection < 5:
            continue

        smaller_overlap = intersection / min(len(tokens), len(seen_tokens))
        jaccard = intersection / len(tokens | seen_tokens)
        if smaller_overlap >= 0.82 or jaccard >= 0.72:
            return True

    return False


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


def image_url_from_page(session: requests.Session, link: str) -> str:
    if not link:
        return ""
    try:
        response = session.get(link, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException:
        return ""

    soup = BeautifulSoup(response.text, "html.parser")
    return image_url_from_soup(soup, response.url)


def is_google_news_article_url(link: str) -> bool:
    return "news.google.com" in link and "/rss/articles/" in link


def decode_google_news_url(session: requests.Session, link: str) -> str:
    if not is_google_news_article_url(link):
        return link

    try:
        result = GoogleDecoder().decode_google_news_url(link)
    except Exception:
        return ""
    if not isinstance(result, dict) or not result.get("status"):
        return ""
    return clean_text(result.get("decoded_url", ""))


def article_image_url(session: requests.Session, article: Article) -> str:
    publisher_link = decode_google_news_url(session, article.link)
    if publisher_link and publisher_link != article.link:
        image_url = image_url_from_page(session, publisher_link)
        if image_url:
            return image_url

    return image_url_from_summary(article.summary, article.link) or image_url_from_page(session, article.link)


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


def download_image(session: requests.Session, image_url: str) -> Image.Image | None:
    if not image_url:
        return None
    try:
        response = session.get(image_url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content))
        image.load()
        if image.width < 420 or image.height < 220:
            return None
        return image.convert("RGB")
    except (requests.RequestException, OSError):
        return None


def find_lead_image(articles: list[Article]) -> tuple[Article, Image.Image] | None:
    with requests.Session() as session:
        for article in articles[:HERO_LOOKUP_LIMIT]:
            image_url = article_image_url(session, article)
            image = download_image(session, image_url)
            if image:
                return article, image
    return None


def fetch_feed_entries(feed: RssFeed, session: requests.Session) -> list[object]:
    try:
        response = session.get(feed.url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"Warning: RSS feed failed for {feed.label}: {exc}")
        return []

    parsed = feedparser.parse(response.content)
    if getattr(parsed, "bozo", False):
        print(f"Warning: RSS parse issue for {feed.label}: {getattr(parsed, 'bozo_exception', 'unknown error')}")
    return list(getattr(parsed, "entries", []))[:MAX_ENTRIES_PER_FEED]


def collect_articles() -> list[Article]:
    articles: list[Article] = []
    seen_titles: set[str] = set()
    seen_story_token_sets: list[set[str]] = []

    with requests.Session() as session:
        for feed in RSS_FEEDS:
            for entry in fetch_feed_entries(feed, session):
                raw_title = clean_text(entry.get("title", "")) if hasattr(entry, "get") else ""
                if not raw_title:
                    continue

                source = source_from_entry(entry, feed.label)
                title = strip_google_source_suffix(raw_title, source)
                if REQUIRE_ARABIC_HEADLINES and not has_arabic(title):
                    continue
                dedupe_key = normalize_for_dedupe(title)
                if not dedupe_key or dedupe_key in seen_titles:
                    continue
                tokens = story_tokens(title)
                if is_near_duplicate_story(tokens, seen_story_token_sets):
                    continue

                keyword_text = f"{title} {source}"
                if not is_uae_related(keyword_text):
                    continue
                if contains_any_keyword(keyword_text, BAD_KEYWORDS):
                    continue
                if not GLOBAL_UAE_COVERAGE and not contains_any_keyword(keyword_text, IMPORTANT_KEYWORDS):
                    continue

                published_at = parsed_datetime(entry)
                if published_at and datetime.now(UAE_TIMEZONE) - published_at > timedelta(days=MAX_ARTICLE_AGE_DAYS):
                    continue

                category = category_for(keyword_text)
                score = article_score(keyword_text, source, feed, published_at)
                link = clean_text(entry.get("link", "")) if hasattr(entry, "get") else ""
                summary = entry.get("summary", "") if hasattr(entry, "get") else ""

                seen_titles.add(dedupe_key)
                if tokens:
                    seen_story_token_sets.append(tokens)
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
                    )
                )

    articles.sort(
        key=lambda article: (
            CATEGORY_ORDER.index(article.category),
            -article.score,
            -(article.published_at.timestamp() if article.published_at else 0),
            article.title.lower(),
        )
    )
    return articles


def font_path(file_name: str) -> str:
    return str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / file_name)


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    local_candidates = (
        [
            "NotoNaskhArabic-Variable.ttf",
            "NotoSansArabic-Bold.ttf",
            "Cairo-Bold.ttf",
            "Cairo-Variable.ttf",
            "IBM-Plex-Sans-Arabic-Bold.ttf",
        ]
        if bold
        else [
            "NotoNaskhArabic-Variable.ttf",
            "NotoSansArabic-Regular.ttf",
            "Cairo-Regular.ttf",
            "Cairo-Variable.ttf",
            "IBM-Plex-Sans-Arabic-Regular.ttf",
        ]
    )
    for candidate in local_candidates:
        path = FONT_DIR / candidate
        if path.exists():
            try:
                if FONT_LAYOUT_ENGINE is not None:
                    return ImageFont.truetype(str(path), size, layout_engine=FONT_LAYOUT_ENGINE)
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue

    candidates = ["tahomabd.ttf", "arialbd.ttf", "segoeuib.ttf"] if bold else ["tahoma.ttf", "arial.ttf", "segoeui.ttf"]
    for candidate in candidates:
        try:
            if FONT_LAYOUT_ENGINE is not None:
                return ImageFont.truetype(font_path(candidate), size, layout_engine=FONT_LAYOUT_ENGINE)
            return ImageFont.truetype(font_path(candidate), size)
        except OSError:
            continue
    return ImageFont.load_default()


def visual_text(text: str) -> str:
    text = clean_text(text)
    if has_arabic(text) and not RAQM_AVAILABLE:
        return get_display(arabic_reshaper.reshape(text))
    return text


def text_render_options(text: str) -> dict[str, str]:
    if has_arabic(text) and RAQM_AVAILABLE:
        return {"direction": "rtl", "language": "ar"}
    return {}


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    anchor: str = "la",
) -> None:
    prepared_text = visual_text(text)
    draw.text(
        xy,
        prepared_text,
        fill=fill,
        font=font,
        anchor=anchor,
        **text_render_options(prepared_text),
    )


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    prepared_text = visual_text(text)
    bbox = draw.textbbox((0, 0), prepared_text, font=font, **text_render_options(prepared_text))
    return bbox[2] - bbox[0]


def line_height(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), "Ag", font=font)
    return bbox[3] - bbox[1]


def split_long_word(draw: ImageDraw.ImageDraw, word: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for character in word:
        candidate = f"{current}{character}"
        if current and text_width(draw, candidate, font) > max_width:
            chunks.append(current)
            current = character
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = clean_text(text).split()
    if not words:
        return []

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)
            current = ""

        if text_width(draw, word, font) > max_width:
            chunks = split_long_word(draw, word, font, max_width)
            lines.extend(chunks[:-1])
            current = chunks[-1] if chunks else ""
        else:
            current = word

    if current:
        lines.append(current)
    return lines


def limited_text_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    lines = wrap_text(draw, text, font, max_width)
    if len(lines) <= max_lines:
        return lines

    fitted = lines[:max_lines]
    suffix = "..."
    final_line = fitted[-1].rstrip()
    while final_line and text_width(draw, f"{final_line}{suffix}", font) > max_width:
        final_line = final_line[:-1].rstrip()
    fitted[-1] = f"{final_line}{suffix}" if final_line else suffix
    return fitted


def complete_sentence_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int,
    max_chars: int,
    max_sentences: int = 2,
) -> list[str]:
    excerpt = sentence_safe_excerpt(text, max_chars=max_chars, max_sentences=max_sentences)
    if not excerpt:
        return []

    sentences = complete_sentence_chunks(excerpt)
    if not sentences:
        return []

    while sentences:
        candidate = " ".join(sentences).strip()
        lines = wrap_text(draw, candidate, font, max_width)
        if lines and len(lines) <= max_lines:
            return lines
        sentences.pop()
    return []


def blend_color(
    color: tuple[int, int, int],
    background: tuple[int, int, int] = (255, 255, 255),
    opacity: float = 0.16,
) -> tuple[int, int, int]:
    return tuple(int((channel * opacity) + (background[index] * (1 - opacity))) for index, channel in enumerate(color))


def draw_soft_shadow(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int = PDF_CARD_RADIUS,
) -> None:
    left, top, right, bottom = box
    draw.rounded_rectangle((left + 1, top + 7, right + 1, bottom + 7), radius=radius, fill=COLORS["shadow"])
    draw.rounded_rectangle((left, top + 3, right, bottom + 3), radius=radius, fill=(236, 241, 245))


def draw_pill(
    draw: ImageDraw.ImageDraw,
    right: int,
    top: int,
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    text_fill: tuple[int, int, int],
    horizontal_padding: int = 18,
    height_padding: int = 8,
) -> tuple[int, int, int, int]:
    label_width = text_width(draw, text, font)
    label_height = line_height(draw, font)
    box = (
        right - label_width - (horizontal_padding * 2),
        top,
        right,
        top + label_height + (height_padding * 2),
    )
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=fill)
    draw_text(
        draw,
        (right - horizontal_padding, top + height_padding - 1),
        text,
        fill=text_fill,
        font=font,
        anchor="ra",
    )
    return box


def draw_text_in_box(
    draw: ImageDraw.ImageDraw,
    left: int,
    right: int,
    y: int,
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
) -> None:
    if has_arabic(text):
        draw_text(draw, (right, y), text, fill=fill, font=font, anchor="ra")
    else:
        draw_text(draw, (left, y), text, fill=fill, font=font, anchor="la")


def group_articles(articles: list[Article]) -> dict[str, list[Article]]:
    grouped = {category: [] for category in CATEGORY_ORDER}
    for article in articles:
        bucket = grouped[article.category]
        if len(bucket) < MAX_HEADLINES_PER_SECTION:
            bucket.append(article)
    return grouped


def grouped_item_count(grouped: dict[str, list[Article]]) -> int:
    return sum(len(items) for items in grouped.values())


def arabic_datetime(value: datetime, include_weekday: bool = False) -> str:
    date_text = f"{value.day:02d} {ARABIC_MONTHS[value.month]} {value.year}"
    time_text = value.strftime("%H:%M")
    if include_weekday:
        return f"{ARABIC_DAYS[value.weekday()]}، {date_text} | {time_text} بتوقيت الإمارات"
    return f"{date_text}، {time_text} بتوقيت الإمارات"


def source_label(article: Article) -> str:
    bits = [article.source or article.feed_label]
    if article.published_at:
        bits.append(arabic_datetime(article.published_at))
    return " | ".join(bits)


def measure_grouped_height(
    draw: ImageDraw.ImageDraw,
    grouped: dict[str, list[Article]],
    section_font: ImageFont.ImageFont,
    headline_font: ImageFont.ImageFont,
    source_font: ImageFont.ImageFont,
    start_y: int,
) -> int:
    y = start_y
    headline_width = IMAGE_WIDTH - (MARGIN_X * 2) - 42
    headline_step = line_height(draw, headline_font) + 7
    source_step = line_height(draw, source_font) + 24

    for category in CATEGORY_ORDER:
        items = grouped[category]
        if not items:
            continue

        y += 46
        for article in items:
            lines = wrap_text(draw, article.title, headline_font, headline_width)
            y += max(1, len(lines)) * headline_step
            y += source_step
        y += 12

    return y


def trim_grouped_to_fit(
    draw: ImageDraw.ImageDraw,
    grouped: dict[str, list[Article]],
    section_font: ImageFont.ImageFont,
    headline_font: ImageFont.ImageFont,
    source_font: ImageFont.ImageFont,
    start_y: int,
) -> dict[str, list[Article]]:
    fitted = {category: list(items) for category, items in grouped.items()}
    while grouped_item_count(fitted) > 0:
        needed_height = measure_grouped_height(draw, fitted, section_font, headline_font, source_font, start_y)
        if needed_height <= FOOTER_TOP - 24:
            return fitted

        removed_extra_item = False
        for category in reversed(CATEGORY_ORDER):
            if len(fitted[category]) > 1:
                fitted[category].pop()
                removed_extra_item = True
                break
        if removed_extra_item:
            continue

        for category in reversed(CATEGORY_ORDER):
            if fitted[category]:
                fitted[category].pop()
                break
    return fitted


def draw_icon(draw: ImageDraw.ImageDraw, category: str, center_x: int, center_y: int, size: int, color: tuple[int, int, int]) -> None:
    radius = size // 2
    draw.ellipse(
        (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
        fill=color,
    )

    white = (255, 255, 255)
    s = size
    if category == "Leadership":
        crown = [
            (center_x - int(s * 0.30), center_y + int(s * 0.12)),
            (center_x - int(s * 0.24), center_y - int(s * 0.16)),
            (center_x - int(s * 0.08), center_y + int(s * 0.02)),
            (center_x, center_y - int(s * 0.20)),
            (center_x + int(s * 0.08), center_y + int(s * 0.02)),
            (center_x + int(s * 0.24), center_y - int(s * 0.16)),
            (center_x + int(s * 0.30), center_y + int(s * 0.12)),
        ]
        draw.polygon(crown, fill=white)
        draw.rectangle(
            (
                center_x - int(s * 0.28),
                center_y + int(s * 0.13),
                center_x + int(s * 0.28),
                center_y + int(s * 0.23),
            ),
            fill=white,
        )
    elif category == "Government":
        draw.polygon(
            [
                (center_x - int(s * 0.28), center_y - int(s * 0.12)),
                (center_x, center_y - int(s * 0.30)),
                (center_x + int(s * 0.28), center_y - int(s * 0.12)),
            ],
            fill=white,
        )
        for offset in [-16, 0, 16]:
            draw.rectangle(
                (
                    center_x + offset - 4,
                    center_y - int(s * 0.08),
                    center_x + offset + 4,
                    center_y + int(s * 0.20),
                ),
                fill=white,
            )
        draw.rectangle(
            (
                center_x - int(s * 0.30),
                center_y + int(s * 0.22),
                center_x + int(s * 0.30),
                center_y + int(s * 0.28),
            ),
            fill=white,
        )
    elif category == "Defense & Security":
        shield = [
            (center_x, center_y - int(s * 0.30)),
            (center_x + int(s * 0.25), center_y - int(s * 0.18)),
            (center_x + int(s * 0.20), center_y + int(s * 0.14)),
            (center_x, center_y + int(s * 0.30)),
            (center_x - int(s * 0.20), center_y + int(s * 0.14)),
            (center_x - int(s * 0.25), center_y - int(s * 0.18)),
        ]
        draw.polygon(shield, fill=white)
    elif category == "Economy":
        points = [
            (center_x - int(s * 0.28), center_y + int(s * 0.20)),
            (center_x - int(s * 0.10), center_y + int(s * 0.06)),
            (center_x + int(s * 0.04), center_y + int(s * 0.10)),
            (center_x + int(s * 0.26), center_y - int(s * 0.18)),
        ]
        draw.line(points, fill=white, width=5, joint="curve")
        draw.polygon(
            [
                (center_x + int(s * 0.26), center_y - int(s * 0.18)),
                (center_x + int(s * 0.10), center_y - int(s * 0.17)),
                (center_x + int(s * 0.24), center_y - int(s * 0.02)),
            ],
            fill=white,
        )
    elif category == "Foreign Relations":
        draw.ellipse(
            (
                center_x - int(s * 0.26),
                center_y - int(s * 0.26),
                center_x + int(s * 0.26),
                center_y + int(s * 0.26),
            ),
            outline=white,
            width=4,
        )
        draw.line((center_x - int(s * 0.26), center_y, center_x + int(s * 0.26), center_y), fill=white, width=3)
        draw.arc(
            (
                center_x - int(s * 0.14),
                center_y - int(s * 0.26),
                center_x + int(s * 0.14),
                center_y + int(s * 0.26),
            ),
            80,
            280,
            fill=white,
            width=3,
        )
        draw.arc(
            (
                center_x - int(s * 0.14),
                center_y - int(s * 0.26),
                center_x + int(s * 0.14),
                center_y + int(s * 0.26),
            ),
            -100,
            100,
            fill=white,
            width=3,
        )
    else:
        draw.rectangle(
            (
                center_x - int(s * 0.24),
                center_y - int(s * 0.24),
                center_x + int(s * 0.24),
                center_y + int(s * 0.24),
            ),
            outline=white,
            width=4,
        )
        for index in range(3):
            y = center_y - int(s * 0.10) + index * 10
            draw.line((center_x - int(s * 0.14), y, center_x + int(s * 0.15), y), fill=white, width=3)


def paste_cover_image(base: Image.Image, source: Image.Image, box: tuple[int, int, int, int], radius: int = 8) -> None:
    width = box[2] - box[0]
    height = box[3] - box[1]
    fitted = ImageOps.fit(source, (width, height), method=Image.Resampling.LANCZOS)
    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, width, height), radius=radius, fill=255)
    base.paste(fitted, (box[0], box[1]), mask)


def add_rounded_gradient_overlay(
    base: Image.Image,
    box: tuple[int, int, int, int],
    radius: int = PDF_CARD_RADIUS,
    top_alpha: int = 0,
    bottom_alpha: int = 185,
) -> None:
    width = box[2] - box[0]
    height = box[3] - box[1]
    region = base.crop(box).convert("RGBA")
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    for y in range(height):
        progress = y / max(1, height - 1)
        alpha = int(top_alpha + ((bottom_alpha - top_alpha) * progress))
        overlay_draw.line((0, y, width, y), fill=(0, 0, 0, alpha))

    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, width, height), radius=radius, fill=255)
    combined = Image.alpha_composite(region, overlay)
    base.paste(combined.convert("RGB"), (box[0], box[1]), mask)


def draw_hero(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    article: Article,
    photo: Image.Image,
    fonts: dict[str, ImageFont.ImageFont],
) -> int:
    box = (
        MARGIN_X,
        HERO_IMAGE_TOP,
        IMAGE_WIDTH - MARGIN_X,
        HERO_IMAGE_TOP + HERO_IMAGE_HEIGHT,
    )
    paste_cover_image(image, photo, box)

    y = box[3] + HERO_TEXT_GAP
    max_width = IMAGE_WIDTH - (MARGIN_X * 2)
    headline_step = line_height(draw, fonts["hero"]) + 7
    for line in wrap_text(draw, article.title, fonts["hero"], max_width):
        draw_text(
            draw,
            (IMAGE_WIDTH - MARGIN_X, y),
            line,
            fill=COLORS["ink"],
            font=fonts["hero"],
            anchor="ra",
        )
        y += headline_step

    draw_text(
        draw,
        (IMAGE_WIDTH - MARGIN_X, y + 2),
        source_label(article),
        fill=COLORS["muted"],
        font=fonts["source"],
        anchor="ra",
    )
    y += line_height(draw, fonts["source"]) + HERO_BOTTOM_GAP
    draw.line((MARGIN_X, y - 8, IMAGE_WIDTH - MARGIN_X, y - 8), fill=COLORS["light_line"], width=1)
    return y


def draw_header(draw: ImageDraw.ImageDraw, title_font: ImageFont.ImageFont, date_font: ImageFont.ImageFont) -> None:
    now = datetime.now(UAE_TIMEZONE)
    draw.rectangle((0, 0, IMAGE_WIDTH, 12), fill=COLORS["accent"])
    draw_text(
        draw,
        (IMAGE_WIDTH - MARGIN_X, 58),
        "موجز الإمارات اليومي",
        fill=COLORS["ink"],
        font=title_font,
        anchor="ra",
    )
    draw_text(
        draw,
        (IMAGE_WIDTH - MARGIN_X, 132),
        arabic_datetime(now, include_weekday=True),
        fill=COLORS["muted"],
        font=date_font,
        anchor="ra",
    )
    draw.line((MARGIN_X, 184, IMAGE_WIDTH - MARGIN_X, 184), fill=COLORS["line"], width=2)


def draw_pdf_header(
    draw: ImageDraw.ImageDraw,
    title_font: ImageFont.ImageFont,
    date_font: ImageFont.ImageFont,
    label_font: ImageFont.ImageFont,
    page_number: int,
) -> None:
    now = datetime.now(UAE_TIMEZONE)
    draw.rectangle((0, 0, IMAGE_WIDTH, 14), fill=COLORS["accent"])
    draw.rectangle((0, 14, IMAGE_WIDTH, 18), fill=COLORS["flag_red"])

    draw_text(
        draw,
        (IMAGE_WIDTH - MARGIN_X, 58),
        "موجز الإمارات اليومي",
        fill=COLORS["ink"],
        font=title_font,
        anchor="ra",
    )
    draw_text(
        draw,
        (IMAGE_WIDTH - MARGIN_X, 126),
        arabic_datetime(now, include_weekday=True),
        fill=COLORS["muted"],
        font=date_font,
        anchor="ra",
    )

    draw_pill(
        draw,
        MARGIN_X + 118,
        54,
        f"صفحة {page_number}",
        label_font,
        fill=COLORS["accent_soft"],
        text_fill=COLORS["accent"],
        horizontal_padding=18,
        height_padding=8,
    )
    draw.line((MARGIN_X, 176, IMAGE_WIDTH - MARGIN_X, 176), fill=COLORS["line"], width=1)


def group_pdf_items_by_category(items: list[PdfArticle]) -> dict[str, list[PdfArticle]]:
    grouped = {category: [] for category in CATEGORY_ORDER}
    for item in items:
        grouped[item.article.category].append(item)
    return grouped


def pdf_item_importance_key(item: PdfArticle) -> tuple[int, int, float, str]:
    source = (item.article.source or item.article.feed_label).lower()
    trusted_bonus = 1 if any(name in source for name in TRUSTED_SOURCE_NAMES) else 0
    published_ts = item.article.published_at.timestamp() if item.article.published_at else 0.0
    return (item.article.score, trusted_bonus, published_ts, item.article.title.lower())


def lead_pdf_item(items: list[PdfArticle]) -> PdfArticle:
    return max(items, key=pdf_item_importance_key)


def draw_summary_stat(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    value: str,
    label: str,
    color: tuple[int, int, int],
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    left, top, right, bottom = box
    draw.rounded_rectangle(box, radius=PDF_CARD_RADIUS, fill=COLORS["surface"], outline=(232, 238, 243), width=1)
    draw.rounded_rectangle((right - 8, top, right, bottom), radius=PDF_CARD_RADIUS, fill=color)
    draw_text(draw, (right - 24, top + 18), value, fill=COLORS["ink"], font=fonts["summary_value"], anchor="ra")
    draw_text(draw, (right - 24, bottom - 30), label, fill=COLORS["muted"], font=fonts["summary_label"], anchor="ra")


def draw_summary_category_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    category: str,
    items: list[PdfArticle],
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    left, top, right, bottom = box
    section_color = COLORS[category]

    draw_soft_shadow(draw, box)
    draw.rounded_rectangle(box, radius=PDF_CARD_RADIUS, fill=COLORS["surface"], outline=(232, 238, 243), width=1)
    draw.rounded_rectangle((right - 12, top + 18, right - 5, top + 55), radius=3, fill=section_color)
    draw_text(
        draw,
        (right - 26, top + 18),
        CATEGORY_LABELS[category],
        fill=COLORS["ink"],
        font=fonts["summary_section"],
        anchor="ra",
    )

    count_text = str(len(items))
    draw_pill(
        draw,
        left + 58,
        top + 18,
        count_text,
        fonts["summary_source"],
        fill=blend_color(section_color, opacity=0.13),
        text_fill=section_color,
        horizontal_padding=14,
        height_padding=5,
    )

    subtitle = CATEGORY_SUBTITLES[category]
    subtitle_lines = limited_text_lines(draw, subtitle, fonts["summary_source"], right - left - 56, 2)
    y = top + 74
    for line in subtitle_lines:
        draw_text(draw, (right - 24, y), line, fill=COLORS["muted"], font=fonts["summary_source"], anchor="ra")
        y += line_height(draw, fonts["summary_source"]) + 5

    page_label = "صفحة داخل الملف" if items else "لا توجد أخبار مصورة"
    draw_text(draw, (right - 24, bottom - 32), page_label, fill=section_color, font=fonts["summary_source"], anchor="ra")


def draw_pdf_summary_page(
    items: list[PdfArticle],
    total_article_count: int,
    fonts: dict[str, ImageFont.ImageFont],
    link_areas: list[PdfLinkArea],
) -> Image.Image:
    page, draw, y = new_pdf_page(fonts, 1)
    lead_item = lead_pdf_item(items)
    grouped = group_pdf_items_by_category(items)

    hero_box = (MARGIN_X, y, IMAGE_WIDTH - MARGIN_X, y + PDF_SUMMARY_HERO_HEIGHT)
    draw_soft_shadow(draw, hero_box)
    paste_cover_image(page, lead_item.image, hero_box, radius=PDF_CARD_RADIUS)
    add_rounded_gradient_overlay(page, hero_box, radius=PDF_CARD_RADIUS, top_alpha=24, bottom_alpha=215)

    hero_right = hero_box[2] - 28
    hero_left = hero_box[0] + 28

    title_lines = limited_text_lines(draw, lead_item.article.title, fonts["pdf_lead_title"], hero_right - hero_left, 3)
    source_lines = limited_text_lines(draw, source_label(lead_item.article), fonts["summary_source"], hero_right - hero_left, 1)
    text_y = hero_box[3] - 46
    text_y -= len(source_lines) * (line_height(draw, fonts["summary_source"]) + 5)
    text_y -= len(title_lines) * (line_height(draw, fonts["pdf_lead_title"]) + 7)

    for line in title_lines:
        draw_text_in_box(draw, hero_left, hero_right, text_y, line, fonts["pdf_lead_title"], fill=(255, 255, 255))
        text_y += line_height(draw, fonts["pdf_lead_title"]) + 7
    text_y += 6
    for line in source_lines:
        draw_text_in_box(draw, hero_left, hero_right, text_y, line, fonts["summary_source"], fill=(226, 236, 241))
        text_y += line_height(draw, fonts["summary_source"]) + 5

    link_text = "فتح الخبر الرئيسي"
    link_width = text_width(draw, link_text, fonts["pdf_link"])
    link_left = hero_left
    link_right = hero_left + link_width + 42
    link_top = hero_box[1] + 30
    link_bottom = link_top + 34
    draw.rounded_rectangle((link_left, link_top, link_right, link_bottom), radius=17, fill=(255, 255, 255))
    draw_text(draw, (link_right - 20, link_top + 6), link_text, fill=COLORS["accent"], font=fonts["pdf_link"], anchor="ra")
    if lead_item.publisher_url:
        link_areas.append(PdfLinkArea(page_index=0, rect=(link_left, link_top, link_right, link_bottom), url=lead_item.publisher_url))

    y = hero_box[3] + 20
    active_categories = sum(1 for category in CATEGORY_ORDER if grouped[category])
    stat_gap = 16
    stat_width = (IMAGE_WIDTH - (MARGIN_X * 2) - (stat_gap * 2)) // 3
    stat_top = y
    stats = [
        (IMAGE_WIDTH - MARGIN_X - stat_width, IMAGE_WIDTH - MARGIN_X, str(total_article_count), "عناصر مجمعة", COLORS["accent"]),
        (IMAGE_WIDTH - MARGIN_X - (stat_width * 2) - stat_gap, IMAGE_WIDTH - MARGIN_X - stat_width - stat_gap, str(len(items)), "أخبار مصورة", COLORS["flag_red"]),
        (MARGIN_X, MARGIN_X + stat_width, str(active_categories), "أقسام نشطة", COLORS["Economy"]),
    ]
    for left, right, value, label, color in stats:
        draw_summary_stat(draw, (left, stat_top, right, stat_top + PDF_SUMMARY_STAT_HEIGHT), value, label, color, fonts)

    y = stat_top + PDF_SUMMARY_STAT_HEIGHT + 28
    draw_text(draw, (IMAGE_WIDTH - MARGIN_X, y), "الأقسام داخل الملف", fill=COLORS["ink"], font=fonts["summary_title"], anchor="ra")
    y += line_height(draw, fonts["summary_title"]) + 18

    grid_gap = PDF_SUMMARY_CATEGORY_GAP
    card_width = (IMAGE_WIDTH - (MARGIN_X * 2) - grid_gap) // 2
    for index, category in enumerate(CATEGORY_ORDER):
        row = index // 2
        column = index % 2
        if column == 0:
            left = IMAGE_WIDTH - MARGIN_X - card_width
        else:
            left = MARGIN_X
        top = y + row * (PDF_SUMMARY_CATEGORY_HEIGHT + grid_gap)
        draw_summary_category_card(
            draw,
            (left, top, left + card_width, top + PDF_SUMMARY_CATEGORY_HEIGHT),
            category,
            grouped[category],
            fonts,
        )

    return page


def draw_pdf_section_header(
    draw: ImageDraw.ImageDraw,
    category: str,
    count: int,
    fonts: dict[str, ImageFont.ImageFont],
    y: int,
) -> int:
    section_color = COLORS[category]
    left = MARGIN_X
    right = IMAGE_WIDTH - MARGIN_X
    bottom = y + PDF_SECTION_HEADER_HEIGHT
    fill = blend_color(section_color, opacity=0.10)

    draw.rounded_rectangle((left, y, right, bottom), radius=PDF_CARD_RADIUS, fill=fill)
    draw.rounded_rectangle((right - 12, y + 16, right - 5, bottom - 16), radius=3, fill=section_color)
    draw_text(draw, (right - 32, y + 15), CATEGORY_LABELS[category], fill=COLORS["ink"], font=fonts["section_title"], anchor="ra")
    draw_text(draw, (right - 32, y + 52), CATEGORY_SUBTITLES[category], fill=COLORS["muted"], font=fonts["section_subtitle"], anchor="ra")

    count_label = f"{count} أخبار مختارة"
    draw_pill(
        draw,
        left + text_width(draw, count_label, fonts["summary_source"]) + 34,
        y + 24,
        count_label,
        fonts["summary_source"],
        fill=(255, 255, 255),
        text_fill=section_color,
        horizontal_padding=14,
        height_padding=6,
    )
    return bottom + PDF_SECTION_PAGE_GAP


def draw_pdf_link_button(
    draw: ImageDraw.ImageDraw,
    right: int,
    bottom: int,
    label: str,
    font: ImageFont.ImageFont,
    color: tuple[int, int, int],
    fill: tuple[int, int, int],
) -> tuple[int, int, int, int]:
    width = text_width(draw, label, font) + 34
    height = line_height(draw, font) + 16
    box = (right - width, bottom - height, right, bottom)
    draw.rounded_rectangle(box, radius=height // 2, fill=fill)
    draw_text(draw, (right - 17, box[1] + 7), label, fill=color, font=font, anchor="ra")
    return box


def draw_pdf_feature_story(
    page: Image.Image,
    draw: ImageDraw.ImageDraw,
    item: PdfArticle,
    fonts: dict[str, ImageFont.ImageFont],
    y: int,
    page_index: int,
    link_areas: list[PdfLinkArea],
) -> int:
    category = item.article.category
    section_color = COLORS[category]
    left = MARGIN_X
    right = IMAGE_WIDTH - MARGIN_X
    bottom = y + PDF_SECTION_FEATURE_HEIGHT
    box = (left, y, right, bottom)

    draw_soft_shadow(draw, box)
    draw.rounded_rectangle(box, radius=PDF_CARD_RADIUS, fill=COLORS["surface"], outline=(232, 238, 243), width=1)
    draw.rounded_rectangle((right - 9, y + 20, right - 4, bottom - 20), radius=3, fill=section_color)

    image_right = right - 24
    image_left = image_right - PDF_SECTION_IMAGE_WIDTH
    image_box = (image_left, y + 24, image_right, bottom - 24)
    if item.image:
        paste_cover_image(page, item.image, image_box, radius=PDF_CARD_RADIUS)
        add_rounded_gradient_overlay(page, image_box, radius=PDF_CARD_RADIUS, top_alpha=0, bottom_alpha=95)

    text_left = left + 28
    text_right = image_left - 28
    text_width_limit = text_right - text_left
    text_y = y + 26

    draw_pill(
        draw,
        text_right,
        text_y,
        "القصة الأبرز",
        fonts["pdf_category"],
        fill=blend_color(section_color, opacity=0.12),
        text_fill=section_color,
        horizontal_padding=15,
        height_padding=6,
    )
    text_y += line_height(draw, fonts["pdf_category"]) + 24

    title_lines = limited_text_lines(draw, item.article.title, fonts["pdf_feature_title"], text_width_limit, 4)
    for line in title_lines:
        draw_text_in_box(draw, text_left, text_right, text_y, line, fonts["pdf_feature_title"], fill=COLORS["ink"])
        text_y += line_height(draw, fonts["pdf_feature_title"]) + 7

    reserved_bottom = bottom - 112
    available_brief_lines = max(0, (reserved_bottom - text_y - 8) // (line_height(draw, fonts["pdf_brief"]) + 6))
    brief_lines = []
    if available_brief_lines:
        brief_lines = complete_sentence_lines(
            draw,
            item.brief or item.article.summary,
            fonts["pdf_brief"],
            text_width_limit,
            max_lines=min(3, available_brief_lines),
            max_chars=320,
            max_sentences=2,
        )
    if brief_lines:
        text_y += 8
        for line in brief_lines:
            draw_text_in_box(draw, text_left, text_right, text_y, line, fonts["pdf_brief"], fill=COLORS["muted"])
            text_y += line_height(draw, fonts["pdf_brief"]) + 6

    source_text = source_label(item.article)
    source_lines = limited_text_lines(draw, source_text, fonts["pdf_source"], text_width_limit, 1)
    source_y = bottom - 92
    for line in source_lines:
        draw_text_in_box(draw, text_left, text_right, source_y, line, fonts["pdf_source"], fill=COLORS["soft_muted"])

    link_box = draw_pdf_link_button(
        draw,
        text_right,
        bottom - 24,
        "فتح الخبر الأصلي",
        fonts["pdf_link"],
        color=(255, 255, 255),
        fill=section_color,
    )
    if item.publisher_url:
        link_areas.append(PdfLinkArea(page_index=page_index, rect=link_box, url=item.publisher_url))
    return bottom + PDF_SECTION_PAGE_GAP


def draw_pdf_compact_story(
    page: Image.Image,
    draw: ImageDraw.ImageDraw,
    item: PdfArticle,
    fonts: dict[str, ImageFont.ImageFont],
    box: tuple[int, int, int, int],
    page_index: int,
    link_areas: list[PdfLinkArea],
) -> None:
    left, top, right, bottom = box
    category = item.article.category
    section_color = COLORS[category]

    draw_soft_shadow(draw, box)
    draw.rounded_rectangle(box, radius=PDF_CARD_RADIUS, fill=COLORS["surface"], outline=(232, 238, 243), width=1)
    draw.rounded_rectangle((right - 9, top + 16, right - 4, bottom - 16), radius=3, fill=section_color)

    image_right = right - 22
    image_width = min(240, max(170, (right - left) // 4))
    image_left = image_right - image_width
    image_box = (image_left, top + 22, image_right, bottom - 22)
    if item.image:
        paste_cover_image(page, item.image, image_box, radius=PDF_CARD_RADIUS)

    text_left = left + 20
    text_right = image_left - 18
    text_width_limit = text_right - text_left
    text_y = top + 22

    title_lines = limited_text_lines(draw, item.article.title, fonts["pdf_compact_title"], text_width_limit, 3)
    for line in title_lines:
        draw_text_in_box(draw, text_left, text_right, text_y, line, fonts["pdf_compact_title"], fill=COLORS["ink"])
        text_y += line_height(draw, fonts["pdf_compact_title"]) + 6

    reserved_bottom = bottom - 94
    available_brief_lines = max(0, (reserved_bottom - text_y - 4) // (line_height(draw, fonts["pdf_compact_brief"]) + 5))
    brief_lines = []
    if available_brief_lines:
        brief_lines = complete_sentence_lines(
            draw,
            item.brief or item.article.summary,
            fonts["pdf_compact_brief"],
            text_width_limit,
            max_lines=min(2, available_brief_lines),
            max_chars=220,
            max_sentences=1,
        )
    if brief_lines:
        text_y += 4
        for line in brief_lines:
            draw_text_in_box(draw, text_left, text_right, text_y, line, fonts["pdf_compact_brief"], fill=COLORS["muted"])
            text_y += line_height(draw, fonts["pdf_compact_brief"]) + 5

    source_lines = limited_text_lines(draw, item.article.source or item.article.feed_label, fonts["summary_source"], text_width_limit, 1)
    for line in source_lines:
        draw_text_in_box(draw, text_left, text_right, bottom - 78, line, fonts["summary_source"], fill=COLORS["soft_muted"])

    link_box = draw_pdf_link_button(
        draw,
        text_right,
        bottom - 18,
        "فتح الخبر",
        fonts["summary_source"],
        color=section_color,
        fill=blend_color(section_color, opacity=0.12),
    )
    if item.publisher_url:
        link_areas.append(PdfLinkArea(page_index=page_index, rect=link_box, url=item.publisher_url))


def draw_pdf_category_page(
    category: str,
    items: list[PdfArticle],
    fonts: dict[str, ImageFont.ImageFont],
    page_number: int,
    page_index: int,
    link_areas: list[PdfLinkArea],
) -> Image.Image:
    page, draw, y = new_pdf_page(fonts, page_number)
    y = draw_pdf_section_header(draw, category, len(items), fonts, y)
    y = draw_pdf_feature_story(page, draw, items[0], fonts, y, page_index, link_areas)

    remaining = items[1:MAX_PDF_ARTICLES_PER_CATEGORY]
    if not remaining:
        return page

    card_gap = PDF_SECTION_PAGE_GAP
    card_width = IMAGE_WIDTH - (MARGIN_X * 2)
    for index, item in enumerate(remaining):
        left = MARGIN_X
        top = y + index * (PDF_SECTION_COMPACT_HEIGHT + card_gap)
        draw_pdf_compact_story(
            page,
            draw,
            item,
            fonts,
            (left, top, left + card_width, top + PDF_SECTION_COMPACT_HEIGHT),
            page_index,
            link_areas,
        )
    return page


def draw_footer(draw: ImageDraw.ImageDraw, footer_font: ImageFont.ImageFont, page_number: int | None = None) -> None:
    draw.line((MARGIN_X, FOOTER_TOP, IMAGE_WIDTH - MARGIN_X, FOOTER_TOP), fill=COLORS["line"], width=2)
    footer_text = "المصادر: أخبار Google RSS | الصور: صفحة الناشر عند توفرها | نسخة محلية تجريبية"
    if page_number is not None:
        footer_text = f"{footer_text} | صفحة {page_number}"
    draw_text(
        draw,
        (IMAGE_WIDTH - MARGIN_X, FOOTER_TOP + 28),
        footer_text,
        fill=COLORS["muted"],
        font=footer_font,
        anchor="ra",
    )


def draw_no_news_message(draw: ImageDraw.ImageDraw, message_font: ImageFont.ImageFont) -> None:
    message = "لم يتم العثور على أخبار إماراتية مطابقة اليوم."
    max_width = IMAGE_WIDTH - (MARGIN_X * 2)
    lines = wrap_text(draw, message, message_font, max_width)
    total_height = len(lines) * (line_height(draw, message_font) + 8)
    y = (IMAGE_HEIGHT - total_height) // 2
    for line in lines:
        draw_text(draw, (IMAGE_WIDTH // 2, y), line, fill=COLORS["muted"], font=message_font, anchor="ma")
        y += line_height(draw, message_font) + 8


def render_articles(
    draw: ImageDraw.ImageDraw,
    grouped: dict[str, list[Article]],
    fonts: dict[str, ImageFont.ImageFont],
    start_y: int,
) -> None:
    y = start_y
    headline_width = IMAGE_WIDTH - (MARGIN_X * 2) - 42
    headline_step = line_height(draw, fonts["headline"]) + 7
    source_step = line_height(draw, fonts["source"]) + 24

    for category in CATEGORY_ORDER:
        articles = grouped[category]
        if not articles:
            continue

        section_color = COLORS[category]
        icon_center_y = y + 22
        draw_icon(draw, category, IMAGE_WIDTH - MARGIN_X - 22, icon_center_y, 40, section_color)
        draw_text(
            draw,
            (IMAGE_WIDTH - MARGIN_X - 58, y + 3),
            CATEGORY_LABELS[category],
            fill=COLORS["ink"],
            font=fonts["section"],
            anchor="ra",
        )

        label = f"{len(articles)}"
        label_w = text_width(draw, label, fonts["source"])
        draw.rounded_rectangle(
            (
                MARGIN_X,
                y + 9,
                MARGIN_X + label_w + 26,
                y + 36,
            ),
            radius=13,
            fill=(245, 248, 250),
            outline=COLORS["light_line"],
        )
        draw_text(
            draw,
            (MARGIN_X + 13, y + 10),
            label,
            fill=COLORS["muted"],
            font=fonts["source"],
        )

        y += 54

        for article in articles:
            bullet_x = IMAGE_WIDTH - MARGIN_X - 14
            text_right = IMAGE_WIDTH - MARGIN_X - 42
            draw.ellipse((bullet_x - 6, y + 9, bullet_x + 5, y + 20), fill=section_color)
            for line in wrap_text(draw, article.title, fonts["headline"], headline_width):
                draw_text(
                    draw,
                    (text_right, y),
                    line,
                    fill=COLORS["ink"],
                    font=fonts["headline"],
                    anchor="ra",
                )
                y += headline_step
            draw_text(
                draw,
                (text_right, y + 1),
                source_label(article),
                fill=COLORS["muted"],
                font=fonts["source"],
                anchor="ra",
            )
            y += source_step

        y += 12
        draw.line((MARGIN_X, y - 4, IMAGE_WIDTH - MARGIN_X, y - 4), fill=COLORS["light_line"], width=1)


def balanced_pdf_article_candidates(articles: list[Article]) -> list[Article]:
    grouped = {category: [] for category in CATEGORY_ORDER}
    for article in articles:
        grouped[article.category].append(article)

    candidates: list[Article] = []
    max_depth = max((len(grouped[category]) for category in CATEGORY_ORDER), default=0)
    for slot in range(max_depth):
        for category in CATEGORY_ORDER:
            if slot < len(grouped[category]):
                candidates.append(grouped[category][slot])
    return candidates


def select_pdf_articles_with_images(articles: list[Article]) -> list[PdfArticle]:
    selected: list[PdfArticle] = []
    category_counts = {category: 0 for category in CATEGORY_ORDER}

    with requests.Session() as session:
        for article in balanced_pdf_article_candidates(articles):
            if len(selected) >= MAX_PDF_ARTICLES:
                break
            if category_counts[article.category] >= MAX_PDF_ARTICLES_PER_CATEGORY:
                continue

            publisher_url, image_url, brief = publisher_article_details(session, article)
            image = download_image(session, image_url)
            if not image:
                continue

            selected.append(PdfArticle(article=article, image=image, publisher_url=publisher_url, brief=brief))
            category_counts[article.category] += 1
            print(f"صورة خبر حقيقية: {len(selected)} / {MAX_PDF_ARTICLES}")

    return selected


def pdf_card_text_lines(
    draw: ImageDraw.ImageDraw,
    item: PdfArticle,
    fonts: dict[str, ImageFont.ImageFont],
    text_width_limit: int,
) -> tuple[list[str], list[str], list[str]]:
    title_lines = limited_text_lines(
        draw,
        item.article.title,
        fonts["pdf_headline"],
        text_width_limit,
        PDF_TITLE_MAX_LINES,
    )
    brief_lines = complete_sentence_lines(
        draw,
        item.brief,
        fonts["pdf_brief"],
        text_width_limit,
        PDF_BRIEF_MAX_LINES,
        max_chars=360,
        max_sentences=2,
    )
    source_lines = limited_text_lines(draw, source_label(item.article), fonts["pdf_source"], text_width_limit, 1)
    return title_lines, brief_lines, source_lines


def measure_pdf_article_card(
    draw: ImageDraw.ImageDraw,
    item: PdfArticle,
    fonts: dict[str, ImageFont.ImageFont],
) -> int:
    card_width = IMAGE_WIDTH - (MARGIN_X * 2)
    text_width_limit = card_width - (PDF_CARD_PADDING * 3) - PDF_THUMBNAIL_WIDTH
    title_lines, brief_lines, source_lines = pdf_card_text_lines(draw, item, fonts, text_width_limit)

    text_height = line_height(draw, fonts["pdf_category"]) + 24
    text_height += len(title_lines) * (line_height(draw, fonts["pdf_headline"]) + 6)
    if brief_lines:
        text_height += 8 + len(brief_lines) * (line_height(draw, fonts["pdf_brief"]) + 5)
    text_height += max(1, len(source_lines)) * (line_height(draw, fonts["pdf_source"]) + 5) + 8
    text_height += line_height(draw, fonts["pdf_link"]) + 16
    inner_height = max(PDF_THUMBNAIL_HEIGHT, text_height)
    return inner_height + (PDF_CARD_PADDING * 2)


def pdf_lead_text_lines(
    draw: ImageDraw.ImageDraw,
    item: PdfArticle,
    fonts: dict[str, ImageFont.ImageFont],
    text_width_limit: int,
) -> tuple[list[str], list[str], list[str]]:
    title_lines = limited_text_lines(
        draw,
        item.article.title,
        fonts["pdf_lead_title"],
        text_width_limit,
        PDF_LEAD_TITLE_MAX_LINES,
    )
    brief_lines = complete_sentence_lines(
        draw,
        item.brief,
        fonts["pdf_brief"],
        text_width_limit,
        PDF_LEAD_BRIEF_MAX_LINES,
        max_chars=300,
        max_sentences=2,
    )
    source_lines = limited_text_lines(draw, source_label(item.article), fonts["pdf_source"], text_width_limit, 1)
    return title_lines, brief_lines, source_lines


def measure_pdf_lead_card(
    draw: ImageDraw.ImageDraw,
    item: PdfArticle,
    fonts: dict[str, ImageFont.ImageFont],
) -> int:
    card_width = IMAGE_WIDTH - (MARGIN_X * 2)
    text_width_limit = card_width - (PDF_LEAD_PADDING * 2)
    _title_lines, brief_lines, _source_lines = pdf_lead_text_lines(draw, item, fonts, text_width_limit)
    text_height = PDF_LEAD_PADDING
    if brief_lines:
        text_height += len(brief_lines) * (line_height(draw, fonts["pdf_brief"]) + 6) + 12
    text_height += line_height(draw, fonts["pdf_link"]) + 18
    text_height += PDF_LEAD_PADDING
    return PDF_LEAD_IMAGE_HEIGHT + text_height


def draw_pdf_lead_card(
    page: Image.Image,
    draw: ImageDraw.ImageDraw,
    item: PdfArticle,
    fonts: dict[str, ImageFont.ImageFont],
    y: int,
    page_index: int,
    link_areas: list[PdfLinkArea],
) -> int:
    card_left = MARGIN_X
    card_right = IMAGE_WIDTH - MARGIN_X
    card_height = measure_pdf_lead_card(draw, item, fonts)
    card_box = (card_left, y, card_right, y + card_height)
    category = item.article.category
    section_color = COLORS[category]

    draw_soft_shadow(draw, card_box)
    draw.rounded_rectangle(
        card_box,
        radius=PDF_CARD_RADIUS,
        fill=COLORS["surface"],
        outline=(232, 238, 243),
        width=1,
    )

    image_box = (card_left, y, card_right, y + PDF_LEAD_IMAGE_HEIGHT)
    if item.image:
        paste_cover_image(page, item.image, image_box, radius=PDF_CARD_RADIUS)
        add_rounded_gradient_overlay(page, image_box, radius=PDF_CARD_RADIUS, top_alpha=12, bottom_alpha=205)

    text_right = card_right - PDF_LEAD_PADDING
    text_left = card_left + PDF_LEAD_PADDING
    text_width_limit = text_right - text_left
    title_lines, brief_lines, source_lines = pdf_lead_text_lines(draw, item, fonts, text_width_limit)

    pill_top = y + PDF_LEAD_PADDING
    draw_pill(
        draw,
        text_right,
        pill_top,
        CATEGORY_LABELS[category],
        fonts["pdf_category"],
        fill=(255, 255, 255),
        text_fill=section_color,
        horizontal_padding=16,
        height_padding=7,
    )

    title_step = line_height(draw, fonts["pdf_lead_title"]) + 7
    source_step = line_height(draw, fonts["pdf_source"]) + 5
    overlay_y = y + PDF_LEAD_IMAGE_HEIGHT - PDF_LEAD_PADDING
    overlay_y -= len(source_lines) * source_step
    overlay_y -= len(title_lines) * title_step
    overlay_y -= 12

    for line in title_lines:
        draw_text_in_box(
            draw,
            text_left,
            text_right,
            overlay_y,
            line,
            fonts["pdf_lead_title"],
            fill=(255, 255, 255),
        )
        overlay_y += title_step

    overlay_y += 6
    for line in source_lines:
        draw_text_in_box(
            draw,
            text_left,
            text_right,
            overlay_y,
            line,
            fonts["pdf_source"],
            fill=(226, 236, 241),
        )
        overlay_y += source_step

    text_y = y + PDF_LEAD_IMAGE_HEIGHT + PDF_LEAD_PADDING
    for line in brief_lines:
        draw_text_in_box(
            draw,
            text_left,
            text_right,
            text_y,
            line,
            fonts["pdf_brief"],
            fill=COLORS["muted"],
        )
        text_y += line_height(draw, fonts["pdf_brief"]) + 6
    text_y += 12

    link_text = "فتح الخبر الأصلي"
    link_width = text_width(draw, link_text, fonts["pdf_link"])
    link_padding_x = 20
    link_padding_y = 8
    link_left = text_right - link_width - (link_padding_x * 2)
    link_top = text_y
    link_bottom = text_y + line_height(draw, fonts["pdf_link"]) + (link_padding_y * 2)
    draw.rounded_rectangle(
        (link_left, link_top, text_right, link_bottom),
        radius=(link_bottom - link_top) // 2,
        fill=COLORS["accent"],
    )
    draw_text(
        draw,
        (text_right - link_padding_x, text_y + link_padding_y - 1),
        link_text,
        fill=(255, 255, 255),
        font=fonts["pdf_link"],
        anchor="ra",
    )
    if item.publisher_url:
        link_areas.append(PdfLinkArea(page_index=page_index, rect=(link_left, link_top, text_right, link_bottom), url=item.publisher_url))

    return y + card_height + PDF_CARD_GAP


def draw_pdf_article_card(
    page: Image.Image,
    draw: ImageDraw.ImageDraw,
    item: PdfArticle,
    fonts: dict[str, ImageFont.ImageFont],
    y: int,
    page_index: int,
    link_areas: list[PdfLinkArea],
) -> int:
    card_left = MARGIN_X
    card_right = IMAGE_WIDTH - MARGIN_X
    card_width = card_right - card_left
    card_height = measure_pdf_article_card(draw, item, fonts)
    category = item.article.category
    section_color = COLORS[category]
    card_box = (card_left, y, card_right, y + card_height)

    draw_soft_shadow(draw, card_box)
    draw.rounded_rectangle(
        card_box,
        radius=PDF_CARD_RADIUS,
        fill=COLORS["surface"],
        outline=(232, 238, 243),
        width=1,
    )

    image_right = card_right - PDF_CARD_PADDING
    image_left = image_right - PDF_THUMBNAIL_WIDTH
    image_top = y + PDF_CARD_PADDING
    image_bottom = image_top + PDF_THUMBNAIL_HEIGHT
    if item.image:
        paste_cover_image(page, item.image, (image_left, image_top, image_right, image_bottom), radius=PDF_CARD_RADIUS)

    text_right = image_left - PDF_CARD_PADDING
    text_left = card_left + PDF_CARD_PADDING
    text_width_limit = text_right - text_left
    text_y = y + PDF_CARD_PADDING

    draw_pill(
        draw,
        text_right,
        text_y,
        CATEGORY_LABELS[category],
        fonts["pdf_category"],
        fill=blend_color(section_color, opacity=0.13),
        text_fill=section_color,
        horizontal_padding=15,
        height_padding=6,
    )
    text_y += line_height(draw, fonts["pdf_category"]) + 24

    title_lines, brief_lines, source_lines = pdf_card_text_lines(draw, item, fonts, text_width_limit)
    for line in title_lines:
        draw_text_in_box(
            draw,
            text_left,
            text_right,
            text_y,
            line,
            fonts["pdf_headline"],
            fill=COLORS["ink"],
        )
        text_y += line_height(draw, fonts["pdf_headline"]) + 6

    if brief_lines:
        text_y += 8
        for line in brief_lines:
            draw_text_in_box(
                draw,
                text_left,
                text_right,
                text_y,
                line,
                fonts["pdf_brief"],
                fill=COLORS["muted"],
            )
            text_y += line_height(draw, fonts["pdf_brief"]) + 5

    text_y += 6
    for line in source_lines:
        draw_text_in_box(
            draw,
            text_left,
            text_right,
            text_y,
            line,
            fonts["pdf_source"],
            fill=COLORS["soft_muted"],
        )
        text_y += line_height(draw, fonts["pdf_source"]) + 5
    text_y += 8

    link_text = "فتح الخبر الأصلي"
    link_width = text_width(draw, link_text, fonts["pdf_link"])
    link_padding_x = 18
    link_padding_y = 7
    link_left = text_right - link_width - (link_padding_x * 2)
    link_top = text_y
    link_bottom = text_y + line_height(draw, fonts["pdf_link"]) + (link_padding_y * 2)
    draw.rounded_rectangle(
        (link_left, link_top, text_right, link_bottom),
        radius=(link_bottom - link_top) // 2,
        fill=COLORS["accent_soft"],
    )
    draw_text(
        draw,
        (text_right - link_padding_x, text_y + link_padding_y - 1),
        link_text,
        fill=COLORS["accent"],
        font=fonts["pdf_link"],
        anchor="ra",
    )
    if item.publisher_url:
        link_areas.append(
            PdfLinkArea(
                page_index=page_index,
                rect=(link_left, link_top, text_right, link_bottom),
                url=item.publisher_url,
            )
        )

    return y + card_height + PDF_CARD_GAP


def new_pdf_page(fonts: dict[str, ImageFont.ImageFont], page_number: int) -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
    page = Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT), COLORS["paper"])
    draw = ImageDraw.Draw(page)
    draw_pdf_header(draw, fonts["title"], fonts["date"], fonts["pdf_source"], page_number)
    draw_footer(draw, fonts["footer"], page_number)
    return page, draw, PDF_CONTENT_TOP


def draw_no_real_images_message(draw: ImageDraw.ImageDraw, message_font: ImageFont.ImageFont) -> None:
    message = "لم يتم العثور على أخبار تحتوي على صور حقيقية من صفحات الناشرين."
    max_width = IMAGE_WIDTH - (MARGIN_X * 2)
    lines = wrap_text(draw, message, message_font, max_width)
    total_height = len(lines) * (line_height(draw, message_font) + 8)
    y = (IMAGE_HEIGHT - total_height) // 2
    for line in lines:
        draw_text(draw, (IMAGE_WIDTH // 2, y), line, fill=COLORS["muted"], font=message_font, anchor="ma")
        y += line_height(draw, message_font) + 8


def pdf_rect_from_pixels(rect: tuple[int, int, int, int]) -> tuple[float, float, float, float]:
    left, top, right, bottom = rect
    return (
        left * PDF_LINK_SCALE,
        (IMAGE_HEIGHT - bottom) * PDF_LINK_SCALE,
        right * PDF_LINK_SCALE,
        (IMAGE_HEIGHT - top) * PDF_LINK_SCALE,
    )


def add_clickable_links_to_pdf(raw_pdf_path: Path, final_pdf_path: Path, link_areas: list[PdfLinkArea]) -> None:
    reader = PdfReader(str(raw_pdf_path))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    for link_area in link_areas:
        if 0 <= link_area.page_index < len(writer.pages) and link_area.url:
            writer.add_annotation(
                link_area.page_index,
                Link(rect=pdf_rect_from_pixels(link_area.rect), url=link_area.url, border=[0, 0, 0]),
            )

    with final_pdf_path.open("wb") as output_file:
        writer.write(output_file)


def create_briefing_pdf(articles: list[Article]) -> int:
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    dated_path = dated_output_path()
    raw_pdf_path = dated_path.with_name(f"{dated_path.stem}_raw.pdf")

    fonts = {
        "title": load_font(58, bold=True),
        "date": load_font(24),
        "message": load_font(33, bold=True),
        "footer": load_font(20),
        "pdf_category": load_font(23, bold=True),
        "pdf_lead_title": load_font(36, bold=True),
        "pdf_feature_title": load_font(32, bold=True),
        "pdf_headline": load_font(28, bold=True),
        "pdf_brief": load_font(21),
        "pdf_compact_title": load_font(23, bold=True),
        "pdf_compact_brief": load_font(17),
        "pdf_source": load_font(18),
        "pdf_link": load_font(20, bold=True),
        "section_title": load_font(34, bold=True),
        "section_subtitle": load_font(19),
        "summary_title": load_font(30, bold=True),
        "summary_section": load_font(22, bold=True),
        "summary_headline": load_font(19, bold=True),
        "summary_source": load_font(16),
        "summary_label": load_font(18),
        "summary_value": load_font(34, bold=True),
    }

    pdf_items = select_pdf_articles_with_images(articles) if articles else []

    pages: list[Image.Image] = []
    link_areas: list[PdfLinkArea] = []
    page_number = 1
    page, draw, _y = new_pdf_page(fonts, page_number)

    if not pdf_items:
        if articles:
            draw_no_real_images_message(draw, fonts["message"])
        else:
            draw_no_news_message(draw, fonts["message"])
        pages.append(page)
    else:
        pages.append(draw_pdf_summary_page(pdf_items, len(articles), fonts, link_areas))
        grouped_pdf_items = group_pdf_items_by_category(pdf_items)
        for category in CATEGORY_ORDER:
            category_items = grouped_pdf_items[category]
            if not category_items:
                continue
            page_number += 1
            page_index = len(pages)
            pages.append(draw_pdf_category_page(category, category_items, fonts, page_number, page_index, link_areas))

    first_page, *other_pages = pages
    first_page.save(
        raw_pdf_path,
        "PDF",
        save_all=True,
        append_images=other_pages,
        resolution=PDF_RESOLUTION,
    )
    add_clickable_links_to_pdf(raw_pdf_path, dated_path, link_areas)
    shutil.copyfile(dated_path, LATEST_OUTPUT_PATH)
    try:
        raw_pdf_path.unlink()
    except OSError:
        pass
    return len(pdf_items)


def create_briefing_image(articles: list[Article]) -> int:
    image = Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    fonts = {
        "title": load_font(58, bold=True),
        "date": load_font(24),
        "section": load_font(29, bold=True),
        "hero": load_font(31, bold=True),
        "headline": load_font(27, bold=True),
        "source": load_font(18),
        "message": load_font(33, bold=True),
        "footer": load_font(20),
    }

    draw_header(draw, fonts["title"], fonts["date"])

    content_start_y = HEADER_BOTTOM
    articles_for_sections = articles
    lead_image = find_lead_image(articles) if articles else None
    if lead_image:
        lead_article, photo = lead_image
        content_start_y = draw_hero(image, draw, lead_article, photo, fonts)
        articles_for_sections = [article for article in articles if article is not lead_article]

    rendered_count = 1 if lead_image else 0
    if articles_for_sections:
        grouped = group_articles(articles_for_sections)
        grouped = trim_grouped_to_fit(
            draw,
            grouped,
            fonts["section"],
            fonts["headline"],
            fonts["source"],
            content_start_y,
        )
        section_count = grouped_item_count(grouped)
        rendered_count += section_count
        if section_count:
            render_articles(draw, grouped, fonts, content_start_y)
        elif not lead_image:
            draw_no_news_message(draw, fonts["message"])
    else:
        if not lead_image:
            draw_no_news_message(draw, fonts["message"])

    draw_footer(draw, fonts["footer"])
    image.save(OUTPUT_PATH)
    return rendered_count


def main() -> None:
    articles = collect_articles()
    rendered_count = create_briefing_pdf(articles)
    print(f"العناصر المجمعة: {len(articles)}")
    print(f"العناصر المعروضة: {rendered_count}")
    print(f"مسار ملف PDF المؤرخ: {dated_output_path()}")
    print(f"آخر نسخة: {LATEST_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
