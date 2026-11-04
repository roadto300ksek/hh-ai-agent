"""Единая настройка Playwright: одинаковый отпечаток браузера во всех агентах."""
from pathlib import Path

from paths import STATE_FILE

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]

INIT_SCRIPT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


def launch_context(p, headless=False, use_state=True, storage_state=STATE_FILE):
    """Запускает Chromium и контекст с сохраненной сессией.

    Возвращает (browser, context). Закрывать browser должен вызывающий код.
    """
    browser = p.chromium.launch(headless=headless, args=LAUNCH_ARGS)

    options = {
        "user_agent": USER_AGENT,
        "viewport": {"width": 1366, "height": 768},
        "locale": "ru-RU",
        "timezone_id": "Europe/Moscow",
    }

    if use_state:
        state_path = Path(storage_state)
        if not state_path.exists():
            browser.close()
            raise FileNotFoundError(
                f"Файл сессии {state_path.name} не найден. "
                "Сначала запусти hh_login.py и войди в аккаунт."
            )
        options["storage_state"] = str(state_path)

    context = browser.new_context(**options)
    context.add_init_script(INIT_SCRIPT)
    return browser, context
