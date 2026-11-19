"""Выбор резюме под конкретную вакансию (этап 5).

Детерминированный скоринг без LLM: одно и то же vacancy + generated_resumes.json
всегда дают один и тот же результат, а решение можно объяснить.

Правила:
1. Сильные сигналы в названии вакансии решают категорию
   («telegram» → боты, «QA» → автотесты, «1С/автоматизация» → автоматизация).
2. Если в названии сигналов нет, смотрим описание: категория побеждает,
   только если в описании минимум 2 разных сильных сигнала.
3. Если сигналов нет вообще — фолбэк на general.
4. Фразы из target_titles и match_keywords в generated_resumes.json
   добавляют очки и разбивают ничьи.

Запуск для проверки:
    python hh_resume_selector.py --title "Python-разработчик Telegram-ботов"
    python hh_resume_selector.py --file analyzed_vacancies.json --limit 20
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from paths import CREATED_RESUMES_FILE, GENERATED_RESUMES_FILE
from utils import configure_stdout, read_json

DEFAULT_RESUME_ID = "general"

# Сильные сигналы категории. Проверяются по названию вакансии целиком,
# по описанию — только как «2+ разных сигнала».
STRONG_PATTERNS: dict[str, list[str]] = {
    "qa": [
        r"\bqa\b",
        r"\baqa\b",
        r"тестировщ",
        r"тестирован",
        r"автотест",
        r"quality assurance",
    ],
    "bots": [
        r"telegram",
        r"телеграм",
        r"\bбот(?:а|ы|ов|у|ом|е|ам|ами|ах)?\b",
        r"чат-бот",
        r"chatbot",
    ],
    "parsing": [
        r"парсинг",
        r"парсер",
        r"\bscrap",
        r"сбор данных",
        r"сборщик данных",
    ],
    "ai": [
        r"\bai\b",
        r"\bllm\b",
        r"\bml\b",
        r"\bии\b",
        r"нейросет",
        r"промпт",
        r"genai",
        r"\brag\b",
        r"машинн\w* обучен",
        r"искусственн\w* интеллект",
    ],
    "data": [
        r"data engineer",
        r"\betl\b",
        r"\bdwh\b",
        r"аналитик данных",
        r"\bbi\b",
        r"дата-инженер",
        r"инженер данных",
    ],
    "automation": [
        r"автоматизац",
        r"\brpa\b",
        r"бизнес-процесс",
        r"\b1с\b",
    ],
    "integration": [
        r"интегратор",
        r"интеграц",
        r"\bapi\b",
    ],
    "internal_tools": [
        r"внутренн\w* инструмент",
        r"internal tools",
        r"инструменты для команд",
    ],
    "backend": [
        r"backend",
        r"бэкенд",
        r"fastapi",
        r"django",
        r"flask",
        r"rest api",
    ],
    "general": [],
}

# При равных очках выигрывает более узкая категория.
PRIORITY = [
    "qa",
    "bots",
    "parsing",
    "ai",
    "data",
    "integration",
    "internal_tools",
    "automation",
    "backend",
    "general",
]

TITLE_PHRASE_WEIGHT = 12
DESC_PHRASE_WEIGHT = 2
KEYWORD_TITLE_WEIGHT = 6
KEYWORD_DESC_WEIGHT = 1
MIN_DESC_SIGNALS = 2


def normalize(text: str) -> str:
    """Нижний регистр, ё → е, схлопнутые пробелы."""
    text = (text or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text).strip()


def _matches_any(text: str, patterns: list[str]) -> list[str]:
    """Возвращает сработавшие паттерны (без дублей)."""
    hits = []
    for pattern in patterns:
        if re.search(pattern, text):
            hits.append(pattern)
    return hits


@dataclass
class ResumeChoice:
    resume_id: str
    hash: str
    title: str
    score: int
    reason: str
    is_fallback: bool = False
    scores: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "resume_id": self.resume_id,
            "hash": self.hash,
            "title": self.title,
            "score": self.score,
            "reason": self.reason,
            "is_fallback": self.is_fallback,
            "scores": dict(self.scores),
        }


def _load_resumes(path=None) -> list[dict]:
    data = read_json(path or GENERATED_RESUMES_FILE, None)
    if not isinstance(data, dict) or not isinstance(data.get("resumes"), list):
        raise RuntimeError("generated_resumes.json не найден или повреждён")
    return data["resumes"]


def _load_hashes(path=None) -> dict[str, str]:
    data = read_json(path or CREATED_RESUMES_FILE, {}) or {}
    result = {}
    for rid, info in (data.get("resumes") or {}).items():
        if isinstance(info, dict) and info.get("hash"):
            result[rid] = info["hash"]
    return result


def _phrase_score(resume: dict, title_text: str, desc_text: str) -> tuple[int, list[str]]:
    """Очки по target_titles и match_keywords; возвращает очки и объяснение."""
    score = 0
    reasons = []
    seen = set()

    for phrase in resume.get("target_titles") or []:
        key = normalize(phrase)
        if not key or key in seen:
            continue
        seen.add(key)
        if key in title_text:
            score += TITLE_PHRASE_WEIGHT
            reasons.append(f"должность «{phrase}»")
        elif key in desc_text:
            score += DESC_PHRASE_WEIGHT

    for phrase in resume.get("match_keywords") or []:
        key = normalize(phrase)
        if not key or key in seen:
            continue
        seen.add(key)
        if key in title_text:
            score += KEYWORD_TITLE_WEIGHT
            reasons.append(f"ключ «{phrase}»")
        elif key in desc_text:
            score += KEYWORD_DESC_WEIGHT

    return score, reasons


def choose_resume(
    vacancy: dict,
    resumes: list[dict] | None = None,
    hashes: dict[str, str] | None = None,
) -> ResumeChoice:
    """Выбирает резюме по названию и описанию вакансии."""
    resumes = resumes if resumes is not None else _load_resumes()
    hashes = hashes if hashes is not None else _load_hashes()

    title_text = normalize(vacancy.get("title", ""))
    desc_text = normalize(vacancy.get("description", ""))
    if not desc_text:
        desc_text = normalize(vacancy.get("snippet", ""))

    by_id = {r["id"]: r for r in resumes}
    fallback_id = DEFAULT_RESUME_ID if DEFAULT_RESUME_ID in by_id else next(iter(by_id))

    title_hits: dict[str, list[str]] = {}
    desc_hits: dict[str, list[str]] = {}
    phrase_scores: dict[str, int] = {}
    phrase_reasons: dict[str, list[str]] = {}

    for resume in resumes:
        rid = resume["id"]
        title_hits[rid] = _matches_any(title_text, STRONG_PATTERNS.get(rid, []))
        desc_hits[rid] = _matches_any(desc_text, STRONG_PATTERNS.get(rid, []))
        score, reasons = _phrase_score(resume, title_text, desc_text)
        phrase_scores[rid] = score
        phrase_reasons[rid] = reasons

    # 1. Сильные сигналы в названии.
    candidates = [rid for rid, hits in title_hits.items() if hits]
    source = "название вакансии"

    # 2. Иначе — минимум 2 разных сигнала в описании.
    if not candidates:
        candidates = [
            rid for rid, hits in desc_hits.items() if len(hits) >= MIN_DESC_SIGNALS
        ]
        source = "описание вакансии"

    if not candidates:
        resume = by_id[fallback_id]
        return ResumeChoice(
            resume_id=fallback_id,
            hash=hashes.get(fallback_id, ""),
            title=resume.get("title", ""),
            score=phrase_scores.get(fallback_id, 0),
            reason="нет явных сигналов — фолбэк general",
            is_fallback=True,
            scores=phrase_scores,
        )

    strong_signals = title_hits if source == "название вакансии" else desc_hits

    def sort_key(rid: str):
        return (
            phrase_scores.get(rid, 0),
            len(strong_signals.get(rid, [])),
            -PRIORITY.index(rid) if rid in PRIORITY else -len(PRIORITY),
        )

    best = max(candidates, key=sort_key)
    resume = by_id[best]

    strong = strong_signals[best]
    reason_parts = [f"сигнал в {source}: {', '.join(strong)}"]
    if phrase_reasons.get(best):
        reason_parts.append("; ".join(phrase_reasons[best][:4]))

    return ResumeChoice(
        resume_id=best,
        hash=hashes.get(best, ""),
        title=resume.get("title", ""),
        score=phrase_scores.get(best, 0),
        reason="; ".join(reason_parts),
        is_fallback=False,
        scores=phrase_scores,
    )


def choose_for_vacancy(vacancy: dict) -> ResumeChoice:
    """Удобная обёртка с чтением файлов по умолчанию."""
    return choose_resume(vacancy)


def main():
    configure_stdout(line_buffering=True)
    parser = argparse.ArgumentParser(description="Выбор резюме под вакансию")
    parser.add_argument("--title", default="", help="название вакансии")
    parser.add_argument("--description", default="", help="описание вакансии")
    parser.add_argument("--file", help="JSON со списком вакансий (title/link/description)")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    if args.file:
        data = read_json(Path(args.file), [])
        items = data if isinstance(data, list) else data.get("items", [])
        for vacancy in items[: args.limit]:
            choice = choose_for_vacancy(vacancy)
            print(
                f"{choice.resume_id:15} <- {vacancy.get('title', '')[:60]:60} "
                f"[{choice.score}] {choice.reason[:80]}"
            )
        return

    if not args.title:
        parser.error("нужен --title или --file")

    choice = choose_for_vacancy({"title": args.title, "description": args.description})
    print(json.dumps(choice.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
