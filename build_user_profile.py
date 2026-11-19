"""Этап 4 (v2.0): построение user_real_profile.json из candidate_local.py.

Профиль — единственный источник фактов для генератора резюме. Скрипт берёт
личные данные из candidate_local.py и добавляет структурированные факты
(навыки, проекты, опыт), которых нет в текстовом профиле.

Запуск:
    python build_user_profile.py
"""
import sys
from datetime import datetime

from paths import USER_PROFILE_FILE
from utils import configure_stdout, log, write_json

configure_stdout(line_buffering=True)

try:
    import candidate_local
except ImportError:
    candidate_local = None


def contacts():
    """Личные данные берём из candidate_local, если он есть."""
    fallback = {
        "telegram": "<TELEGRAM>",
        "phone": "<PHONE>",
        "email": "<EMAIL>",
        "github": "https://github.com/roadto300ksek",
    }
    if candidate_local is None:
        return fallback

    answers = getattr(candidate_local, "CANDIDATE_ANSWERS", {})
    return {
        "telegram": answers.get("telegram", fallback["telegram"]),
        "phone": answers.get("phone", fallback["phone"]),
        "email": answers.get("email", fallback["email"]),
        "github": answers.get("github", fallback["github"]),
    }


def build_profile():
    return {
        "meta": {
            "created_at": datetime.now().isoformat(),
            "source": "candidate_local.py + резюме hh.ru от 19.11.2026",
            "version": "2.0",
        },
        "name": "Александр",
        "city": "Липецк",
        "level": "Junior/Junior+",
        "format": ["удалённо", "гибрид", "офис в городе"],
        "salary": {
            "min": 50000,
            "comfort": 70000,
            "note": "50–70 тыс. ₽, при указанной вилке в вакансии — ориентироваться на неё",
        },
        "hard_skills": [
            "Python",
            "asyncio",
            "Playwright",
            "FastAPI",
            "Flask",
            "aiogram 3",
            "python-telegram-bot",
            "OpenAI SDK",
            "DeepSeek API",
            "REST API",
            "JSON",
            "SQLite",
            "aiosqlite",
            "Streamlit",
            "APScheduler",
            "Linux",
            "Git",
            "unittest",
        ],
        "soft_skills": [
            "работа с людьми",
            "ответственность",
            "стрессоустойчивость",
            "командная работа",
            "самообучение",
            "внимательность к деталям",
        ],
        "projects": [
            {
                "name": "Мультиагентная система автоматизации поиска работы на HeadHunter",
                "stack": [
                    "Python", "Playwright", "DeepSeek API (OpenAI SDK)",
                    "SQLite", "Streamlit", "JSON", "unittest", "Git",
                ],
                "result": (
                    "5 агентов: авторизация → сканер → аналитик → копирайтер → "
                    "исполнитель. 460+ карточек за прогон, ИИ-фильтр отсеивает "
                    "75% нерелевантного, рутина сокращена с 3–4 часов до 15 минут в день."
                ),
                "url": "https://github.com/roadto300ksek/hh-ai-agent",
            },
            {
                "name": "Telegram-бот для изучения итальянского языка",
                "stack": [
                    "Python", "python-telegram-bot", "DeepSeek API",
                    "edge-tts/gTTS", "Flask", "Git",
                ],
                "result": (
                    "4 сценария диалога, перевод, объяснение грамматики, "
                    "автоматическая озвучка, антифлуд и защита от инъекций, "
                    "деплой на PythonAnywhere."
                ),
                "url": "https://github.com/roadto300ksek/italiano-bot",
            },
            {
                "name": "Telegram-бот с модерацией и планировщиком публикаций (meme-bot)",
                "stack": [
                    "Python", "aiogram 3", "aiosqlite (SQLite)",
                    "APScheduler", "Flask", "unittest", "Git",
                ],
                "result": (
                    "Индексация контента с дедупликацией по SHA-1, модерация "
                    "через pending-запросы, планировщик равномерных слотов, "
                    "очередь на 14 дней, восстановление после рестарта, "
                    "14 сценариев unittest на изолированной БД."
                ),
                "url": "https://github.com/roadto300ksek/meme-bot",
            },
        ],
        "experience": [
            {
                "role": "Компьютерный мастер",
                "period": "Март 2022 — сейчас",
                "facts": [
                    "настройка и администрирование локальных сетей",
                    "развёртывание и поддержка почтовых серверов",
                    "сопровождение антивирусного ПО",
                    "диагностика и ремонт ПК, консультации пользователей",
                ],
            },
            {
                "role": "Монтировщик сцены",
                "period": "Май 2025 — июнь 2026",
                "facts": [
                    "монтаж и демонтаж сценических конструкций",
                    "работа в команде по графику",
                    "соблюдение техники безопасности",
                ],
            },
            {
                "role": "Аниматор",
                "period": "Декабрь 2024 — январь 2026",
                "facts": [
                    "организация и проведение праздников для детей",
                    "работа с детьми и родителями",
                ],
            },
            {
                "role": "Поддержка Яндекс.Такси",
                "period": "Январь 2021 — февраль 2022",
                "facts": [
                    "рассмотрение обращений пассажиров и водителей",
                    "помощь в решении вопросов по заказам и сервису",
                ],
            },
        ],
        "it_experience": (
            "коммерческого опыта в IT нет; 6 месяцев активной разработки "
            "пет-проектов на Python"
        ),
        "total_experience": "общий стаж 5 лет 11 месяцев",
        "education": (
            "Липецкий государственный педагогический университет, "
            "русский язык и литература, 2012, неоконченное высшее"
        ),
        "languages": {"русский": "родной", "английский": "B1", "итальянский": "A2"},
        "forbidden_claims": [
            "5 лет опыта",
            "10 лет опыта",
            "коммерческий опыт в IT",
            "C++",
            "Java",
            "Middle",
            "Senior",
            "Lead",
            "Team Lead",
        ],
        "contacts": contacts(),
    }


def main():
    profile = build_profile()
    write_json(USER_PROFILE_FILE, profile)

    print(f"✅ Профиль сохранён: {USER_PROFILE_FILE.name}")
    print(f"   Навыков: {len(profile['hard_skills'])}")
    print(f"   Проектов: {len(profile['projects'])}")
    print(f"   Опыт (не IT): {len(profile['experience'])}")
    print(f"   Зарплата: {profile['salary']['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
