from playwright.sync_api import sync_playwright

from hh_browser import launch_context
from paths import DEBUG_PAGE, DEBUG_SCREENSHOT
from utils import configure_stdout

configure_stdout()


def debug_hh():
    with sync_playwright() as p:
        try:
            browser, context = launch_context(p, headless=False)
        except FileNotFoundError as e:
            print(f"🛑 {e}")
            return

        try:
            page = context.new_page()

            url = "https://hh.ru/search/vacancy?text=Python"
            print(f"Открываю: {url}")
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(10000)

            page.screenshot(path=str(DEBUG_SCREENSHOT), full_page=False)
            print(f"📸 Скриншот сохранён: {DEBUG_SCREENSHOT.name}")

            html = page.content()
            DEBUG_PAGE.write_text(html, encoding="utf-8")
            print(f"📄 HTML сохранён: {DEBUG_PAGE.name}")

            selectors_to_check = [
                '[data-qa="serp-item"]',
                '[data-qa="vacancy-serp__vacancy"]',
                '[data-qa="vacancy-serp-item"]',
                'div[class*="vacancy-card"]',
                'div[class*="serp-item"]',
                'article',
                'a[href*="/vacancy/"]',
            ]
            print("\n🔎 Проверка селекторов:")
            for sel in selectors_to_check:
                print(f"   {sel} -> {page.locator(sel).count()}")

            print(f"\n🌐 Текущий URL: {page.url}")
            print(f"📌 Заголовок: {page.title()}")

            content_lower = html.lower()
            for marker in ["captcha", "подтвердите", "робот", "доступ ограничен", "blocked"]:
                if marker in content_lower:
                    print(f"🚨 Найден маркер блокировки: '{marker}'")

            print("\nБраузер закроется через 30 секунд. Посмотри, что на экране!")
            page.wait_for_timeout(30000)
        finally:
            browser.close()


if __name__ == "__main__":
    debug_hh()
