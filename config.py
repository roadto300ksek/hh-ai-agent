"""Общие настройки проекта: профиль кандидата и единая точка вызова LLM."""
import os
import time

from dotenv import load_dotenv
from openai import OpenAI

from paths import ENV_FILE

load_dotenv(ENV_FILE)

MODEL_NAME = "deepseek-chat"
BASE_URL = "https://api.deepseek.com"
REQUEST_TIMEOUT = 60

# ============================================
# ПРОФИЛЬ КАНДИДАТА (используется анализатором)
# ============================================
CANDIDATE_PROFILE = """
Кандидат: Python-разработчик (Junior/Junior+), специализация — автоматизация бизнес-процессов, парсинг данных и интеграции с LLM/AI.
Навыки: Python, Playwright, FastAPI, Flask, aiogram, asyncio, REST API, JSON, парсинг данных, OpenAI SDK / DeepSeek API, SQLite, Streamlit, Linux, APScheduler, Git.
Желаемая роль: Junior/Junior+ Python-разработчик, AI-инженер (Junior), RPA-разработчик (Junior), Стажер.

ГЕОГРАФИЯ И ФОРМАТ РАБОТЫ:
- Идеально: удалённая работа.
- Хорошо: гибрид или офис в <ГОРОД>.
- Плохо: офис/гибрид в других городах без возможности удалёнки.

ВАЖНО (УРОВЕНЬ ОПЫТА):
- Цель: Junior и Junior+. Стажёр/Intern тоже подходит.
- Если в вакансии написано "Middle", "Middle+", "Senior", "Lead" или требуется опыт "от 2-3 лет", "3-6 лет" — ставь оценку 0-10.
- Если требуется опыт "1-3 года" и стек совпадает — оценивай внимательно, можно 40-60.

Готов к тестовому заданию и быстрому выходу на задачи по автоматизации, парсингу, интеграциям и AI-фичам.

НЕ подходят: 1С-разработка, Java, C++, PHP, менеджеры по продажам, преподаватели, вакансии без Python.
"""

# ============================================
# ИНФОРМАЦИЯ ДЛЯ ПИСЕМ (используется копирайтером)
# ============================================
CANDIDATE_INFO = """
Имя: <ИМЯ>
Город: <ГОРОД>
Формат работы: удалёнка или гибрид/офис в <ГОРОД>
Резюме: Python-разработчик (Junior/Junior+), специализация — автоматизация, парсинг и AI-интеграции.

Опыт и навыки:
- Python (основной язык), asyncio
- Playwright (автоматизация браузера, обход антибот-защиты, парсинг)
- FastAPI, Flask, aiogram (python-telegram-bot)
- OpenAI SDK / DeepSeek API (интеграция LLM)
- REST API, JSON, работа с cookies/сессиями
- SQLite, Streamlit, APScheduler, Linux, Git

Пет-проекты:
1. Мультиагентная система автоматизации поиска работы на HeadHunter: 5 агентов (авторизация → сканер → аналитик → копирайтер → исполнитель), Python, Playwright, DeepSeek API, SQLite, Streamlit, unittest. Результат: 460+ карточек за прогон, ИИ-фильтр отсеивает 75% нерелевантного.
2. Telegram-бот для изучения итальянского языка: python-telegram-bot, DeepSeek API, edge-tts/gTTS, Flask. 4 сценария диалога, перевод, объяснение грамматики, озвучка, деплой на PythonAnywhere.

Тон письма: уверенный, но без пафоса. Деловой, живой, без штампов типа "стрессоустойчивый" и "командный игрок".
"""


# ============================================
# ОТВЕТЫ КАНДИДАТА НА ВОПРОСЫ РАБОТОДАТЕЛЯ
# ============================================
# Меняй ответы здесь — они автоматически попадут в анкеты hh.ru.
CANDIDATE_ANSWERS = {
    "city": "<ГОРОД>",
    "citizenship": "Россия",
    "education": "<ОБРАЗОВАНИЕ>",
    "it_experience": "коммерческого опыта в IT нет; 6 месяцев активной разработки пет-проектов на Python",
    "total_experience": "<ОПЫТ>",
    "employment_format": "<ФОРМАТ ТРУДОУСТРОЙСТВА>",
    "salary_min": "<МИНИМУМ>",
    "salary_comfort": "<КОМФОРТ>",
    "salary_note": (
        "если в вакансии указана вилка — ориентироваться на неё; "
        "если вилка не указана — <МИНИМУМ> / <КОМФОРТ>"
    ),
    "work_format": "удалёнка или гибрид в вашем городе",
    "relocation": "переезд в другой город не рассматриваю",
    "business_trips": "к командировкам готов",
    "start": "готов приступить сразу",
    "ready_for_test": "готов выполнить тестовое задание",
    "english": "B1",
    "italian": "A2",
    "russian": "родной",
    "telegram": "@username",
    "phone": "+7 000 000-00-00",
    "email": "email@example.com",
    "github": "https://github.com/username",
    "portfolio": "ваши проекты",
    "criminal_record": "<СУДИМОСТЬ>",
    "driver_license": "<ПРАВА>",
    "consent": (
        "на согласия об обработке персональных данных и подобные "
        "юридические подтверждения — всегда «Да»"
    ),
}

# Личные данные подтягиваются из candidate_local.py, если он создан.
# Этот файл в .gitignore и не попадает в GitHub.
try:
    import candidate_local
except ImportError:
    candidate_local = None

if candidate_local is not None:
    CANDIDATE_PROFILE = getattr(
        candidate_local, "CANDIDATE_PROFILE", CANDIDATE_PROFILE
    )
    CANDIDATE_INFO = getattr(candidate_local, "CANDIDATE_INFO", CANDIDATE_INFO)
    CANDIDATE_ANSWERS = {
        **CANDIDATE_ANSWERS,
        **getattr(candidate_local, "CANDIDATE_ANSWERS", {}),
    }

CANDIDATE_ANSWER_RULES = f"""
ФАКТЫ ДЛЯ АНКЕТ:
- Город: {CANDIDATE_ANSWERS['city']}. Гражданство: {CANDIDATE_ANSWERS['citizenship']}.
- Образование: {CANDIDATE_ANSWERS['education']}.
- Опыт в IT: {CANDIDATE_ANSWERS['it_experience']}. {CANDIDATE_ANSWERS['total_experience']}.
- Формат трудоустройства: {CANDIDATE_ANSWERS['employment_format']}.
- Зарплата: {CANDIDATE_ANSWERS['salary_note']}.
- Формат работы: {CANDIDATE_ANSWERS['work_format']}. {CANDIDATE_ANSWERS['relocation']}. {CANDIDATE_ANSWERS['business_trips']}.
- Старт: {CANDIDATE_ANSWERS['start']}.
- Тестовое задание: {CANDIDATE_ANSWERS['ready_for_test']}.
- Языки: английский {CANDIDATE_ANSWERS['english']}, итальянский {CANDIDATE_ANSWERS['italian']}, русский — {CANDIDATE_ANSWERS['russian']}.
- Контакты: Telegram {CANDIDATE_ANSWERS['telegram']}, телефон {CANDIDATE_ANSWERS['phone']}, почта {CANDIDATE_ANSWERS['email']}. Указывать только если вопрос прямо просит контакт для связи.
- GitHub: {CANDIDATE_ANSWERS['github']}
- Портфолио: {CANDIDATE_ANSWERS['portfolio']}.
- {CANDIDATE_ANSWERS['criminal_record']}, {CANDIDATE_ANSWERS['driver_license']}.
- {CANDIDATE_ANSWERS['consent']}.

ПРАВИЛА:
- Не выдумывай компании, проекты, цифры, сроки и опыт, которых нет в фактах.
- Если спрашивают про опыт или результат, которого нет, не оставляй пустой ответ: честно скажи, что коммерческого опыта/результата пока нет, и опиши ближайший релевантный личный проект.
- Пустой ответ допустим только если вопрос требует факта, которого нет в профиле.
- Не выбирай варианты «Свой вариант» или «Другое», если есть подходящий конкретный вариант.
"""


def get_client(timeout=REQUEST_TIMEOUT):
    """Создает клиент DeepSeek. Понятно падает, если ключ не настроен."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY не найден. Создай файл .env и добавь строку "
            "DEEPSEEK_API_KEY=твой_ключ"
        )
    # max_retries=0: повторы делает ask_llm, чтобы не ждать дважды
    return OpenAI(base_url=BASE_URL, api_key=api_key, timeout=timeout, max_retries=0)


def _is_retryable(error):
    """401/403/400/404 — ошибки конфигурации, повторять их бессмысленно."""
    status = getattr(error, "status_code", None)
    if status in (400, 401, 403, 404):
        return False
    return True


def ask_llm(prompt, temperature=0.2, json_mode=False, retries=3, base_delay=2):
    """Запрос к LLM с повторами и экспоненциальной паузой.

    Один сбой сети или лимита больше не роняет всю пачку вакансий.
    """
    client = get_client()
    extra = {"response_format": {"type": "json_object"}} if json_mode else {}

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                **extra,
            )
            content = response.choices[0].message.content
            if content is None or not content.strip():
                raise ValueError("Модель вернула пустой ответ")
            return content
        except Exception as e:
            last_error = e
            if not _is_retryable(e) or attempt == retries:
                break
            delay = base_delay * (2 ** (attempt - 1))
            print(f"   ⚠️ Ошибка LLM (попытка {attempt}/{retries}): {e}")
            print(f"   🔄 Повтор через {delay} сек...")
            time.sleep(delay)

    raise last_error
