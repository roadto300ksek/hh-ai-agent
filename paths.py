"""Единые пути проекта: скрипты больше не зависят от текущей папки запуска."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

ENV_FILE = BASE_DIR / ".env"
STATE_FILE = BASE_DIR / "hh_state.json"

VACANCIES_FILE = BASE_DIR / "vacancies.json"
ANALYZED_FILE = BASE_DIR / "analyzed_vacancies.json"
COVER_LETTERS_FILE = BASE_DIR / "cover_letters.json"
ACTIVE_CANDIDATES_FILE = BASE_DIR / "active_candidates.json"
AUTO_STATUS_FILE = BASE_DIR / "auto_status.json"

# ==== Data-Driven резюме (v2.0) ====
VACANCY_DETAILS_FILE = BASE_DIR / "vacancy_details.json"
MARKET_TRENDS_FILE = BASE_DIR / "market_trends.json"
USER_PROFILE_FILE = BASE_DIR / "user_real_profile.json"
RESUME_TARGETS_FILE = BASE_DIR / "resume_targets.json"
GENERATED_RESUMES_FILE = BASE_DIR / "generated_resumes.json"
RESUMES_MD_FILE = BASE_DIR / "resumes.md"
CREATED_RESUMES_FILE = BASE_DIR / "hh_created_resumes.json"

DB_PATH = BASE_DIR / "hh_agent.db"

SCREENSHOT_DIR = BASE_DIR / "executor_screenshots"
DEBUG_SCREENSHOT = BASE_DIR / "debug_screenshot.png"
DEBUG_PAGE = BASE_DIR / "debug_page.html"


def ensure_dirs():
    """Создает папки, которые нужны во время работы."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
