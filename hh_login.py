from playwright.sync_api import sync_playwright
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

def save_session():
    with sync_playwright() as p:
        # Маскируемся под обычный Chrome, чтобы hh.ru не блокировал
        browser = p.chromium.launch(
            headless=False,  # Видимый режим обязателен для ручного входа
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )

        # Скрываем факт, что это бот
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        page = context.new_page()

        print("🌐 Загружаю hh.ru...")
        try:
            # Ждём только DOM (структуру), а не все картинки и рекламу
            page.goto("https://hh.ru", wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"⚠️ Первая попытка не удалась: {e}")
            print("🔄 Пробую ещё раз...")
            page.goto("https://hh.ru", wait_until="domcontentloaded", timeout=60000)

        print("👉 Пожалуйста, залогинься вручную в открывшемся окне браузера.")
        print("👉 После успешного входа нажми Enter в этой консоли...")
        
        # Ждём, пока ты нажмёшь Enter в консоли
        input()

        # Сохраняем состояние сессии (cookies, localStorage) в файл
        context.storage_state(path="hh_state.json")
        print("✅ Сессия сохранена в файл hh_state.json")

        browser.close()

if __name__ == "__main__":
    save_session()