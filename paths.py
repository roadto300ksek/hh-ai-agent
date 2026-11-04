"""Единые пути проекта: скрипты больше не зависят от текущей папки запуска."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

ENV_FILE = BASE_DIR / ".env"
STATE_FILE = BASE_DIR / "hh_state.json"

VACANCIES_FILE = BASE_DIR / "vacancies.json"
ANALYZED_FILE = BASE_DIR / "analyzed_vacancies.json"
COVER_LETTERS_FILE = BASE_DIR / "cover_letters.json"

DB_PATH = BASE_DIR / "hh_agent.db"

SCREENSHOT_DIR = BASE_DIR / "executor_screenshots"
DEBUG_SCREENSHOT = BASE_DIR / "debug_screenshot.png"
DEBUG_PAGE = BASE_DIR / "debug_page.html"

RUN_LOG = BASE_DIR / "run_all.log"


def ensure_dirs():
    """Создает папки, которые нужны во время работы."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
