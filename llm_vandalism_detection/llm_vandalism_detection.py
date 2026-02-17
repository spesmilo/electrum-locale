#!/usr/bin/env python3
"""
Vandalism detection for translation files using LLM (OpenAI-compatible API).

Usage:
  ./llm_vandalism_detection.py --openai-url https://api.ppq.ai --openai-key YOUR_KEY --model google/gemini-3-flash-preview --locale-dir locale
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    import polib
except ImportError as e:
    sys.exit(f"Error: {str(e)}. Try 'python3 -m pip install --user polib' (or 'python3-polib' from Debian)")

try:
    import aiohttp
except ImportError as e:
    sys.exit(f"Error: {str(e)}. Try 'python3 -m pip install --user aiohttp' (or 'python3-aiohttp' from Debian)")



# Concurrency and retry configuration
CONCURRENCY_DEFAULT = 50
RETRY_DELAY_DEFAULT = 2.0  # seconds between retries

# OpenAI-compatible API configuration
OPENAI_BASE_URL_DEFAULT = "https://api.ppq.ai"
OPENAI_MODEL_DEFAULT = "google/gemini-3-flash-preview"  # this passes the unittest, cheaper than haiku, ~0.02 ct/req
# OPENAI_MODEL_DEFAULT = "claude-haiku-4.5"  # this passes the unittest, seems to work well, costs ~0.06 ct/req (ppq.ai)


PROMPT_TEMPLATE = """
You are a binary classifier for translation quality control.

Input format:
original_str: <original English string>
translation_str: <translated string>
target_language: <target language code>

Task:
Determine whether translation_str is a plausible translation of original_str into the target language.

Classification: Genuine or Spam

Genuine — translation_str is a plausible rendering of original_str in the target language. This includes:
- Natural/idiomatic translations that do not match word-for-word.
    - Translations that leave technical terms, brand names, or proper nouns untranslated.
- Translations that are significantly shorter or longer than original_str due to language characteristics.
- Partial translations where most meaning is preserved.
- Strings in scripts or character sets consistent with the target language.
- Strings that differ in formality, register, or phrasing but convey the same intent.

Spam — translation_str has no plausible relationship to original_str. Clear indicators:
- Completely unrelated topic (advertisements, political slogans, solicitations).
- Cryptocurrency addresses, any URLs, or contact information injected where none exists in original_str.
- Any URL appearing in translation_str that does not appear in original_str, even if it is seemingly related to Electrum.
- Obvious trolling, joke replacements, or intentionally offensive substitutions.
- Random character sequences with no linguistic structure.
- Empty string when original_str is non-empty.
- Text in a language entirely inconsistent with the target_language code.

Decision policy:
- Default to Genuine unless there is strong positive evidence of spam.
- Do NOT flag a string as Spam merely because you are uncertain about the language or translation accuracy.
- A poor-quality or inaccurate translation is still Genuine if it appears to be a good-faith attempt.
- When in doubt, output Spam.

Domain context:
- These are UI strings for a Bitcoin wallet application (Electrum Wallet).
- Placeholders (e.g., %1, %s, {{}}, ...), Qt markup (e.g., &, <b>, </b>), and technical tokens are expected and must not trigger Spam.
- References to bitcoin, transactions, wallets, keys, addresses, and blockchain terminology are expected domain vocabulary, not spam indicators.

Output requirements:
- Output exactly one token: Genuine or Spam
- No punctuation, explanation, or extra text.

Input:

original_str: {msgid}
translation_str: {msgstr}
target_language: {lang}
"""



def get_openai_url():
    return os.environ.get("OPENAI_BASE_URL", OPENAI_BASE_URL_DEFAULT)


def get_openai_model():
    return os.environ.get("OPENAI_MODEL", OPENAI_MODEL_DEFAULT)


def get_openai_api_key():
    return os.environ.get("OPENAI_API_KEY", "")


def get_concurrency():
    return int(os.environ.get("CONCURRENCY", CONCURRENCY_DEFAULT))


def get_retry_delay():
    return float(os.environ.get("RETRY_DELAY", RETRY_DELAY_DEFAULT))


def parse_po_file(filepath: str) -> list[tuple[str, str]]:
    """
    Parse a .po file and extract msgid/msgstr pairs.
    Returns list of (msgid, msgstr) tuples.
    """
    po = polib.pofile(filepath)
    return [(entry.msgid, entry.msgstr) for entry in po if entry.msgid]


async def call_openai_async(session: aiohttp.ClientSession, prompt: str) -> str:
    """
    Call an OpenAI-compatible API asynchronously using aiohttp.
    Retries indefinitely on failure with a delay between attempts.
    """
    url = f"{get_openai_url()}/chat/completions"
    api_key = get_openai_api_key()
    retry_delay = get_retry_delay()

    payload = {
        "model": get_openai_model(),
        "messages": [
            {"role": "user", "content": prompt}
        ],
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    while True:
        try:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as response:
                if response.status != 200:
                    body = await response.text()
                    raise RuntimeError(f"HTTP {response.status}: {body}")
                result = await response.json()
                response = result["choices"][0]["message"]["content"].strip().lower()
                assert response in ("genuine", "spam"), f"invalid response: {response}"
                return response
        except Exception as e:
            print(f"Request failed ({e}), retrying in {retry_delay}s...", file=sys.stderr)
            await asyncio.sleep(retry_delay)



async def classify_translation_async(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    msgid: str,
    msgstr: str,
    lang: str,
) -> str:
    """
    Classify a translation as Genuine or Spam using the OpenAI-compatible API asynchronously.
    """
    prompt = PROMPT_TEMPLATE.format(msgid=msgid, msgstr=msgstr, lang=lang)
    async with semaphore:
        response = await call_openai_async(session, prompt)
    if "genuine" in response:
        return "Genuine"
    return "Spam"


def get_report_path(output_dir: Path, locale_name: str) -> Path:
    """
    Get the report file path for a specific locale.
    """
    return output_dir / f"vandalism_report_{locale_name}.json"


def report_exists(output_dir: Path, locale_name: str) -> bool:
    """
    Check if a report already exists for the given locale.
    """
    return get_report_path(output_dir, locale_name).exists()


async def scan_po_file_async(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    po_file: Path,
    locale_name: str,
) -> list[dict]:
    """
    Scan a single .po file using concurrent async OpenAI API requests.
    Returns list of spam entries.
    """
    entries = parse_po_file(str(po_file))
    translated = [(mid, mst) for mid, mst in entries if mst]

    async def _check(msgid: str, msgstr: str):
        classification = await classify_translation_async(session, semaphore, msgid, msgstr, locale_name)
        if classification == "Spam":
            print(f"SPAM: {msgid} -> {msgstr}")
            return {"locale": locale_name, "original_str": msgid, "translation": msgstr}
        return None

    results = await asyncio.gather(*[_check(mid, mst) for mid, mst in translated])
    return [r for r in results if r is not None]


def write_locale_report(spam_entries: list[dict], output_dir: Path, locale_name: str):
    """
    Write spam entries for a single locale to a report file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = get_report_path(output_dir, locale_name)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated": datetime.now().isoformat(),
                "locale": locale_name,
                "total_spam": len(spam_entries),
                "entries": spam_entries,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"Report written: {json_path}")



async def scan_locale_directory_async(locale_dir: str, output_dir: str, force: bool = False) -> dict:
    """
    Scan all .po files using concurrent async OpenAI API requests.
    Skips locales that already have reports unless force=True.
    Returns dict with scan statistics.
    """
    locale_path = Path(locale_dir)
    output_path = Path(output_dir)
    concurrency = get_concurrency()
    semaphore = asyncio.Semaphore(concurrency)

    stats = {
        "scanned": 0,
        "skipped": 0,
        "total_spam": 0,
    }

    locales = {}
    for po_file in sorted(locale_path.rglob("*.po")):
        locale_name = po_file.parent.name
        if locale_name not in locales:
            locales[locale_name] = []
        locales[locale_name].append(po_file)

    async with aiohttp.ClientSession() as session:
        for locale_name in sorted(locales.keys()):
            if not force and report_exists(output_path, locale_name):
                print(f"Skipping {locale_name} (report exists)")
                stats["skipped"] += 1
                continue

            print(f"Scanning: {locale_name}")
            locale_spam = []

            for po_file in locales[locale_name]:
                spam_entries = await scan_po_file_async(session, semaphore, po_file, locale_name)
                locale_spam.extend(spam_entries)

            write_locale_report(locale_spam, output_path, locale_name)
            stats["scanned"] += 1
            stats["total_spam"] += len(locale_spam)

    return stats


def write_summary_report(output_dir: str):
    """
    Generate a summary report from all individual locale reports.
    """
    output_path = Path(output_dir)
    all_entries = []

    for report_file in sorted(output_path.glob("vandalism_report_*.json")):
        with open(report_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            all_entries.extend(data.get("entries", []))

    # Write combined text report
    txt_path = output_path / "vandalism_report_summary.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("VANDALISM DETECTION SUMMARY REPORT\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"Total spam entries detected: {len(all_entries)}\n")
        f.write("=" * 80 + "\n\n")

        # Group by locale
        by_locale = {}
        for entry in all_entries:
            locale = entry["locale"]
            if locale not in by_locale:
                by_locale[locale] = []
            by_locale[locale].append(entry)

        for locale in sorted(by_locale.keys()):
            entries = by_locale[locale]
            f.write(f"\n{'─' * 40}\n")
            f.write(f"LOCALE: {locale} ({len(entries)} entries)\n")
            f.write(f"{'─' * 40}\n\n")

            for entry in entries:
                f.write(f"Original: {entry['original_str']}\n")
                f.write(f"Translation: {entry['translation']}\n")
                f.write("\n")

    # Write combined JSON report
    json_path = output_path / "vandalism_report_summary.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated": datetime.now().isoformat(),
                "total_spam": len(all_entries),
                "entries": all_entries,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"\nSummary report written to: {txt_path}")
    print(f"Summary JSON written to: {json_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect vandalized translations using LLM"
    )
    parser.add_argument(
        "--locale-dir",
        default="locale",
        help="Path to locale directory (default: locale)",
    )
    parser.add_argument(
        "--output-dir",
        default="vandalism_reports",
        help="Output directory for reports (default: vandalism_reports)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-scan locales even if report exists",
    )
    parser.add_argument(
        "--count",
        action="store_true",
        help="Count translatable strings per locale and print totals (no LLM calls)",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Only generate summary report from existing locale reports",
    )
    parser.add_argument(
        "--openai-url",
        default=None,
        help=f"OpenAI-compatible API base URL (default: {OPENAI_BASE_URL_DEFAULT})",
    )
    parser.add_argument(
        "--openai-key",
        default=None,
        help="OpenAI API key (can also use OPENAI_API_KEY env var)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"Model to use (default depends on API backend)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help=f"Max concurrent requests for OpenAI backend (default: {CONCURRENCY_DEFAULT})",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=None,
        help=f"Seconds between retries on failed requests (default: {RETRY_DELAY_DEFAULT})",
    )
    args = parser.parse_args()

    if args.openai_url:
        os.environ["OPENAI_BASE_URL"] = args.openai_url
    if args.openai_key:
        os.environ["OPENAI_API_KEY"] = args.openai_key
    if args.model:
        os.environ["OPENAI_MODEL"] = args.model
    if args.concurrency is not None:
        os.environ["CONCURRENCY"] = str(args.concurrency)
    if args.retry_delay is not None:
        os.environ["RETRY_DELAY"] = str(args.retry_delay)

    if args.count:
        if not os.path.isdir(args.locale_dir):
            print(f"Error: Locale directory not found: {args.locale_dir}")
            return 1
        locale_path = Path(args.locale_dir)
        total = 0
        for po_file in sorted(locale_path.rglob("*.po")):
            locale_name = po_file.parent.name
            entries = parse_po_file(str(po_file))
            translated = [(mid, mst) for mid, mst in entries if mst]
            count = len(translated)
            total += count
            print(f"{locale_name}: {count} strings")
        print(f"\nTotal: {total} strings ({total} LLM requests)")
        return 0

    if args.summary_only:
        write_summary_report(args.output_dir)
        return 0

    if not os.path.isdir(args.locale_dir):
        print(f"Error: Locale directory not found: {args.locale_dir}")
        return 1

    print(f"API: OpenAI-compatible (async, concurrency={get_concurrency()})")
    print(f"URL: {get_openai_url()}")
    print(f"Model: {get_openai_model()}")
    print(f"Locale directory: {args.locale_dir}")
    print(f"Output directory: {args.output_dir}")
    print(f"Force re-scan: {args.force}")
    print()

    stats = asyncio.run(scan_locale_directory_async(args.locale_dir, args.output_dir, args.force))

    print()
    print(f"Scanned: {stats['scanned']} locales")
    print(f"Skipped: {stats['skipped']} locales (reports already exist)")
    print(f"Total spam found: {stats['total_spam']}")

    write_summary_report(args.output_dir)

    return 0


if __name__ == "__main__":
    exit(main())
