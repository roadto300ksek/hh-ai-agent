"""Этап 2 (v2.0): сбор полных описаний вакансий для анализа рынка.

Берёт ссылки из vacancies.json, открывает каждую страницу через Playwright
и сохраняет полный текст описания в vacancy_details.json.

Скрипт запускается отдельно от основного пайплайна:
    python hh_details_collector.py            # до 300 вакансий
    python hh_details_collector.py --limit 50 # быстрая проверка
    python hh_details_collector.py --headless # без окна браузера

Собирает инкрементально: уже собранные ссылки пропускаются, прогресс
сохраняется после каждой вакансии.
"""
import argparse
import random
import sys
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

from hh_browser import launch_context
from paths import STATE_FILE, VACANCIES_FILE, VACANCY_DETAILS_FILE
from utils import configure_stdout, log, page_is_closed, read_json, write_json

configure_stdout(line_buffering=True)

# ============================================
# НАСТРОЙКИ
# ============================================
DEFAULT_LIMIT = 300
PAGE_WAIT_MIN = 3
PAGE_WAIT_MAX = 6
NAVIGATION_ATTEMPTS = 2
SAMPLE_SEED = 42

TITLE_SELECTORS = ['[data-qa="vacancy-title"]', "h1"]
COMPANY_SELECTORS = [
    '[data-qa="vacancy-employer-name"]',
    '[data-qa="vacancy-company-name"]',
    '[data-qa="vacancy-company"]',
]
DESCRIPTION_SELECTORS = [
    '[data-qa="vacancy-description"]',
    '[data-qa="vacancy-description-item"]',
]

BLOCK_MARKERS = [
    "hh.ru недоступен",
    "владелец сайта запретил доступ",
    "доступ ограничен",
    "подтвердите, что вы не робот",
    "ддос-guard",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Сбор полных описаний вакансий")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--retry-empty",
        action="store_true",
        help="повторить вакансии из исходной выборки, где описание не собралось",
    )
    return parser.parse_args()


def first_text(page, selectors, timeout_ms=3000):
    """Первый непустой текст из списка селекторов."""
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        try:
            text = locator.first.inner_text(timeout=timeout_ms).strip()
        except Exception:
            continue
        if text:
            return text
    return ""


def read_description(page):
    """Описание вакансии; у архивных сначала раскрывает скрытый блок."""
    try:
        page.wait_for_selector('[data-qa="vacancy-description"]', timeout=8000)
    except Exception:
        pass

    description = first_text(page, DESCRIPTION_SELECTORS)
    if description:
        return description

    expand = page.locator('button:has-text("Показать описание вакансии")')
    if expand.count():
        try:
            expand.first.click(timeout=4000)
            page.wait_for_timeout(2000)
        except Exception:
            return ""
        return first_text(page, DESCRIPTION_SELECTORS, timeout_ms=5000)
    return ""


class SessionExpired(Exception):
    """Сессия hh.ru протухла: страница ведёт на форму входа."""


def is_login_url(url):
    url = (url or "").lower()
    return "/account/login" in url or url.rstrip("/").endswith("/login")


def is_blocked(page):
    """True, если hh.ru показал DDoS-Guard, капчу или блокировку IP."""
    title = (page.title() or "").lower()
    if "ddos-guard" in title or "недоступен" in title:
        return True
    try:
        body = page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        return False
    return any(marker in body for marker in BLOCK_MARKERS)


def load_existing():
    """Читает уже собранные описания, чтобы не открывать их повторно."""
    data = read_json(VACANCY_DETAILS_FILE, None)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return {"meta": {}, "items": []}
    # Пустые описания (например, после протухшей сессии) пересобираем заново.
    items = [
        item for item in data["items"]
        if isinstance(item, dict) and str(item.get("description", "")).strip()
    ]
    return {"meta": data.get("meta", {}), "items": items}


def select_candidates(vacancies, existing_links, limit):
    """Определяет, какие вакансии ещё предстоит собрать."""
    candidates = []
    seen = set(existing_links)
    for item in vacancies:
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        if not link or link in seen:
            continue
        seen.add(link)
        candidates.append(item)

    rng = random.Random(SAMPLE_SEED)
    rng.shuffle(candidates)
    return candidates[:limit]


def collect_one(page, vacancy):
    """Открывает вакансию и возвращает её полное описание."""
    link = vacancy["link"]
    for attempt in range(1, NAVIGATION_ATTEMPTS + 1):
        try:
            page.goto(link, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(random.randint(PAGE_WAIT_MIN, PAGE_WAIT_MAX) * 1000)
            if is_login_url(page.url):
                raise SessionExpired()
            if is_blocked(page):
                return None
            description = read_description(page)
            if not description:
                log("   ⚠️ Пустое описание — не сохраняю, попробую в следующий раз.")
                return "skip"
            return {
                "link": link,
                "title": first_text(page, TITLE_SELECTORS) or vacancy.get("title", ""),
                "company": first_text(page, COMPANY_SELECTORS) or vacancy.get("company", ""),
                "description": description,
            }
        except SessionExpired:
            raise
        except Exception as e:
            if page_is_closed(page):
                raise
            log(f"   ⚠️ Попытка {attempt}/{NAVIGATION_ATTEMPTS} не удалась: {e}")
            if attempt < NAVIGATION_ATTEMPTS:
                time.sleep(3)
    return None


def main():
    args = parse_args()

    vacancies = read_json(VACANCIES_FILE, [])
    if not isinstance(vacancies, list) or not vacancies:
        print("❌ vacancies.json пуст или отсутствует. Сначала запусти hh_scanner_multi.py")
        return 1

    existing = load_existing()
    items = [item for item in existing["items"] if isinstance(item, dict)]
    existing_links = {item.get("link") for item in items if item.get("link")}

    candidates = select_candidates(vacancies, existing_links, args.limit)
    if args.retry_empty:
        original_limit = existing["meta"].get("limit") or args.limit
        original = select_candidates(vacancies, set(), original_limit)
        candidates = [c for c in original if c.get("link") not in existing_links]
        log(f"🔁 Повторю вакансии без описания из первой выборки: {len(candidates)}")
    log(f"📊 Всего вакансий в vacancies.json: {len(vacancies)}")
    log(f"📁 Уже собрано описаний: {len(items)}")
    log(f"🎯 К сбору в этот запуск: {len(candidates)} (лимит {args.limit})")

    if not candidates:
        print("🎉 Новых вакансий для сбора нет.")
        return 0

    if not STATE_FILE.exists():
        print(f"🛑 Нет файла сессии {STATE_FILE.name}. Запусти hh_login.py.")
        return 1

    collected = 0
    with sync_playwright() as p:
        try:
            browser, context = launch_context(p, headless=args.headless)
        except FileNotFoundError as e:
            print(f"🛑 {e}")
            return 1

        try:
            page = context.new_page()

            for index, vacancy in enumerate(candidates, start=1):
                if page_is_closed(page):
                    log("🛑 Окно браузера закрыто. Останавливаюсь.")
                    break

                log(f"[{index}/{len(candidates)}] {vacancy.get('title', '')}")
                try:
                    result = collect_one(page, vacancy)
                except SessionExpired:
                    log("🛑 Сессия hh.ru истекла. Запусти hh_login.py и повтори.")
                    break

                if result is None:
                    log("🛑 hh.ru заблокировал доступ или вакансия недоступна. Останавливаюсь.")
                    break
                if result == "skip":
                    continue

                items.append(result)
                collected += 1
                write_json(VACANCY_DETAILS_FILE, {
                    "meta": {
                        "created_at": datetime.now().isoformat(),
                        "source_file": VACANCIES_FILE.name,
                        "collected": len(items),
                        "limit": args.limit,
                    },
                    "items": items,
                })

                if index < len(candidates):
                    page.wait_for_timeout(random.randint(PAGE_WAIT_MIN, PAGE_WAIT_MAX) * 1000)
        except KeyboardInterrupt:
            log("\n🛑 Остановлено пользователем.")
        finally:
            try:
                browser.close()
            except Exception:
                pass

    write_json(VACANCY_DETAILS_FILE, {
        "meta": {
            "created_at": datetime.now().isoformat(),
            "source_file": VACANCIES_FILE.name,
            "collected": len(items),
            "limit": args.limit,
        },
        "items": items,
    })

    log(f"✅ Собрано за запуск: {collected}. Всего описаний: {len(items)}.")
    log(f"📁 Файл: {VACANCY_DETAILS_FILE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
