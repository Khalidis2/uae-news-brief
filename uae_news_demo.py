from __future__ import annotations

import io
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image

from brief_pdf import BriefItem, build_pdf
from news_core import (
    CATEGORY_ORDER,
    REQUEST_HEADERS,
    REQUEST_TIMEOUT_SECONDS,
    UAE_TIMEZONE,
    WORLD_NEWS_ENABLED,
    Article,
    collect_articles,
    publisher_article_details,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_DIR = Path(__file__).resolve().parent
BRIEFS_DIR = PROJECT_DIR / "briefs"
LATEST_OUTPUT_PATH = PROJECT_DIR / "uae_daily_brief.pdf"
MAX_PDF_ARTICLES = 36
MAX_PDF_ARTICLES_PER_CATEGORY = 3
DETAIL_WORKERS = 8
DETAIL_CANDIDATE_LIMIT = 100


@dataclass(frozen=True)
class PdfArticle:
    article: Article
    image: Image.Image | None
    publisher_url: str
    brief: str


def brief_title() -> str:
    return "موجز الإمارات والعالم اليومي" if WORLD_NEWS_ENABLED else "موجز الإمارات اليومي"


def dated_output_path(value: datetime | None = None) -> Path:
    value = value or datetime.now(UAE_TIMEZONE)
    day_name = value.strftime("%A").lower()
    return BRIEFS_DIR / f"uae_daily_brief_{value:%Y-%m-%d}_{day_name}.pdf"


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
    candidates = balanced_pdf_article_candidates(articles)[:DETAIL_CANDIDATE_LIMIT]

    def load_candidate(article: Article) -> tuple[Article, str, str, Image.Image | None]:
        with requests.Session() as session:
            publisher_url, image_url, brief = publisher_article_details(session, article)
            return article, publisher_url, brief, download_image(session, image_url)

    # Publisher pages are slow, so fetch them concurrently; selection below still follows the balanced order.
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
        futures = [pool.submit(load_candidate, article) for article in candidates]
        for future in futures:
            if len(selected) >= MAX_PDF_ARTICLES:
                break
            article, publisher_url, brief, image = future.result()
            if category_counts[article.category] >= MAX_PDF_ARTICLES_PER_CATEGORY:
                continue
            if not image:
                continue

            selected.append(PdfArticle(article=article, image=image, publisher_url=publisher_url, brief=brief))
            category_counts[article.category] += 1
            print(f"صورة خبر حقيقية: {len(selected)} / {MAX_PDF_ARTICLES}")
        for future in futures:
            future.cancel()

    return selected


def create_briefing_pdf(articles: list[Article]) -> int:
    pdf_items = select_pdf_articles_with_images(articles) if articles else []
    now = datetime.now(UAE_TIMEZONE)
    build_pdf(
        items=[
            BriefItem(
                title=item.article.title,
                source=item.article.source or item.article.feed_label,
                category=item.article.category,
                published_at=item.article.published_at,
                brief=item.brief,
                image=item.image,
                url=item.publisher_url,
                score=item.article.score,
            )
            for item in pdf_items
            if item.image is not None
        ],
        total_collected=len(articles),
        category_order=CATEGORY_ORDER,
        title=brief_title(),
        now=now,
        dated_path=dated_output_path(now),
        latest_path=LATEST_OUTPUT_PATH,
        empty_message=(
            "لم يتم العثور على أخبار مصورة مطابقة اليوم."
            if articles
            else "لم يتم العثور على أخبار مطابقة اليوم."
        ),
    )
    return len(pdf_items)


def main() -> None:
    try:
        articles = collect_articles()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    rendered_count = create_briefing_pdf(articles)
    print(f"العناصر المجمعة: {len(articles)}")
    print(f"العناصر المعروضة: {rendered_count}")
    print(f"مسار ملف PDF المؤرخ: {dated_output_path()}")
    print(f"آخر نسخة: {LATEST_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
