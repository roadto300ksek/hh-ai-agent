from playwright.sync_api import sync_playwright
import json
import time
import random

# ============================================
# НАСТРОЙКИ ПАРАНОИКА (можно менять)
# ============================================
MIN_DELAY_BETWEEN_QUERIES = 15   # минимум секунд между запросами
MAX_DELAY_BETWEEN_QUERIES = 25   # максимум секунд между запросами
SCROLL_STEPS = 5                 # сколько раз прокрутить страницу вниз
SCROLL_PAUSE_MIN = 2             # минимум секунд между прокрутками
SCROLL_PAUSE_MAX = 4             # максимум секунд между прокрутками
# ============================================

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


def human_delay(min_sec, max_sec):
    """Случайная пауза, чтобы поведение не выглядело роботом."""
    delay = random.uniform(min_sec, max_sec)
    print(f"   ⏳ Пауза {delay:.1f} сек...")
    time.sleep(delay)


def human_scroll(page):
    """Плавная прокрутка страницы с паузами, как будто человек читает."""
    for step in range(SCROLL_STEPS):
        scroll_by = random.randint(400, 900)
        page.mouse.wheel(0, scroll_by)
        pause = random.uniform(SCROLL_PAUSE_MIN, SCROLL_PAUSE_MAX)
        time.sleep(pause)
    page.mouse.wheel(0, -300)
    time.sleep(1)


def scrape_query(page, query):
    """Собирает вакансии по одному запросу."""
    url = f"https://hh.ru/search/vacancy?text={query}"
    print(f"\n🔍 Ищу: {query}")
    print(f"   URL: {url}")

    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(random.randint(4000, 7000))
    except Exception as e:
        print(f"   ⚠️ Не удалось открыть страницу: {e}")
        return []

    # Плавная прокрутка вниз — подгружаем все карточки
    human_scroll(page)

    # Проверяем, не вылезла ли капча
    if page.locator('iframe[src*="captcha"]').count() > 0 and "recaptcha" not in page.url.lower():
        # Более точная проверка — только реальные капчи hh.ru
        captcha_visible = page.locator('iframe[src*="captcha.hh.ru"]').count() > 0
        if captcha_visible:
            print("   🚨 КАПЧА! Пройди её вручную в браузере, потом нажми Enter в консоли...")
            input()

    # ← ИСПРАВЛЕННЫЙ СЕЛЕКТОР
    cards = page.locator('[data-qa="vacancy-serp__vacancy"]').all()
    print(f"   Найдено карточек: {len(cards)}")

    result = []
    for card in cards:
        try:
            title_el = card.locator('[data-qa="serp-item__title"]').first
            title = title_el.inner_text().strip()
            link = title_el.get_attribute("href")
            if link and "?" in link:
                link = link.split("?")[0]

            company_el = card.locator('[data-qa="vacancy-serp__vacancy-employer"]').first
            company = company_el.inner_text().strip() if company_el.count() > 0 else "Не указана"

            snippet_el = card.locator('[data-qa="vacancy-serp__vacancy_snippet_responsibility"]').first
            snippet = snippet_el.inner_text().strip() if snippet_el.count() > 0 else ""

            result.append({
                "title": title,
                "company": company,
                "link": link,
                "snippet": snippet,
                "found_by": query,
            })
        except Exception as e:
            print(f"   ⚠️ Ошибка парсинга карточки: {e}")
    return result


def scrape_hh():
    all_vacancies = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = browser.new_context(
            storage_state="hh_state.json",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )

        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        page = context.new_page()

        total_queries = len(SEARCH_QUERIES)
        for idx, query in enumerate(SEARCH_QUERIES, start=1):
            print(f"\n{'='*50}")
            print(f"📊 Запрос {idx}/{total_queries}")
            print(f"{'='*50}")

            vacancies = scrape_query(page, query)
            new_count = 0
            for v in vacancies:
                if v["link"] and v["link"] not in all_vacancies:
                    all_vacancies[v["link"]] = v
                    new_count += 1
            print(f"   ➕ Новых уникальных: {new_count}")

            if idx < total_queries:
                human_delay(MIN_DELAY_BETWEEN_QUERIES, MAX_DELAY_BETWEEN_QUERIES)

        browser.close()

    final_list = list(all_vacancies.values())

    with open("vacancies.json", "w", encoding="utf-8") as f:
        json.dump(final_list, f, ensure_ascii=False, indent=4)

    print(f"\n{'='*50}")
    print(f"✅ ИТОГО уникальных вакансий: {len(final_list)}")
    print(f"📁 Файл: vacancies.json")
    print(f"{'='*50}")


if __name__ == "__main__":
    scrape_hh()