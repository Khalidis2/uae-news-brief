from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import winreg
except ImportError:  # pragma: no cover - Windows-only fallback
    winreg = None

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


PROJECT_DIR = Path(__file__).resolve().parent
NEWS_SCRIPT = PROJECT_DIR / "uae_news_demo.py"
DEFAULT_PDF_PATH = PROJECT_DIR / "uae_daily_brief.pdf"
BRIEFS_DIR = PROJECT_DIR / "briefs"
DEFAULT_CHAT_ID = "47329648"
TELEGRAM_API_TIMEOUT = 120
UAE_TIMEZONE = timezone(timedelta(hours=4), "GST")
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


def generate_pdf() -> None:
    subprocess.run([sys.executable, str(NEWS_SCRIPT)], cwd=PROJECT_DIR, check=True)


def dated_pdf_path(value: datetime | None = None) -> Path:
    value = value or datetime.now(UAE_TIMEZONE)
    return BRIEFS_DIR / f"uae_daily_brief_{value:%Y-%m-%d}_{value.strftime('%A').lower()}.pdf"


def telegram_caption(value: datetime | None = None) -> str:
    value = value or datetime.now(UAE_TIMEZONE)
    return f"موجز الإمارات اليومي - {ARABIC_DAYS[value.weekday()]} {value.day:02d} {ARABIC_MONTHS[value.month]} {value.year}"


def newest_dated_pdf() -> Path:
    dated_files = sorted(BRIEFS_DIR.glob("uae_daily_brief_*.pdf"), key=lambda path: path.stat().st_mtime, reverse=True)
    return dated_files[0] if dated_files else DEFAULT_PDF_PATH


def get_user_environment_variable(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value or winreg is None:
        return value

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            registry_value, _value_type = winreg.QueryValueEx(key, name)
            return str(registry_value).strip()
    except OSError:
        return ""


def send_document(bot_token: str, chat_id: str, pdf_path: Path, caption: str) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    api_url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    with pdf_path.open("rb") as pdf_file:
        response = requests.post(
            api_url,
            data={"chat_id": chat_id, "caption": caption},
            files={"document": (pdf_path.name, pdf_file, "application/pdf")},
            timeout=TELEGRAM_API_TIMEOUT,
        )

    if not response.ok:
        raise RuntimeError(f"Telegram send failed: HTTP {response.status_code} - {response.text}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and send the UAE daily brief PDF to Telegram.")
    parser.add_argument("--skip-generate", action="store_true", help="Send the existing PDF without regenerating it.")
    parser.add_argument("--pdf", type=Path, default=None, help="Path to the PDF file to send.")
    parser.add_argument(
        "--chat-id",
        default=get_user_environment_variable("TELEGRAM_CHAT_ID") or DEFAULT_CHAT_ID,
        help="Telegram chat ID.",
    )
    parser.add_argument(
        "--caption",
        default=None,
        help="Caption to send with the PDF.",
    )
    args = parser.parse_args()

    bot_token = get_user_environment_variable("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("Missing TELEGRAM_BOT_TOKEN.")
        print("Set it safely in Windows user environment variables:")
        print('[Environment]::SetEnvironmentVariable("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_FROM_BOTFATHER", "User")')
        print(f'[Environment]::SetEnvironmentVariable("TELEGRAM_CHAT_ID", "{args.chat_id}", "User")')
        return 2

    if not args.skip_generate:
        print("Generating PDF...")
        generate_pdf()

    pdf_path = (args.pdf or dated_pdf_path()).resolve()
    if not pdf_path.exists() and not args.pdf:
        pdf_path = newest_dated_pdf().resolve()
    caption = args.caption or telegram_caption()
    print(f"Sending PDF to Telegram chat {args.chat_id}: {pdf_path}")
    send_document(bot_token, args.chat_id, pdf_path, caption)
    print("Telegram message sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
