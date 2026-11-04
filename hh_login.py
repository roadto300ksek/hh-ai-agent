import sys

from playwright.sync_api import sync_playwright

from hh_browser import launch_context
from paths import STATE_FILE
from utils import configure_stdout

configure_stdout()


def save_session():
    with sync_playwright() as p:
        # Видимый режим обязателен для ручного входа, сессию пока не подставляем
        browser, context = launch_context(p, headless=False, use_state=False)
        try:
            page = context.new_page()

            print("🌐 Загружаю hh.ru...")
            last_error = None
            for attempt in range(1, 3):
                try:
                    page.goto("https://hh.ru", wait_until="domcontentloaded", timeout=60000)
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    print(f"⚠️ Попытка {attempt}/2 не удалась: {e}")
            if last_error:
                print("🛑 Не удалось открыть hh.ru. Проверь интернет и попробуй снова.")
                return

            print("👉 Пожалуйста, залогинься вручную в открывшемся окне браузера.")
            print("👉 После успешного входа нажми Enter в этой консоли...")

            if not sys.stdin or not sys.stdin.isatty():
                print("🛑 Нет интерактивной консоли — запусти hh_login.py из терминала.")
                return

            input()
            context.storage_state(path=str(STATE_FILE))
            print(f"✅ Сессия сохранена в файл {STATE_FILE.name}")
        finally:
            browser.close()


if __name__ == "__main__":
    save_session()
