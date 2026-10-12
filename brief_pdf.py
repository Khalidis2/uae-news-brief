"""Dark editorial PDF layout for the daily brief.

Pages are drawn as 1080x1600 images (Pillow), saved as a PDF, then given clickable link annotations.
The module is deliberately independent of the news collector: it only needs `BriefItem` objects.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont, ImageOps, features
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link

from text_utils import clean_text, complete_sentence_chunks, has_arabic, sentence_safe_excerpt

FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
RAQM = features.check("raqm")
LAYOUT_ENGINE = getattr(getattr(ImageFont, "Layout", object), "RAQM", None) if RAQM else None

PAGE_W, PAGE_H = 1080, 1600
MARGIN = 64
CONTENT_W = PAGE_W - 2 * MARGIN
PAGE_TOP = 128
PAGE_BOTTOM = PAGE_H - 56
GAP = 24
RESOLUTION = 144.0
LINK_SCALE = 72.0 / RESOLUTION

COVER_HERO_H = 860
COVER_ROWS_MAX = 6
HERO_IMAGE_H = 400
GRID_IMAGE_H = 240
IMAGE_SCALES = (1.0, 0.88, 0.76, 0.64)  # tried in order until a section fits on one page
WIDE_H = 214

BG = (10, 14, 24)
CARD = (20, 27, 44)
INK = (243, 245, 249)
MUTED = (160, 170, 190)
FAINT = (104, 115, 138)
LINE = (38, 47, 70)
GOLD = (224, 186, 100)

ARABIC_DAYS = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
ARABIC_MONTHS = [
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
]

CATEGORY_STYLE = {
    "Leadership": ("القيادة", "تحركات القيادة والرسائل الرسمية الأبرز", (236, 184, 96)),
    "Government": ("الحكومة", "قرارات وسياسات وخدمات تؤثر على الدولة", (92, 176, 236)),
    "Defense & Security": ("الدفاع والأمن", "ملفات الأمن والدفاع والتعاون الشرطي", (126, 196, 156)),
    "Economy": ("الاقتصاد", "الأعمال والاستثمار والطاقة والتقنية", (88, 212, 146)),
    "Foreign Relations": ("العلاقات الخارجية", "الدبلوماسية والشراكات والتحركات الخارجية", (146, 156, 244)),
    "Other Important UAE News": ("أخبار إماراتية", "قصص إماراتية مهمة خارج الأقسام الرئيسية", (170, 180, 200)),
    "World Affairs": ("أخبار العالم", "أبرز الأحداث السياسية والإنسانية حول العالم", (244, 116, 116)),
    "Middle East": ("الشرق الأوسط", "تطورات المنطقة والملفات الإقليمية", (244, 166, 76)),
    "Global Business": ("الاقتصاد العالمي", "الأسواق والطاقة والتجارة العالمية", (76, 194, 226)),
    "Tech & Science": ("التقنية والعلوم", "الذكاء الاصطناعي والتقنية والعلوم والصحة", (196, 136, 246)),
}
DEFAULT_STYLE = ("أخبار", "", (170, 180, 200))


@dataclass(frozen=True)
class BriefItem:
    title: str
    source: str
    category: str
    published_at: datetime | None
    brief: str
    image: Image.Image
    url: str
    score: int


@dataclass(frozen=True)
class LinkArea:
    page_index: int
    rect: tuple[int, int, int, int]
    url: str


Color = tuple[int, int, int]
Box = tuple[int, int, int, int]


def style_of(category: str) -> tuple[str, str, Color]:
    return CATEGORY_STYLE.get(category, DEFAULT_STYLE)


# --------------------------------------------------------------------------- text


@lru_cache(maxsize=None)
def font(size: int, weight: int = 400) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("Cairo-Variable.ttf", "NotoNaskhArabic-Variable.ttf"):
        path = FONT_DIR / name
        if not path.exists():
            continue
        try:
            loaded = (
                ImageFont.truetype(str(path), size, layout_engine=LAYOUT_ENGINE)
                if LAYOUT_ENGINE is not None
                else ImageFont.truetype(str(path), size)
            )
        except OSError:
            continue
        try:
            values = [
                min(max(weight, axis["minimum"]), axis["maximum"]) if axis["name"] == b"Weight" else axis["default"]
                for axis in loaded.get_variation_axes()
            ]
            loaded.set_variation_by_axes(values)
        except (OSError, AttributeError):
            pass
        return loaded
    return ImageFont.load_default()


def shaped(text: str) -> str:
    text = clean_text(text)
    if has_arabic(text) and not RAQM:
        return get_display(arabic_reshaper.reshape(text))
    return text


def render_options(text: str) -> dict[str, str]:
    return {"direction": "rtl", "language": "ar"} if has_arabic(text) and RAQM else {}


def text_w(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont) -> int:
    prepared = shaped(text)
    left, _top, right, _bottom = draw.textbbox((0, 0), prepared, font=fnt, **render_options(prepared))
    return right - left


def put(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, fnt: ImageFont.ImageFont, fill: Color, rtl: bool) -> None:
    """Draw text whose right edge (rtl) or left edge (ltr) sits at x."""
    prepared = shaped(text)
    draw.text((x, y), prepared, font=fnt, fill=fill, anchor="ra" if rtl else "la", **render_options(prepared))


def split_word(draw: ImageDraw.ImageDraw, word: str, fnt: ImageFont.ImageFont, width: int) -> list[str]:
    chunks, current = [], ""
    for character in word:
        if current and text_w(draw, current + character, fnt) > width:
            chunks.append(current)
            current = character
        else:
            current += character
    if current:
        chunks.append(current)
    return chunks


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in clean_text(text).split():
        candidate = f"{current} {word}".strip()
        if text_w(draw, candidate, fnt) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if text_w(draw, word, fnt) > width:
            chunks = split_word(draw, word, fnt, width)
            lines.extend(chunks[:-1])
            current = chunks[-1]
        else:
            current = word
    if current:
        lines.append(current)
    return lines


def clamp_lines(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont, width: int, max_lines: int) -> list[str]:
    lines = wrap(draw, text, fnt, width)
    if len(lines) <= max_lines:
        return lines
    lines = lines[:max_lines]
    last = lines[-1].rstrip()
    while last and text_w(draw, f"{last}...", fnt) > width:
        last = last[:-1].rstrip()
    lines[-1] = f"{last}..."
    return lines


def summary_lines(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont, width: int, max_lines: int) -> list[str]:
    """Wrap a summary using whole sentences only; fall back to a clipped excerpt for sentence-less text."""
    excerpt = sentence_safe_excerpt(text, max_chars=max_lines * 90, max_sentences=3)
    sentences = complete_sentence_chunks(excerpt)
    while sentences:
        lines = wrap(draw, " ".join(sentences), fnt, width)
        if lines and len(lines) <= max_lines:
            return lines
        sentences.pop()
    return clamp_lines(draw, text, fnt, width, max_lines) if len(clean_text(text)) >= 60 else []


def step(fnt: ImageFont.ImageFont, factor: float = 1.42) -> int:
    return int(getattr(fnt, "size", 20) * factor)


# ------------------------------------------------------------------ time and date


def arabic_date(value: datetime) -> str:
    return f"{ARABIC_DAYS[value.weekday()]} {value.day} {ARABIC_MONTHS[value.month - 1]} {value.year}"


def arabic_count(number: int, one: str, two: str, few: str, many: str) -> str:
    if number == 1:
        return one
    if number == 2:
        return two
    return f"{number} {few if 3 <= number <= 10 else many}"


def ago_text(published: datetime | None, now: datetime, rtl: bool) -> str:
    if not published:
        return ""
    minutes = max(0, int((now - published).total_seconds() // 60))
    if rtl:
        if minutes < 15:
            return "منذ قليل"
        if minutes < 60:
            return f"منذ {minutes} دقيقة"
        hours = minutes // 60
        if hours < 24:
            return "منذ " + arabic_count(hours, "ساعة", "ساعتين", "ساعات", "ساعة")
        return "منذ " + arabic_count(hours // 24, "يوم", "يومين", "أيام", "يوما")
    if minutes < 15:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    if minutes < 24 * 60:
        return f"{minutes // 60}h ago"
    return f"{minutes // (24 * 60)}d ago"


# ----------------------------------------------------------------------- imagery


def tint(color: Color, strength: float, base: Color = BG) -> Color:
    return tuple(int(base[i] + (color[i] - base[i]) * strength) for i in range(3))


def rounded_mask(width: int, height: int, radius: int, corners: tuple[bool, bool, bool, bool]) -> Image.Image:
    scale = 3
    mask = Image.new("L", (width * scale, height * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, width * scale - 1, height * scale - 1), radius=radius * scale, fill=255, corners=corners
    )
    return mask.resize((width, height), Image.Resampling.LANCZOS)


def fill_rounded(page: Image.Image, box: Box, radius: int, color: Color) -> None:
    width, height = box[2] - box[0], box[3] - box[1]
    page.paste(Image.new("RGB", (width, height), color), (box[0], box[1]), rounded_mask(width, height, radius, (True,) * 4))


def paste_image(
    page: Image.Image,
    photo: Image.Image,
    box: Box,
    radius: int = 0,
    corners: tuple[bool, bool, bool, bool] = (True, True, True, True),
) -> None:
    width, height = box[2] - box[0], box[3] - box[1]
    fitted = ImageOps.fit(photo, (width, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))
    mask = rounded_mask(width, height, radius, corners) if radius else None
    page.paste(fitted, (box[0], box[1]), mask)


def fade(page: Image.Image, box: Box, color: Color, max_alpha: int, start: float = 0.0, reverse: bool = False, power: float = 1.6) -> None:
    """Blend `color` over a box with an alpha ramp that grows toward the bottom (or the top when reversed)."""
    width, height = box[2] - box[0], box[3] - box[1]
    column = Image.new("L", (1, height))
    values = []
    for y in range(height):
        progress = (1 - y / max(1, height - 1)) if reverse else y / max(1, height - 1)
        ramp = max(0.0, (progress - start) / (1 - start))
        values.append(int(max_alpha * ramp**power))
    column.putdata(values)
    page.paste(Image.new("RGB", (width, height), color), (box[0], box[1]), column.resize((width, height)))


# ------------------------------------------------------------------------- pages


def new_page() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    page = Image.new("RGB", (PAGE_W, PAGE_H), BG)
    return page, ImageDraw.Draw(page)


def draw_running_header(draw: ImageDraw.ImageDraw, title: str, now: datetime, page_number: int) -> None:
    draw.rectangle((0, 0, PAGE_W, 6), fill=GOLD)
    put(draw, PAGE_W - MARGIN, 38, title, font(24, 800), GOLD, rtl=True)
    put(draw, MARGIN, 40, f"{page_number:02d}", font(22, 700), MUTED, rtl=False)
    date_text = arabic_date(now)
    put(draw, MARGIN + 52, 40, date_text, font(20, 500), FAINT, rtl=False)
    draw.line((MARGIN, 88, PAGE_W - MARGIN, 88), fill=LINE, width=1)


def draw_meta(
    draw: ImageDraw.ImageDraw, x_start: int, x_end: int, y: int, item: BriefItem, now: datetime, rtl: bool, size: int = 19
) -> None:
    """Colored dot, source name and relative time on one line."""
    color = style_of(item.category)[2]
    fnt = font(size, 600)
    when = ago_text(item.published_at, now, rtl)
    source = clamp_lines(draw, item.source, fnt, (x_end - x_start) // 2 + 60, 1)[0] if item.source else ""
    label = " · ".join(part for part in (source, when) if part)
    dot = 11
    if rtl:
        draw.ellipse((x_end - dot, y + 9, x_end, y + 9 + dot), fill=color)
        put(draw, x_end - dot - 12, y, label, fnt, MUTED, rtl=True)
    else:
        draw.ellipse((x_start, y + 9, x_start + dot, y + 9 + dot), fill=color)
        put(draw, x_start + dot + 12, y, label, fnt, MUTED, rtl=False)


# A block is (height, painter); the painter receives the page, its draw, the top-left origin and the link list.
Painter = Callable[[Image.Image, ImageDraw.ImageDraw, int, int, int, list[LinkArea]], None]


def hero_block(item: BriefItem, now: datetime, measure: ImageDraw.ImageDraw, scale: float = 1.0) -> tuple[int, Painter]:
    rtl = has_arabic(item.title)
    image_h = int(HERO_IMAGE_H * scale)
    pad = 30
    inner = CONTENT_W - 2 * pad
    color = style_of(item.category)[2]
    title_font, brief_font, pill_font = font(38, 800), font(23, 400), font(21, 700)
    title_lines = clamp_lines(measure, item.title, title_font, inner, 3)
    brief_lines = summary_lines(measure, item.brief, brief_font, inner, 3)

    height = image_h + 26 + 30 + 14 + len(title_lines) * step(title_font, 1.34) + 8
    if brief_lines:
        height += len(brief_lines) * step(brief_font, 1.5) + 10
    height += 20 + 46 + 28

    def paint(page: Image.Image, draw: ImageDraw.ImageDraw, x: int, y: int, index: int, links: list[LinkArea]) -> None:
        fill_rounded(page, (x, y, x + CONTENT_W, y + height), 24, CARD)
        paste_image(page, item.image, (x, y, x + CONTENT_W, y + image_h), 24, (True, True, False, False))
        fade(page, (x, y + image_h - 90, x + CONTENT_W, y + image_h), CARD, 120, power=2.0)
        left, right = x + pad, x + CONTENT_W - pad
        edge = right if rtl else left
        cursor = y + image_h + 26
        draw_meta(draw, left, right, cursor, item, now, rtl)
        cursor += 30 + 14
        for line in title_lines:
            put(draw, edge, cursor, line, title_font, INK, rtl)
            cursor += step(title_font, 1.34)
        cursor += 8
        for line in brief_lines:
            put(draw, edge, cursor, line, brief_font, MUTED, rtl)
            cursor += step(brief_font, 1.5)
        cursor += 10 + 20
        label = "اقرأ الخبر" if rtl else "Read story"
        width = text_w(draw, label, pill_font) + 48
        pill = (right - width, cursor, right, cursor + 46) if rtl else (left, cursor, left + width, cursor + 46)
        fill_rounded(page, pill, 23, color)
        text_x = (pill[0] + pill[2]) // 2
        prepared = shaped(label)
        draw.text((text_x, cursor + 23), prepared, font=pill_font, fill=BG, anchor="mm", **render_options(prepared))
        if item.url:
            links.append(LinkArea(index, (x, y, x + CONTENT_W, y + height), item.url))

    return height, paint


def grid_card_layout(
    item: BriefItem, width: int, measure: ImageDraw.ImageDraw, image_h: int
) -> tuple[int, list[str], list[str]]:
    lines = clamp_lines(measure, item.title, font(28, 800), width - 44, 3)
    brief_lines = summary_lines(measure, item.brief, font(20, 400), width - 44, 2)
    height = image_h + 22 + 30 + 12 + len(lines) * step(font(28, 800), 1.32) + 26
    if brief_lines:
        height += 8 + len(brief_lines) * step(font(20, 400), 1.5)
    return height, lines, brief_lines


def grid_row_block(pair: list[BriefItem], now: datetime, measure: ImageDraw.ImageDraw, scale: float = 1.0) -> tuple[int, Painter]:
    column_w = (CONTENT_W - GAP) // 2
    image_h = int(GRID_IMAGE_H * scale)
    layouts = [grid_card_layout(item, column_w, measure, image_h) for item in pair]
    height = max(layout[0] for layout in layouts)
    title_font, brief_font = font(28, 800), font(20, 400)

    def paint(page: Image.Image, draw: ImageDraw.ImageDraw, x: int, y: int, index: int, links: list[LinkArea]) -> None:
        # Arabic reads right to left, so the first story of a pair sits on the right.
        rtl_doc = has_arabic(pair[0].title)
        slots = [x + CONTENT_W - column_w, x] if rtl_doc else [x, x + CONTENT_W - column_w]
        for item, (_h, lines, brief_lines), left in zip(pair, layouts, slots):
            rtl = has_arabic(item.title)
            right = left + column_w
            fill_rounded(page, (left, y, right, y + height), 20, CARD)
            paste_image(page, item.image, (left, y, right, y + image_h), 20, (True, True, False, False))
            cursor = y + image_h + 22
            draw_meta(draw, left + 22, right - 22, cursor, item, now, rtl, size=18)
            cursor += 30 + 12
            edge = right - 22 if rtl else left + 22
            for line in lines:
                put(draw, edge, cursor, line, title_font, INK, rtl)
                cursor += step(title_font, 1.32)
            cursor += 8
            for line in brief_lines:
                put(draw, edge, cursor, line, brief_font, MUTED, rtl)
                cursor += step(brief_font, 1.5)
            if item.url:
                links.append(LinkArea(index, (left, y, right, y + height), item.url))

    return height, paint


def wide_block(item: BriefItem, now: datetime, measure: ImageDraw.ImageDraw) -> tuple[int, Painter]:
    rtl = has_arabic(item.title)
    image_w, pad = 330, 22
    text_w_limit = CONTENT_W - image_w - pad * 3
    title_font = font(28, 800)
    lines = clamp_lines(measure, item.title, title_font, text_w_limit, 3)
    height = max(WIDE_H, pad + 30 + 12 + len(lines) * step(title_font, 1.32) + pad)

    def paint(page: Image.Image, draw: ImageDraw.ImageDraw, x: int, y: int, index: int, links: list[LinkArea]) -> None:
        fill_rounded(page, (x, y, x + CONTENT_W, y + height), 20, CARD)
        right_edge = x + CONTENT_W
        if rtl:
            image_box = (right_edge - pad - image_w, y + pad, right_edge - pad, y + height - pad)
            text_left, text_right = x + pad, image_box[0] - pad
        else:
            image_box = (x + pad, y + pad, x + pad + image_w, y + height - pad)
            text_left, text_right = image_box[2] + pad, right_edge - pad
        paste_image(page, item.image, image_box, 14)
        cursor = y + pad
        draw_meta(draw, text_left, text_right, cursor, item, now, rtl, size=18)
        cursor += 30 + 12
        for line in lines:
            put(draw, text_right if rtl else text_left, cursor, line, title_font, INK, rtl)
            cursor += step(title_font, 1.32)
        if item.url:
            links.append(LinkArea(index, (x, y, x + CONTENT_W, y + height), item.url))

    return height, paint


SECTION_HEADER_H = 112


def section_header(category: str, number: int) -> tuple[int, Painter]:
    label, subtitle, color = style_of(category)

    def paint(page: Image.Image, draw: ImageDraw.ImageDraw, x: int, y: int, index: int, links: list[LinkArea]) -> None:
        right = x + CONTENT_W
        draw.rounded_rectangle((right - 8, y + 6, right, y + 82), radius=4, fill=color)
        put(draw, right - 28, y - 4, label, font(48, 800), INK, rtl=True)
        put(draw, right - 28, y + 62, subtitle, font(21, 400), MUTED, rtl=True)
        put(draw, x, y - 14, f"{number:02d}", font(92, 800), tint(color, 0.30), rtl=False)

    return SECTION_HEADER_H, paint


def section_blocks(
    category: str, number: int, items: list[BriefItem], now: datetime, measure: ImageDraw.ImageDraw, scale: float = 1.0
) -> list[tuple[int, Painter]]:
    """Header + hero stay together; the rest follow as grid rows, with an odd last story as a wide card."""
    header_h, header_paint = section_header(category, number)
    hero_h, hero_paint = hero_block(items[0], now, measure, scale)

    def lead_paint(page: Image.Image, draw: ImageDraw.ImageDraw, x: int, y: int, index: int, links: list[LinkArea]) -> None:
        header_paint(page, draw, x, y, index, links)
        hero_paint(page, draw, x, y + header_h + 22, index, links)

    blocks = [(header_h + 22 + hero_h, lead_paint)]
    rest = items[1:]
    while len(rest) >= 2:
        blocks.append(grid_row_block(rest[:2], now, measure, scale))
        rest = rest[2:]
    if rest:
        blocks.append(wide_block(rest[0], now, measure))
    return blocks


def section_pages(
    grouped: dict[str, list[BriefItem]],
    category_order: list[str],
    title: str,
    now: datetime,
    first_page_number: int,
    first_page_index: int,
    links: list[LinkArea],
) -> list[Image.Image]:
    """Flow section blocks across pages, starting a new page whenever the next block would not fit."""
    pages: list[Image.Image] = []
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    page = draw = None
    cursor = PAGE_TOP

    def start_page() -> None:
        nonlocal page, draw, cursor
        page, draw = new_page()
        pages.append(page)
        draw_running_header(draw, title, now, first_page_number + len(pages) - 1)
        cursor = PAGE_TOP

    number = 0
    for category in category_order:
        items = grouped.get(category, [])
        if not items:
            continue
        number += 1
        for scale in IMAGE_SCALES:
            blocks = section_blocks(category, number, items, now, measure, scale)
            total = sum(height for height, _painter in blocks) + GAP * (len(blocks) - 1)
            if total <= PAGE_BOTTOM - PAGE_TOP:
                break
        splittable = total > PAGE_BOTTOM - PAGE_TOP
        # A section stays on one page when it fits; only an oversized one is split block by block.
        if page is None or (not splittable and cursor + total > PAGE_BOTTOM):
            start_page()
        for block_height, painter in blocks:
            if splittable and cursor + block_height > PAGE_BOTTOM:
                start_page()
            painter(page, draw, MARGIN, cursor, first_page_index + len(pages) - 1, links)
            cursor += block_height + GAP
        cursor += 28
    return pages


def importance(item: BriefItem) -> tuple[int, float]:
    return item.score, item.published_at.timestamp() if item.published_at else 0.0


def cover_page(items: list[BriefItem], total: int, title: str, now: datetime, links: list[LinkArea]) -> Image.Image:
    page, draw = new_page()
    ranked = sorted(items, key=importance, reverse=True)
    lead = ranked[0]
    lead_color = style_of(lead.category)[2]

    hero_box = (0, 0, PAGE_W, COVER_HERO_H)
    paste_image(page, lead.image, hero_box)
    fade(page, (0, 0, PAGE_W, 260), (0, 0, 0), 170, reverse=True, power=1.3)
    fade(page, (0, 250, PAGE_W, COVER_HERO_H), BG, 255, start=0.12, power=1.25)

    draw.rectangle((PAGE_W - MARGIN - 64, 50, PAGE_W - MARGIN, 55), fill=GOLD)
    put(draw, PAGE_W - MARGIN, 70, title, font(38, 800), (255, 255, 255), rtl=True)
    put(draw, PAGE_W - MARGIN, 124, arabic_date(now), font(23, 500), (222, 228, 240), rtl=True)
    put(draw, MARGIN, 80, f"{len(items)} خبرا مختارا", font(21, 700), (222, 228, 240), rtl=False)

    rtl = has_arabic(lead.title)
    title_font = font(54, 800)
    lines = clamp_lines(draw, lead.title, title_font, CONTENT_W, 4)
    label = style_of(lead.category)[0]
    chip_font = font(21, 700)
    chip_w = text_w(draw, label, chip_font) + 36
    block_h = 44 + 22 + len(lines) * step(title_font, 1.28) + 18 + 30
    top = COVER_HERO_H - 70 - block_h
    chip = (PAGE_W - MARGIN - chip_w, top, PAGE_W - MARGIN, top + 44) if rtl else (MARGIN, top, MARGIN + chip_w, top + 44)
    fill_rounded(page, chip, 22, lead_color)
    prepared = shaped(label)
    draw.text(((chip[0] + chip[2]) // 2, top + 22), prepared, font=chip_font, fill=BG, anchor="mm", **render_options(prepared))
    cursor = top + 44 + 22
    for line in lines:
        put(draw, PAGE_W - MARGIN if rtl else MARGIN, cursor, line, title_font, (255, 255, 255), rtl)
        cursor += step(title_font, 1.28)
    cursor += 18
    draw_meta(draw, MARGIN, PAGE_W - MARGIN, cursor, lead, now, rtl, size=21)
    if lead.url:
        links.append(LinkArea(0, (0, 0, PAGE_W, COVER_HERO_H), lead.url))

    # "In this issue": the next most important stories, at most two per section so the list shows breadth.
    y = COVER_HERO_H + 8
    draw.rounded_rectangle((PAGE_W - MARGIN - 8, y + 6, PAGE_W - MARGIN, y + 40), radius=4, fill=GOLD)
    put(draw, PAGE_W - MARGIN - 28, y, "أبرز ما في العدد", font(32, 800), INK, rtl=True)
    y += 66

    per_category: dict[str, int] = {}
    picks: list[BriefItem] = []
    for item in ranked[1:]:
        if per_category.get(item.category, 0) >= 2:
            continue
        per_category[item.category] = per_category.get(item.category, 0) + 1
        picks.append(item)

    row_font = font(27, 700)
    for number, item in enumerate(picks[:COVER_ROWS_MAX], start=2):
        item_rtl = has_arabic(item.title)
        number_w = 74
        lines = clamp_lines(draw, item.title, row_font, CONTENT_W - number_w - 10, 2)
        row_h = len(lines) * step(row_font, 1.3) + 30 + 34
        if y + row_h > PAGE_BOTTOM:
            break
        draw.line((MARGIN, y, PAGE_W - MARGIN, y), fill=LINE, width=1)
        color = style_of(item.category)[2]
        if item_rtl:
            num_x, text_left, text_right = PAGE_W - MARGIN, MARGIN, PAGE_W - MARGIN - number_w
        else:
            num_x, text_left, text_right = MARGIN, MARGIN + number_w, PAGE_W - MARGIN
        put(draw, num_x, y + 14, f"{number:02d}", font(40, 800), tint(color, 0.85), item_rtl)
        cursor = y + 18
        for line in lines:
            put(draw, text_right if item_rtl else text_left, cursor, line, row_font, INK, item_rtl)
            cursor += step(row_font, 1.3)
        draw_meta(draw, text_left, text_right, cursor + 4, item, now, item_rtl, size=18)
        if item.url:
            links.append(LinkArea(0, (MARGIN, y + 4, PAGE_W - MARGIN, y + row_h - 4), item.url))
        y += row_h
    return page


def message_page(title: str, now: datetime, message: str) -> Image.Image:
    page, draw = new_page()
    draw_running_header(draw, title, now, 1)
    lines = wrap(draw, message, font(36, 700), CONTENT_W)
    y = PAGE_H // 2 - len(lines) * 30
    for line in lines:
        prepared = shaped(line)
        draw.text((PAGE_W // 2, y), prepared, font=font(36, 700), fill=MUTED, anchor="ma", **render_options(prepared))
        y += 60
    return page


# ----------------------------------------------------------------------- output


def pdf_rect(rect: Box) -> tuple[float, float, float, float]:
    left, top, right, bottom = rect
    return left * LINK_SCALE, (PAGE_H - bottom) * LINK_SCALE, right * LINK_SCALE, (PAGE_H - top) * LINK_SCALE


def save_pdf(pages: list[Image.Image], links: list[LinkArea], dated_path: Path, latest_path: Path) -> None:
    dated_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = dated_path.with_name(f"{dated_path.stem}_raw.pdf")
    first, *others = pages
    first.save(raw_path, "PDF", save_all=True, append_images=others, resolution=RESOLUTION, quality=90)

    writer = PdfWriter()
    for page in PdfReader(str(raw_path)).pages:
        writer.add_page(page)
    for link in links:
        if 0 <= link.page_index < len(writer.pages) and link.url:
            writer.add_annotation(link.page_index, Link(rect=pdf_rect(link.rect), url=link.url, border=[0, 0, 0]))
    with dated_path.open("wb") as handle:
        writer.write(handle)

    shutil.copyfile(dated_path, latest_path)
    try:
        raw_path.unlink()
    except OSError:
        pass


def build_pdf(
    items: list[BriefItem],
    total_collected: int,
    category_order: list[str],
    title: str,
    now: datetime,
    dated_path: Path,
    latest_path: Path,
    empty_message: str,
) -> None:
    links: list[LinkArea] = []
    if not items:
        pages = [message_page(title, now, empty_message)]
    else:
        grouped: dict[str, list[BriefItem]] = {}
        for item in items:
            grouped.setdefault(item.category, []).append(item)
        for bucket in grouped.values():
            bucket.sort(key=importance, reverse=True)
        pages = [cover_page(items, total_collected, title, now, links)]
        pages.extend(section_pages(grouped, category_order, title, now, 2, 1, links))
    save_pdf(pages, links, dated_path, latest_path)
