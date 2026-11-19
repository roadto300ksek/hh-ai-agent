"""Этап 6 (v2.0): генерация 10 вариантов резюме под целевые категории.

Читает user_real_profile.json, resume_targets.json и market_trends.json,
генерирует по одному резюме на категорию и сохраняет:
- generated_resumes.json — структура для автоотбора;
- resumes.md — готовые тексты для ручного копирования на hh.ru.

Запуск:
    python hh_resume_generator.py
    python hh_resume_generator.py --limit 3   # быстрая проверка
"""
import argparse
import json
import sys
from datetime import datetime

from config import ask_llm
from paths import (
    GENERATED_RESUMES_FILE,
    MARKET_TRENDS_FILE,
    RESUMES_MD_FILE,
    RESUME_TARGETS_FILE,
    USER_PROFILE_FILE,
)
from utils import configure_stdout, log, read_json, write_json

configure_stdout(line_buffering=True)

# ============================================
# НАСТРОЙКИ
# ============================================
MAX_ABOUT_LENGTH = 1000
GENERATION_TEMPERATURE = 0.7
GENERATION_ATTEMPTS = 2
MIN_SKILLS = 3
MAX_SKILLS = 14
MIN_KEYWORDS = 3

SALARY_SUFFIX = " Ожидания: 50–70 тыс. ₽ или по вилке вакансии."
SALARY_MARKERS = ("50–70", "50-70", "50 000", "70 000", "по вилке")


def parse_args():
    parser = argparse.ArgumentParser(description="Генерация вариантов резюме")
    parser.add_argument("--limit", type=int, default=0, help="0 — все категории")
    return parser.parse_args()


def load_inputs():
    profile = read_json(USER_PROFILE_FILE, None)
    targets = read_json(RESUME_TARGETS_FILE, None)
    trends = read_json(MARKET_TRENDS_FILE, None)

    if not isinstance(profile, dict):
        print(f"❌ {USER_PROFILE_FILE.name} не найден. Запусти build_user_profile.py")
        return None
    if not isinstance(targets, dict) or not targets.get("targets"):
        print(f"❌ {RESUME_TARGETS_FILE.name} не найден. Запусти hh_resume_targeter.py")
        return None
    if not isinstance(trends, dict):
        print(f"❌ {MARKET_TRENDS_FILE.name} не найден. Запусти hh_market_analyzer.py")
        return None
    return profile, targets["targets"], trends


def profile_facts_text(profile):
    lines = [
        f"Уровень: {profile.get('level', '')}",
        f"Формат: {', '.join(profile.get('format', []))}",
        f"Зарплата: {profile.get('salary', {}).get('note', '')}",
        f"Опыт в IT: {profile.get('it_experience', '')}",
        f"Общий стаж: {profile.get('total_experience', '')}",
        f"Образование: {profile.get('education', '')}",
        f"Языки: {', '.join(f'{k} — {v}' for k, v in profile.get('languages', {}).items())}",
        f"Навыки: {', '.join(profile.get('hard_skills', []))}",
        f"Софт-скиллы: {', '.join(profile.get('soft_skills', []))}",
    ]
    for project in profile.get("projects", []):
        lines.append(
            f"Проект: {project.get('name', '')}. "
            f"Стек: {', '.join(project.get('stack', []))}. "
            f"Результат: {project.get('result', '')}"
        )
    for job in profile.get("experience", []):
        facts = "; ".join(job.get("facts", []))
        lines.append(f"Опыт (не IT): {job.get('role', '')} ({job.get('period', '')}) — {facts}")
    lines.append(
        "ЗАПРЕЩЕНО: " + ", ".join(profile.get("forbidden_claims", []))
    )
    return "\n".join(lines)


def market_text(trends):
    titles = ", ".join(item["name"] for item in trends.get("titles", [])[:10])
    skills = ", ".join(item["name"] for item in trends.get("skills", [])[:15])
    pains = "; ".join(item["pain"] for item in trends.get("employer_pains", [])[:5])
    return f"Топ названий: {titles}\nТоп навыки: {skills}\nБоли работодателей: {pains}"


def build_prompt(profile_text, target, market):
    anchors = ", ".join(target.get("real_anchors", []))
    missing = ", ".join(target.get("missing", []))
    keywords = ", ".join(target.get("match_keywords", []))
    return f"""Ты — карьерный консультант и технический редактор. Составь один вариант резюме для hh.ru под конкретную категорию вакансий.

ПРОФИЛЬ КАНДИДАТА (можно использовать только эти факты):
{profile_text}

ЦЕЛЕВАЯ КАТЕГОРИЯ:
- Название: {target.get('title', '')}
- Почему подходит: {target.get('why', '')}
- Реальные опоры: {anchors}
- Чего не хватает: {missing}
- Ключевые слова для автоотбора: {keywords}

РЫНОК (используй только для подсветки навыков, которые уже есть в профиле):
{market}

ПРАВИЛА:
- Опыт не выдумывать. Только факты из профиля.
- Навыки — только из списка профиля. Выбери 8–12 самых релевантных категории, не копируй весь список. Порядок — от важного к менее важному.
- about — 700–900 символов, строго не больше 1000. Живым языком, без канцелярита.
- В about обязательно упомяни формат работы (удалёнка/гибрид/офис) и зарплатные ожидания: 50–70 тыс. ₽ или по вилке вакансии.
- Не повторяй дословно один и тот же текст из категории в категорию: меняй акценты и порядок проектов.
- Не используй слова-маркеры ИИ: «уникальный», «богатый опыт», «играет ключевую роль», «демонстрирует», «в заключение», «стоит отметить».
- honest_gaps — 1-2 честных ограничения, если они важны для категории.

Верни строго JSON без markdown:
{{"title": "...", "about": "...", "skills": ["..."], "focus": "{target.get('focus', '')}", "target_titles": ["..."], "match_keywords": ["..."], "honest_gaps": ["..."]}}"""


def parse_resume_json(text):
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
    return data


def normalize_skill_set(skills):
    return {str(skill).strip().lower() for skill in skills if str(skill).strip()}


def shorten_about(text, limit):
    """Обрезает текст по границе предложения, чтобы не рвать мысль."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end >= int(limit * 0.6):
        return cut[: end + 1]
    return cut.rsplit(" ", 1)[0] + "…"


def clean_resume(raw, profile, target, used_titles):
    """Приводит резюме к схеме и убирает выдуманные навыки."""
    issues = []
    profile_skills = normalize_skill_set(profile.get("hard_skills", []))

    title = str(raw.get("title", "")).strip() or target.get("title", "")
    focus = str(raw.get("focus", "") or target.get("focus", "")).strip()

    about = str(raw.get("about", "")).strip()
    if len(about) > MAX_ABOUT_LENGTH:
        about = shorten_about(about, MAX_ABOUT_LENGTH)
        issues.append("about обрезан до 1000 символов")

    # Зарплатные ожидания обязательны: если модель забыла, добавляем сами.
    if not any(marker in about.lower() for marker in SALARY_MARKERS):
        if len(about) + len(SALARY_SUFFIX) > MAX_ABOUT_LENGTH:
            about = shorten_about(about, MAX_ABOUT_LENGTH - len(SALARY_SUFFIX))
        about = about.rstrip() + SALARY_SUFFIX
        issues.append("добавлены зарплатные ожидания")

    skills = []
    for skill in raw.get("skills", []):
        value = str(skill).strip()
        if not value:
            continue
        if value.lower() in profile_skills:
            skills.append(value)
        else:
            issues.append(f"навык «{value}» убран: нет в профиле")
    if len(skills) > MAX_SKILLS:
        skills = skills[:MAX_SKILLS]
        issues.append(f"навыков больше {MAX_SKILLS}: оставлены первые")
    if len(skills) < MIN_SKILLS:
        issues.append(f"навыков меньше {MIN_SKILLS}")

    keywords = [str(k).strip() for k in raw.get("match_keywords", []) if str(k).strip()]
    if len(keywords) < MIN_KEYWORDS:
        keywords = list(target.get("match_keywords", []))[:8]
        issues.append("match_keywords дополнены из целевой категории")

    target_titles = [str(t).strip() for t in raw.get("target_titles", []) if str(t).strip()]
    if not target_titles:
        target_titles = [target.get("title", "")]
        issues.append("target_titles заполнены из целевой категории")

    honest_gaps = [str(g).strip() for g in raw.get("honest_gaps", []) if str(g).strip()]

    if title.lower() in used_titles:
        title = f"{title} ({focus})"
        issues.append("название сделано уникальным")

    return {
        "id": focus or f"resume_{len(used_titles) + 1}",
        "title": title,
        "about": about,
        "skills": skills,
        "focus": focus,
        "target_titles": target_titles[:3],
        "match_keywords": keywords[:10],
        "honest_gaps": honest_gaps[:2],
    }, issues


def check_forbidden(resume, profile):
    forbidden = [str(x).lower() for x in profile.get("forbidden_claims", [])]
    text = " ".join([
        resume["title"],
        resume["about"],
        " ".join(resume["skills"]),
        " ".join(resume["honest_gaps"]),
    ]).lower()
    return [word for word in forbidden if word in text]


def generate_resume(target, profile, profile_text, market, used_titles):
    """Генерирует одно резюме с несколькими попытками."""
    prompt = build_prompt(profile_text, target, market)
    last_issues = []
    best = None

    for attempt in range(1, GENERATION_ATTEMPTS + 1):
        try:
            raw = ask_llm(prompt, temperature=GENERATION_TEMPERATURE, json_mode=True)
            parsed = parse_resume_json(raw)
        except Exception as e:
            log(f"   ⚠️ Попытка {attempt} не удалась: {e}")
            continue

        candidate, issues = clean_resume(parsed, profile, target, used_titles)
        forbidden = check_forbidden(candidate, profile)
        if forbidden:
            issues.append("есть запрещённые утверждения: " + ", ".join(forbidden))

        if not issues:
            return candidate, []
        last_issues = issues
        best = candidate

    if best is None:
        return None, last_issues or ["не удалось получить ответ модели"]
    return best, last_issues


def render_markdown(data):
    lines = [
        "# Сгенерированные резюме (v2.0)",
        "",
        f"Дата: {data['meta'].get('created_at', '')}",
        f"Профиль: {data['meta'].get('profile_file', '')}",
        f"Категорий: {len(data['resumes'])}",
        "",
        "---",
        "",
    ]
    for resume in data["resumes"]:
        lines.append(f"## {resume['title']}")
        lines.append("")
        lines.append(f"**Фокус:** {resume['focus']}")
        lines.append("")
        lines.append("### О себе")
        lines.append("")
        lines.append(resume["about"])
        lines.append("")
        lines.append("### Навыки")
        lines.append("")
        lines.append(", ".join(resume["skills"]))
        lines.append("")
        lines.append("### Подходит под вакансии")
        lines.append("")
        lines.append(", ".join(resume["target_titles"]))
        lines.append("")
        if resume.get("honest_gaps"):
            lines.append("### Честные ограничения")
            lines.append("")
            for gap in resume["honest_gaps"]:
                lines.append(f"- {gap}")
            lines.append("")
        lines.append(f"**match_keywords:** {', '.join(resume['match_keywords'])}")
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def print_summary(data, all_issues):
    print(f"\n{'=' * 60}")
    print("📄 СГЕНЕРИРОВАННЫЕ РЕЗЮМЕ")
    print(f"{'=' * 60}")
    for resume in data["resumes"]:
        print(f"• {resume['title']}")
        print(f"  Навыки: {', '.join(resume['skills'][:6])}")
    if all_issues:
        print("\n⚠️ Замечания:")
        for note in all_issues:
            print(f"  - {note}")
    print(f"{'=' * 60}")


def main():
    args = parse_args()
    loaded = load_inputs()
    if loaded is None:
        return 1
    profile, targets, trends = loaded

    if args.limit > 0:
        targets = targets[:args.limit]

    profile_text = profile_facts_text(profile)
    market = market_text(trends)

    resumes = []
    all_issues = []
    used_titles = set()
    for target in targets:
        log(f"✍️  {target.get('title', '')}")
        resume, issues = generate_resume(target, profile, profile_text, market, used_titles)
        if resume is None:
            log(f"   ❌ Не удалось сгенерировать: {issues}")
            all_issues.append(f"{target.get('title', '')}: {', '.join(issues)}")
            continue
        resumes.append(resume)
        used_titles.add(resume["title"].lower())
        for issue in issues:
            all_issues.append(f"{resume['title']}: {issue}")

    if not resumes:
        print("❌ Ни одного резюме не сгенерировано.")
        return 1

    data = {
        "meta": {
            "created_at": datetime.now().isoformat(),
            "profile_file": USER_PROFILE_FILE.name,
            "targets_file": RESUME_TARGETS_FILE.name,
            "trends_file": MARKET_TRENDS_FILE.name,
            "resumes_count": len(resumes),
        },
        "resumes": resumes,
    }
    write_json(GENERATED_RESUMES_FILE, data)

    with open(RESUMES_MD_FILE, "w", encoding="utf-8") as f:
        f.write(render_markdown(data))

    print_summary(data, all_issues)
    log(f"📁 Файл: {GENERATED_RESUMES_FILE.name}")
    log(f"📁 Файл: {RESUMES_MD_FILE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
