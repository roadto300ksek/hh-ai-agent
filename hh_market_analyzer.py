"""Этап 3 (v2.0): анализ рынка по полным описаниям вакансий.

Читает vacancy_details.json (или vacancies.json как fallback), разбивает
на батчи и через LLM извлекает названия должностей, навыки, софт-требования
и боли работодателей. Затем агрегирует частоты и сохраняет market_trends.json.

Запуск:
    python hh_market_analyzer.py
    python hh_market_analyzer.py --batch-size 15
"""
import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime

from config import ask_llm
from paths import (
    MARKET_TRENDS_FILE,
    VACANCIES_FILE,
    VACANCY_DETAILS_FILE,
)
from utils import configure_stdout, log, read_json, write_json

configure_stdout(line_buffering=True)

# ============================================
# НАСТРОЙКИ
# ============================================
BATCH_SIZE = 20
TOP_TITLES = 15
TOP_SKILLS = 20
TOP_SOFT = 15
TOP_PAIN = 5
MAX_DESCRIPTION_CHARS = 3000

# Канонические имена для частых вариантов написания.
SKILL_ALIASES = {
    "python": "Python",
    "python3": "Python",
    "питон": "Python",
    "python2": "Python 2",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "django rest framework": "Django REST Framework",
    "drf": "Django REST Framework",
    "aiogram": "aiogram",
    "aiogram 3": "aiogram",
    "aiogram2": "aiogram",
    "python-telegram-bot": "python-telegram-bot",
    "telegram bot api": "Telegram Bot API",
    "playwright": "Playwright",
    "selenium": "Selenium",
    "scrapy": "Scrapy",
    "beautifulsoup": "BeautifulSoup",
    "requests": "Requests",
    "aiohttp": "aiohttp",
    "asyncio": "asyncio",
    "openai": "OpenAI API",
    "openai sdk": "OpenAI SDK",
    "deepseek": "DeepSeek API",
    "deepseek api": "DeepSeek API",
    "llm": "LLM",
    "rest": "REST API",
    "rest api": "REST API",
    "restful": "REST API",
    "json": "JSON",
    "api": "API",
    "sql": "SQL",
    "sqlite": "SQLite",
    "sqlite3": "SQLite",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "psql": "PostgreSQL",
    "mysql": "MySQL",
    "redis": "Redis",
    "rabbitmq": "RabbitMQ",
    "celery": "Celery",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "git": "Git",
    "github": "GitHub",
    "gitlab": "GitLab",
    "linux": "Linux",
    "streamlit": "Streamlit",
    "apscheduler": "APScheduler",
    "unittest": "unittest",
    "pytest": "pytest",
    "pandas": "pandas",
    "numpy": "numpy",
    "scikit-learn": "scikit-learn",
    "machine learning": "Machine Learning",
    "ml": "Machine Learning",
    "airflow": "Airflow",
    "etl": "ETL",
    "ci/cd": "CI/CD",
    "jenkins": "Jenkins",
    "pytest-playwright": "pytest-playwright",
    "beautiful soup": "BeautifulSoup",
    "html": "HTML",
    "css": "CSS",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "typescript": "TypeScript",
    "react": "React",
    "vue": "Vue",
    "django orm": "Django ORM",
    "sqlalchemy": "SQLAlchemy",
    "aiosqlite": "aiosqlite",
    "streamlit dashboard": "Streamlit",
}

# Слова, которые не являются навыками сами по себе.
GENERIC_SKILL_WORDS = {
    "опыт", "знание", "умение", "навык", "навыки", "работа", "разработка",
    "понимание", "принцип", "подход", "база", "качество", "задача", "задачи",
    "команда", "коллектив", "ответственность", "график", "оформление",
    "занятость", "английский", "русский", "язык", "языки", "грамотная",
    "речь", "коммуникация", "коммуникабельность", "пользователь", "клиент",
    "документация", "отчётность", "отчетность", "планирование",
    "саморазвитие", "дисциплина", "стрессоустойчивость", "инициативность",
    "внимательность", "аккуратность", "мобильность", "готовность", "желание",
    "плюсом", "будет", "желательно", "требования", "обязанности", "условия",
    "проект", "проекты", "продукта", "продукт", "бизнес", "процессы",
    "решение", "решения", "участие", "умение работать", "навык работы",
    "командная работа", "работа в команде", "самостоятельность",
}

LEVEL_WORDS = ("junior", "middle", "senior", "lead", "стажер", "стажёр", "intern")

# Аббревиатуры, которые нельзя приводить к «Заглавная + строчные».
TITLE_CASE_MAP = {
    "ai": "AI", "api": "API", "it": "IT", "qa": "QA", "ml": "ML",
    "rpa": "RPA", "etl": "ETL", "devops": "DevOps", "sql": "SQL",
    "crm": "CRM", "erp": "ERP", "bi": "BI", "ui": "UI", "ux": "UX",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Анализ рынка вакансий")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Сколько вакансий анализировать (0 — все). Удобно для быстрой проверки.",
    )
    return parser.parse_args()


def parse_json_payload(text):
    """Достаёт JSON-объект из ответа модели, даже если он обёрнут в markdown."""
    text = (text or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    if not text:
        raise ValueError("Пустой ответ модели")

    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Ответ модели не является JSON-объектом")
    return data


def parse_batch_json(text):
    data = parse_json_payload(text)

    result = {"titles": [], "skills": [], "soft": [], "pains": []}
    for key in result:
        value = data.get(key, [])
        if isinstance(value, list):
            result[key] = [str(item).strip() for item in value if str(item).strip()]
    return result


def canonical_skill(raw):
    """Приводит варианты написания навыка к одному имени."""
    key = raw.strip().lower().replace("ё", "е")
    key = re.sub(r"\s+", " ", key)
    key = key.strip(" .,:;()[]")

    if key in SKILL_ALIASES:
        return SKILL_ALIASES[key]
    if key in GENERIC_SKILL_WORDS:
        return ""

    for suffix in (" опыт", " знание", " навык", " технология", " работа"):
        if key.endswith(suffix):
            key = key[: -len(suffix)].strip()
            break

    if key in SKILL_ALIASES:
        return SKILL_ALIASES[key]
    if key in GENERIC_SKILL_WORDS or len(key) < 2:
        return ""

    return key[:1].upper() + key[1:]


def normalize_title(raw):
    """Убирает уровень и пунктуацию, чтобы считать частоту названий."""
    text = raw.strip().lower().replace("ё", "е")
    # Дефис сохраняем: «Python-разработчик» и «Python разработчик» — разные названия.
    text = re.sub(r"[^a-zа-яе0-9\s+-]", " ", text)
    for word in LEVEL_WORDS:
        text = re.sub(rf"\b{word}\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    # Восстанавливаем регистр аббревиатур (ai → AI, qa → QA).
    text = re.sub(
        r"[a-zа-я0-9+]+",
        lambda match: TITLE_CASE_MAP.get(match.group(0), match.group(0)),
        text,
    )
    return text[:1].upper() + text[1:]


def normalize_phrase(raw):
    text = raw.strip().lower().replace("ё", "е")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,:;()")


def aggregate(items, normalizer):
    counter = Counter()
    for item in items:
        key = normalizer(item)
        if key:
            counter[key] += 1
    return counter


def with_share(counter, total, limit):
    result = []
    for name, count in counter.most_common(limit):
        result.append({
            "name": name,
            "count": count,
            "share": round(count / total, 3) if total else 0.0,
        })
    return result


def build_batch_prompt(batch):
    lines = []
    for index, vacancy in enumerate(batch, start=1):
        description = (
            vacancy.get("description")
            or vacancy.get("snippet")
            or ""
        )[:MAX_DESCRIPTION_CHARS]
        lines.append(
            f"[{index}] Должность: {vacancy.get('title', '')}\n"
            f"Компания: {vacancy.get('company', '')}\n"
            f"Описание: {description}"
        )

    return f"""Ты — HR-аналитик IT-рынка. Проанализируй вакансии и извлеки из описаний:
- titles: канонические названия должностей без уровней (например, "Python-разработчик", "Backend-разработчик", "Инженер автоматизации");
- skills: технологии, библиотеки, фреймворки и инструменты, которые прямо указаны в описании;
- soft: софт-требования и условия работы (удалёнка, гибкий график, английский язык, командная работа и т.п.);
- pains: проблемы работодателя, которые он хочет решить (короткие фразы).

Правила:
- Только то, что реально есть в текстах. Ничего не выдумывай.
- Названия должностей приводи к одной форме, без "Junior/Middle/Senior".
- Навыки — конкретные технологии, а не общие слова.
- На одну вакансию может приходиться несколько навыков и несколько болей.

Верни строго JSON без markdown и пояснений:
{{"titles": ["..."], "skills": ["..."], "soft": ["..."], "pains": ["..."]}}

ВАКАНСИИ:
{chr(10).join(lines)}"""


def analyze_batch(batch):
    raw = ask_llm(build_batch_prompt(batch), temperature=0.1, json_mode=True)
    return parse_batch_json(raw)


def cluster_titles(title_counter, total):
    """Финальный проход: группирует близкие названия должностей."""
    top = title_counter.most_common(40)
    if not top:
        return []

    lines = "\n".join(f"- {name} ({count})" for name, count in top)
    prompt = f"""Ты — HR-аналитик. Вот названия должностей из вакансий с частотой:
{lines}

Выдели {TOP_TITLES} главных названий, объединив близкие по смыслу (например, «Python-разработчик» и «Разработчик Python»).
Сохрани примерную суммарную частоту.
Верни строго JSON без markdown:
{{"titles": [{{"title": "...", "count": 42}}]}}"""
    try:
        raw = ask_llm(prompt, temperature=0.1, json_mode=True)
        data = parse_json_payload(raw)
        result = []
        for item in data.get("titles", []):
            if isinstance(item, dict) and item.get("title"):
                name = str(item["title"]).strip()
                count = int(item.get("count", 0) or 0)
                result.append({
                    "name": name,
                    "count": count,
                    "share": round(count / total, 3) if total else 0.0,
                })
        if result:
            return result[:TOP_TITLES]
    except Exception as e:
        log(f"   ⚠️ Не удалось кластеризовать названия: {e}")

    return with_share(title_counter, total, TOP_TITLES)


def cluster_pains(pain_counter):
    """Финальный проход: группирует близкие боли в 5 главных."""
    top = pain_counter.most_common(30)
    if not top:
        return []

    lines = "\n".join(f"- {name} ({count})" for name, count in top)
    prompt = f"""Ты — HR-аналитик. Вот проблемы работодателей из вакансий с частотой:
{lines}

Выдели {TOP_PAIN} главных болей, объединив близкие по смыслу. Сохрани примерную суммарную частоту.
Верни строго JSON без markdown:
{{"pains": [{{"pain": "...", "count": 42}}]}}"""
    try:
        raw = ask_llm(prompt, temperature=0.1, json_mode=True)
        data = parse_json_payload(raw)
        result = []
        for item in data.get("pains", []):
            if isinstance(item, dict) and item.get("pain"):
                result.append({
                    "pain": str(item["pain"]).strip(),
                    "count": int(item.get("count", 0) or 0),
                })
        if result:
            return result[:TOP_PAIN]
    except Exception as e:
        log(f"   ⚠️ Не удалось кластеризовать боли: {e}")

    return [
        {"pain": name, "count": count}
        for name, count in top[:TOP_PAIN]
    ]


def load_vacancies():
    details = read_json(VACANCY_DETAILS_FILE, None)
    if isinstance(details, dict) and isinstance(details.get("items"), list):
        items = [item for item in details["items"] if isinstance(item, dict)]
        if items:
            log(f"📁 Использую {VACANCY_DETAILS_FILE.name}: {len(items)} полных описаний")
            return items, "vacancy_details.json"

    vacancies = read_json(VACANCIES_FILE, [])
    if isinstance(vacancies, list):
        items = [item for item in vacancies if isinstance(item, dict)]
        if items:
            log(f"⚠️ {VACANCY_DETAILS_FILE.name} не найден. Использую {VACANCIES_FILE.name} (только сниппеты).")
            return items, "vacancies.json"
    return [], None


def build_trends(batch_size, limit=0):
    items, source_name = load_vacancies()
    if not items:
        print("❌ Нет данных. Сначала запусти hh_scanner_multi.py и hh_details_collector.py")
        return None

    if limit > 0:
        items = items[:limit]
    total = len(items)
    log(f"📊 Анализирую {total} вакансий из {source_name} батчами по {batch_size}")

    titles, skills, soft, pains = [], [], [], []
    for start in range(0, total, batch_size):
        batch = items[start:start + batch_size]
        number = start // batch_size + 1
        log(f"   🔍 Батч {number}: {len(batch)} вакансий")
        try:
            parsed = analyze_batch(batch)
        except Exception as e:
            log(f"   ⚠️ Батч {number} пропущен: {e}")
            continue
        titles.extend(parsed["titles"])
        skills.extend(parsed["skills"])
        soft.extend(parsed["soft"])
        pains.extend(parsed["pains"])

    title_counter = aggregate(titles, normalize_title)
    skill_counter = aggregate(skills, canonical_skill)
    soft_counter = aggregate(soft, normalize_phrase)
    pain_counter = aggregate(pains, normalize_phrase)

    trends = {
        "meta": {
            "created_at": datetime.now().isoformat(),
            "source_file": source_name,
            "vacancies_count": total,
            "titles_found": sum(title_counter.values()),
            "skills_found": sum(skill_counter.values()),
        },
        "titles": cluster_titles(title_counter, total),
        "skills": with_share(skill_counter, total, TOP_SKILLS),
        "soft_requirements": with_share(soft_counter, total, TOP_SOFT),
        "employer_pains": cluster_pains(pain_counter),
    }
    return trends


def print_summary(trends):
    print(f"\n{'=' * 60}")
    print("📊 РЕЗУЛЬТАТЫ АНАЛИЗА РЫНКА")
    print(f"{'=' * 60}")
    print(f"Вакансий: {trends['meta']['vacancies_count']}")

    print("\n🏷️  Топ названий должностей:")
    for item in trends["titles"][:10]:
        print(f"   {item['count']:>4}  {item['name']}")

    print("\n🛠️  Топ навыков:")
    for item in trends["skills"][:10]:
        print(f"   {item['count']:>4}  {item['name']}")

    print("\n💬 Софт-требования:")
    for item in trends["soft_requirements"][:8]:
        print(f"   {item['count']:>4}  {item['name']}")

    print("\n💡 Главные боли работодателей:")
    for item in trends["employer_pains"]:
        print(f"   {item['count']:>4}  {item['pain']}")
    print(f"{'=' * 60}")


def main():
    args = parse_args()
    trends = build_trends(args.batch_size, args.limit)
    if trends is None:
        return 1

    write_json(MARKET_TRENDS_FILE, trends)
    print_summary(trends)
    log(f"📁 Файл: {MARKET_TRENDS_FILE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
