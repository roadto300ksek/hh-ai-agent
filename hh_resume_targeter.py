"""Этап 5 (v2.0): целевые категории вакансий под профиль кандидата.

Читает user_real_profile.json и market_trends.json, предлагает 10 категорий
вакансий (от самой релевантной к менее релевантной) и сохраняет
resume_targets.json. Если LLM недоступен, используется встроенный список.

Запуск:
    python hh_resume_targeter.py
"""
import json
import sys
from datetime import datetime

from config import ask_llm
from paths import MARKET_TRENDS_FILE, RESUME_TARGETS_FILE, USER_PROFILE_FILE
from utils import configure_stdout, log, read_json, write_json

configure_stdout(line_buffering=True)

# ============================================
# ВСТРОЕННЫЙ СПИСОК (fallback и точка отсчёта)
# ============================================
DEFAULT_TARGETS = [
    {
        "rank": 1,
        "focus": "automation",
        "title": "Python-разработчик (автоматизация бизнес-процессов)",
        "why": "Playwright, APScheduler и мультиагентная система — прямой опыт автоматизации рутины.",
        "real_anchors": ["Python", "Playwright", "APScheduler", "Streamlit"],
        "missing": ["коммерческий опыт", "UiPath/Robot Framework"],
        "match_keywords": ["автоматизация", "rpa", "python", "playwright", "процессы"],
    },
    {
        "rank": 2,
        "focus": "parsing",
        "title": "Python-разработчик (парсинг и сбор данных)",
        "why": "Playwright, cookies/сессии, обход антибота, дедупликация, 460+ карточек за прогон.",
        "real_anchors": ["Python", "Playwright", "JSON", "SQLite"],
        "missing": ["Scrapy", "Selenium", "прокси-пулы"],
        "match_keywords": ["парсинг", "сбор данных", "scraping", "playwright", "данные"],
    },
    {
        "rank": 3,
        "focus": "backend",
        "title": "Junior Python Backend-разработчик (REST API)",
        "why": "Flask/FastAPI, REST, JSON, SQLite, OpenAI SDK — базовый бэкенд в пет-проектах.",
        "real_anchors": ["Python", "Flask", "FastAPI", "REST API", "SQLite"],
        "missing": ["коммерческий опыт", "PostgreSQL", "Docker"],
        "match_keywords": ["backend", "rest", "api", "flask", "fastapi", "python"],
    },
    {
        "rank": 4,
        "focus": "ai",
        "title": "AI-инженер / LLM-разработчик (Junior)",
        "why": "DeepSeek/OpenAI SDK, промпты, мультиагентная система и Telegram-бот с LLM.",
        "real_anchors": ["Python", "OpenAI SDK", "DeepSeek API", "REST API"],
        "missing": ["LangChain/RAG", "векторные БД", "коммерческий опыт"],
        "match_keywords": ["ai", "llm", "нейросети", "агенты", "openai", "deepseek"],
    },
    {
        "rank": 5,
        "focus": "bots",
        "title": "Разработчик Telegram-ботов",
        "why": "python-telegram-bot, aiogram 3, asyncio, TTS, APScheduler, антифлуд, деплой.",
        "real_anchors": ["Python", "python-telegram-bot", "aiogram 3", "asyncio", "APScheduler"],
        "missing": ["коммерческие боты", "админка"],
        "match_keywords": ["telegram", "бот", "aiogram", "telegram bot", "python"],
    },
    {
        "rank": 6,
        "focus": "internal_tools",
        "title": "Python-разработчик внутренних инструментов",
        "why": "Streamlit-дашборд, Flask, SQLite, планировщик — опыт создания внутренних сервисов.",
        "real_anchors": ["Python", "Streamlit", "Flask", "SQLite", "APScheduler"],
        "missing": ["фронтенд", "продакшен-стек"],
        "match_keywords": ["streamlit", "внутренние инструменты", "дашборд", "flask", "python"],
    },
    {
        "rank": 7,
        "focus": "qa",
        "title": "QA Automation / Автотестирование (Python)",
        "why": "Playwright, unittest: 30 тестов в hh-ai-agent и 14 сценариев в meme-bot.",
        "real_anchors": ["Python", "Playwright", "unittest"],
        "missing": ["pytest", "Selenium", "CI/CD"],
        "match_keywords": ["qa", "автотесты", "тестирование", "playwright", "python"],
    },
    {
        "rank": 8,
        "focus": "integration",
        "title": "Интегратор API / Backend-разработчик",
        "why": "REST, OpenAI SDK, JSON, Flask — работа с внешними API и интеграциями.",
        "real_anchors": ["Python", "REST API", "JSON", "Flask", "OpenAI SDK"],
        "missing": ["опыт интеграций в команде"],
        "match_keywords": ["интеграция", "api", "rest", "python", "flask"],
    },
    {
        "rank": 9,
        "focus": "data",
        "title": "Data / ETL (Junior)",
        "why": "SQLite, JSON, парсинг, атомарная запись, миграции, планировщик.",
        "real_anchors": ["Python", "SQLite", "JSON", "APScheduler"],
        "missing": ["pandas", "Airflow", "PostgreSQL", "оконные функции"],
        "match_keywords": ["etl", "данные", "sqlite", "парсинг", "python"],
    },
    {
        "rank": 10,
        "focus": "general",
        "title": "Junior Python-разработчик / Стажёр",
        "why": "Широкий профиль для нестандартных вакансий и стажировок, включая офис в городе.",
        "real_anchors": ["Python", "Git", "SQLite", "REST API"],
        "missing": ["коммерческий опыт"],
        "match_keywords": ["junior", "стажёр", "стажер", "python", "разработчик"],
    },
]


def load_profile():
    profile = read_json(USER_PROFILE_FILE, None)
    if not isinstance(profile, dict):
        print(f"❌ {USER_PROFILE_FILE.name} не найден. Запусти build_user_profile.py")
        return None
    return profile


def load_trends():
    trends = read_json(MARKET_TRENDS_FILE, None)
    if not isinstance(trends, dict):
        print(f"❌ {MARKET_TRENDS_FILE.name} не найден. Запусти hh_market_analyzer.py")
        return None
    return trends


def profile_summary(profile):
    lines = [
        f"Уровень: {profile.get('level', '')}",
        f"Формат: {', '.join(profile.get('format', []))}",
        f"Зарплата: {profile.get('salary', {}).get('note', '')}",
        f"Опыт в IT: {profile.get('it_experience', '')}",
        f"Навыки: {', '.join(profile.get('hard_skills', []))}",
        f"Софт: {', '.join(profile.get('soft_skills', []))}",
    ]
    for project in profile.get("projects", []):
        lines.append(f"Проект: {project.get('name', '')} — {project.get('result', '')}")
    return "\n".join(lines)


def market_summary(trends):
    titles = ", ".join(item["name"] for item in trends.get("titles", [])[:10])
    skills = ", ".join(item["name"] for item in trends.get("skills", [])[:15])
    pains = "; ".join(item["pain"] for item in trends.get("employer_pains", [])[:5])
    return (
        f"Топ названий: {titles}\n"
        f"Топ навыков: {skills}\n"
        f"Главные боли: {pains}"
    )


def parse_targets_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
        if text.startswith("json"):
            text = text[4:]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Ответ не является JSON-объектом")
    targets = data.get("targets")
    if not isinstance(targets, list):
        raise ValueError("В ответе нет списка targets")
    return targets


def validate_targets(targets):
    result = []
    for index, item in enumerate(targets, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        result.append({
            "rank": item.get("rank", index),
            "focus": str(item.get("focus", f"focus_{index}")).strip(),
            "title": title,
            "why": str(item.get("why", "")).strip(),
            "real_anchors": [str(x).strip() for x in item.get("real_anchors", []) if str(x).strip()],
            "missing": [str(x).strip() for x in item.get("missing", []) if str(x).strip()],
            "match_keywords": [str(x).strip() for x in item.get("match_keywords", []) if str(x).strip()],
        })
    return result


def ask_targets(profile_text, market_text):
    allowed = "\n".join(
        f"- {t['focus']} — {t['title']}" for t in DEFAULT_TARGETS
    )
    prompt = f"""Ты — карьерный консультант. На основе профиля кандидата и анализа рынка отсортируй 10 заданных категорий вакансий по релевантности и уточни формулировки.

ПРОФИЛЬ КАНДИДАТА:
{profile_text}

АНАЛИЗ РЫНКА:
{market_text}

ДОПУСТИМЫЕ КАТЕГОРИИ (значение focus менять нельзя):
{allowed}

Правила:
- Ровно 10 категорий, только из списка выше, без новых направлений.
- rank 1 — самая подходящая категория, rank 10 — самая дальняя.
- title можно уточнить под рынок, но не менять суть категории.
- real_anchors — только навыки, которые реально есть в профиле.
- missing — честно, чего не хватает.
- match_keywords — 5-10 слов для автоотбора вакансий по названию и описанию.
- Не выдумывай опыт и навыки.

Верни строго JSON без markdown:
{{"targets": [{{"rank": 1, "focus": "automation", "title": "...", "why": "...", "real_anchors": ["..."], "missing": ["..."], "match_keywords": ["..."]}}]}}"""
    raw = ask_llm(prompt, temperature=0.2, json_mode=True)
    return validate_targets(parse_targets_json(raw))


def merge_with_defaults(targets):
    """Оставляет только разрешённые категории и добивает список до 10."""
    by_focus = {}
    for item in targets:
        focus = item.get("focus", "")
        if focus in {t["focus"] for t in DEFAULT_TARGETS} and focus not in by_focus:
            by_focus[focus] = item

    result = sorted(by_focus.values(), key=lambda item: item.get("rank", 99))
    for default in DEFAULT_TARGETS:
        if default["focus"] not in by_focus:
            result.append(default)

    for index, item in enumerate(result, start=1):
        item["rank"] = index
    return result[:len(DEFAULT_TARGETS)]


def build_targets():
    profile = load_profile()
    if profile is None:
        return None
    trends = load_trends()
    if trends is None:
        return None

    profile_text = profile_summary(profile)
    market_text = market_summary(trends)

    targets = None
    try:
        targets = ask_targets(profile_text, market_text)
        targets = merge_with_defaults(targets)
        log(f"✅ LLM вернул и отсортировал {len(targets)} категорий")
    except Exception as e:
        log(f"⚠️ Не удалось получить категории от LLM: {e}")

    if len(targets or []) < 10:
        log("   Использую встроенный список категорий")
        targets = DEFAULT_TARGETS

    # Есть ли реальные опоры в профиле — важно не уехать в выдумку.
    profile_skills = {skill.lower() for skill in profile.get("hard_skills", [])}
    for target in targets:
        target["real_anchors"] = [
            anchor for anchor in target.get("real_anchors", [])
            if anchor.lower() in profile_skills
        ]

    return {
        "meta": {
            "created_at": datetime.now().isoformat(),
            "profile_file": USER_PROFILE_FILE.name,
            "trends_file": MARKET_TRENDS_FILE.name,
            "targets_count": len(targets),
        },
        "targets": targets,
    }


def print_summary(data):
    print(f"\n{'=' * 60}")
    print("🎯 ЦЕЛЕВЫЕ КАТЕГОРИИ ВАКАНСИЙ")
    print(f"{'=' * 60}")
    for target in data["targets"]:
        print(f"{target['rank']:>2}. {target['title']}")
        print(f"    Опоры: {', '.join(target['real_anchors'][:5])}")
        print(f"    Не хватает: {', '.join(target['missing'][:3])}")
    print(f"{'=' * 60}")


def main():
    data = build_targets()
    if data is None:
        return 1

    write_json(RESUME_TARGETS_FILE, data)
    print_summary(data)
    log(f"📁 Файл: {RESUME_TARGETS_FILE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
