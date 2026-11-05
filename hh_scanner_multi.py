from urllib.parse import urlencode
import random
import sys
import time

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from hh_browser import launch_context
from paths import VACANCIES_FILE
from utils import configure_stdout, page_is_closed, try_read_json, write_json

configure_stdout()

# ============================================
# НАСТРОЙКИ ПАРАНОИКА (можно менять)
# ============================================
MIN_DELAY_BETWEEN_QUERIES = 15   # минимум секунд между запросами
MAX_DELAY_BETWEEN_QUERIES = 25   # максимум секунд между запросами
SCROLL_STEPS = 5                 # сколько раз прокрутить страницу вниз
SCROLL_PAUSE_MIN = 2             # минимум секунд между прокрутками
SCROLL_PAUSE_MAX = 4             # максимум секунд между прокрутками
SEARCH_PAGES = 2                 # сколько страниц выдачи собирать на запрос
NAVIGATION_ATTEMPTS = 2
# ============================================

# Фильтры на стороне hh.ru: не тратим токены LLM на заведомо неподходящее.
# area=113 — вся Россия. id города можно посмотреть в URL поиска на hh.ru.
# experience: noExperience,between1And3 — junior/стажёр и до 3 лет.
# schedule=remote — удалёнка (убери, если нужны офис и гибрид в <ГОРОД>е).
SEARCH_FILTERS = {
    "area": "113",
    "experience": "noExperience,between1And3",
    "schedule": "remote",
    "order_by": "publication_time",
    "items_on_page": "50",
}

# Список поисковых запросов. Можешь дополнять своими.
SEARCH_QUERIES = [
    "Python автоматизация",
    "Python парсинг",
    "RPA",
    "AI инженер",
    "LLM",
    "Playwright",
    "автоматизация бизнес-процессов",
    "разработчик ботов",
    "Python интеграция API",
    "промпт-инженер",
    "AI агент",
    "автоматизация рутинных задач",
]

CARD_SELECTORS = [
    '[data-qa="vacancy-serp__vacancy"]',
    '[data-qa="serp-item"]',
]


def human_delay(min_sec, max_sec):
    """Случайная пауза, чтобы поведение не выглядело роботом."""
    delay = random.uniform(min_sec, max_sec)
    print(f"   ⏳ Пауза {delay:.1f} сек...")
    time.sleep(delay)


def human_scroll(page):
    """Плавная прокрутка страницы с паузами, как будто человек читает."""
    for _ in range(SCROLL_STEPS):
        page.mouse.wheel(0, random.randint(400, 900))
        time.sleep(random.uniform(SCROLL_PAUSE_MIN, SCROLL_PAUSE_MAX))
    page.mouse.wheel(0, -300)
    time.sleep(1)


def build_search_url(query, page_num=0, filters=None):
    """Собирает URL поиска с фильтрами и номером страницы."""
    params = {"text": query, "page": page_num, **(filters or SEARCH_FILTERS)}
    return f"https://hh.ru/search/vacancy?{urlencode(params)}"


def normalize_link(link):
    if not link:
        return None
    link = link.split("?")[0]
    if link.startswith("/"):
        link = f"https://hh.ru{link}"
    return link


def is_captcha_page(page):
    if "captcha" in page.url.lower():
        return True
    return page.locator('iframe[src*="captcha.hh.ru"]').count() > 0


def wait_for_captcha(page):
    """Возвращает True, если можно продолжать. Без консоли не блокируем весь pipeline."""
    if not is_captcha_page(page):
        return True

    print("   🚨 КАПЧА!")
    if not sys.stdin or not sys.stdin.isatty():
        print("   Консоли нет (запуск из дашборда) — пропускаю запрос.")
        return False

    input("   Пройди капчу в браузере и нажми Enter...")
    return True


def navigate(page, url):
    """Открывает страницу с одной повторной попыткой."""
    for attempt in range(1, NAVIGATION_ATTEMPTS + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(random.randint(4000, 7000))
            return True
        except Exception as e:
            if page_is_closed(page):
                raise
            print(f"   ⚠️ Попытка {attempt}/{NAVIGATION_ATTEMPTS} не удалась: {e}")
            if attempt < NAVIGATION_ATTEMPTS:
                time.sleep(3)
    return False


def parse_cards(page):
    """Парсит карточки выдачи. Возвращает только валидные записи."""
    cards = []
    for selector in CARD_SELECTORS:
        cards = page.locator(selector).all()
        if cards:
            break
    print(f"   Найдено карточек: {len(cards)}")

    result = []
    for card in cards:
        try:
            title_el = card.locator('[data-qa="serp-item__title"]').first
            if title_el.count() == 0:
                continue
            title = title_el.inner_text().strip()
            link = normalize_link(title_el.get_attribute("href"))
            if not title or not link:
                continue

            company_el = card.locator('[data-qa="vacancy-serp__vacancy-employer"]').first
            company = company_el.inner_text().strip() if company_el.count() > 0 else "Не указана"

            # Берем и обязанности, и требования: без требований LLM не видит
            # уровень опыта (Junior/Middle/Senior) и оценивает вслепую.
            snippet_parts = []
            for qa in (
                "vacancy-serp__vacancy_snippet_responsibility",
                "vacancy-serp__vacancy_snippet_requirement",
            ):
                snippet_el = card.locator(f'[data-qa="{qa}"]').first
                if snippet_el.count() > 0:
                    text = snippet_el.inner_text().strip()
                    if text:
                        snippet_parts.append(text)

            result.append({
                "title": title,
                "company": company,
                "link": link,
                "snippet": " ".join(snippet_parts),
                "found_by": "",
            })
        except Exception as e:
            print(f"   ⚠️ Ошибка парсинга карточки: {e}")
    return result


def scrape_query(page, query, page_num=0):
    """Собирает вакансии по одному запросу с одной страницы выдачи."""
    url = build_search_url(query, page_num)
    print(f"\n🔍 Ищу: {query} (страница {page_num + 1})")
    print(f"   URL: {url}")

    if not navigate(page, url):
        return []
    if not wait_for_captcha(page):
        return []

    # Плавная прокрутка вниз — подгружаем все карточки
    human_scroll(page)

    vacancies = parse_cards(page)
    for vacancy in vacancies:
        vacancy["found_by"] = query
    return vacancies


def stop_if_page_closed(page):
    """Закрытый браузер — это остановка пользователем, а не сбой селекторов."""
    if page_is_closed(page):
        print("\n🛑 Окно браузера закрыто. Сбор вакансий остановлен.")
        print(f"📁 Старый {VACANCIES_FILE.name} сохранен.")
        raise SystemExit(1)


def scrape_hh():
    all_vacancies = {}

    with sync_playwright() as p:
        try:
            browser, context = launch_context(p, headless=False)
        except FileNotFoundError as e:
            print(f"🛑 {e}")
            return

        try:
            page = context.new_page()
            total_queries = len(SEARCH_QUERIES)

            for idx, query in enumerate(SEARCH_QUERIES, start=1):
                stop_if_page_closed(page)
                print(f"\n{'='*50}")
                print(f"📊 Запрос {idx}/{total_queries}")
                print(f"{'='*50}")

                for page_num in range(SEARCH_PAGES):
                    stop_if_page_closed(page)
                    vacancies = scrape_query(page, query, page_num)

                    new_count = 0
                    for v in vacancies:
                        link = v["link"]
                        if link not in all_vacancies:
                            all_vacancies[link] = v
                            new_count += 1
                    print(f"   ➕ Новых уникальных: {new_count}")

                    # Дошли до конца выдачи — дальше страницы листать незачем
                    if not vacancies:
                        break

                    if page_num < SEARCH_PAGES - 1:
                        human_delay(5, 10)

                if idx < total_queries:
                    human_delay(MIN_DELAY_BETWEEN_QUERIES, MAX_DELAY_BETWEEN_QUERIES)
        except PlaywrightError as e:
            print("\n🛑 Браузер закрыт или недоступен. Сбор вакансий остановлен.")
            print(f"   Причина: {e}")
            print(f"📁 Старый {VACANCIES_FILE.name} сохранен.")
            raise SystemExit(1)
        finally:
            try:
                browser.close()
            except Exception:
                pass

    final_list = list(all_vacancies.values())

    if not final_list:
        old = try_read_json(VACANCIES_FILE, [])
        old_count = len(old) if isinstance(old, list) else 0
        print("\n⚠️ Не найдено ни одной вакансии (капча/блокировка/селекторы).")
        print(f"📁 Старый {VACANCIES_FILE.name} сохранен ({old_count} вакансий).")
        return

    write_json(VACANCIES_FILE, final_list)

    print(f"\n{'='*50}")
    print(f"✅ ИТОГО уникальных вакансий: {len(final_list)}")
    print(f"📁 Файл: {VACANCIES_FILE.name}")
    print(f"{'='*50}")


if __name__ == "__main__":
    scrape_hh()
