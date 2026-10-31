from playwright.sync_api import sync_playwright

def debug_hh():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state="hh_state.json")
        page = context.new_page()

        url = "https://hh.ru/search/vacancy?text=Python"
        print(f"Открываю: {url}")
        page.goto(url, wait_until="domcontentloaded")

        # Ждём 10 секунд, чтобы всё успело прогрузиться
        page.wait_for_timeout(10000)

        # Сохраняем скриншот — увидим, что на странице
        page.screenshot(path="debug_screenshot.png", full_page=False)
        print("📸 Скриншот сохранён: debug_screenshot.png")

        # Сохраняем HTML — по нему найдём правильные селекторы
        html = page.content()
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("📄 HTML сохранён: debug_page.html")

        # Проверяем разные возможные селекторы вакансий
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
            count = page.locator(sel).count()
            print(f"   {sel} -> {count}")

        # Проверяем URL — вдруг редирект на капчу или логин
        print(f"\n🌐 Текущий URL: {page.url}")
        print(f"📌 Заголовок: {page.title()}")

        # Проверяем, есть ли признаки капчи/блокировки
        content_lower = html.lower()
        for marker in ["captcha", "подтвердите", "робот", "доступ ограничен", "blocked"]:
            if marker in content_lower:
                print(f"🚨 Найден маркер блокировки: '{marker}'")

        print("\nБраузер закроется через 30 секунд. Посмотри, что на экране!")
        page.wait_for_timeout(30000)
        browser.close()

if __name__ == "__main__":
    debug_hh()