import json
import os
import sys

from config import CANDIDATE_PROFILE, ask_llm

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ============================================
# НАСТРОЙКИ
# ============================================
BATCH_SIZE = 10
# ============================================

ANALYZER_TEMPERATURE = 0.2


def evaluate_batch(batch):
    vacancies_text = ""
    for i, v in enumerate(batch, start=1):
        vacancies_text += f"\n[{i}] Название: {v['title']}\nКомпания: {v['company']}\nОписание: {v['snippet']}\n"

    prompt = f"""Ты — карьерный ассистент. Оцени вакансии для кандидата.

ПРОФИЛЬ КАНДИДАТА:
{CANDIDATE_PROFILE}

ВАКАНСИИ:
{vacancies_text}

ЗАДАЧА:
Для каждой вакансии верни оценку от 0 до 100 (где 100 — идеальное совпадение) и короткую причину (1 предложение).
ОБРАТИ ОСОБОЕ ВНИМАНИЕ НА УРОВЕНЬ ОПЫТА! Если это Middle/Senior/Lead — оценка должна быть низкой (0-10).

Формат ответа — строго JSON-объект, без лишнего текста:
{{
  "results": [
    {{"index": 1, "score": 85, "reason": "Подходит: Python, автоматизация, junior-уровень"}},
    {{"index": 2, "score": 10, "reason": "Не подходит: Middle+, требуется опыт 3 года"}}
  ]
}}

Только JSON, без markdown-оберток и пояснений.
"""
    return ask_llm(prompt, temperature=ANALYZER_TEMPERATURE, json_mode=True)


def parse_llm_response(text):
    """Достает список оценок из ответа модели, даже если тот обернут в markdown."""
    text = text.strip()
    if text.startswith("```"):
        # ```json ... ``` -> берем содержимое между первым и последним ```
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    if not text:
        raise ValueError("Пустой ответ модели")

    data = json.loads(text)

    if isinstance(data, dict):
        # json-режим возвращает объект: {"results": [...]}
        for key in ("results", "vacancies", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        raise ValueError("В ответе модели нет списка с оценками")

    if isinstance(data, list):
        return data

    raise ValueError("Неожиданный формат ответа модели")


def main():
    if not os.path.exists("vacancies.json"):
        print("❌ Файл vacancies.json не найден.")
        return

    with open("vacancies.json", "r", encoding="utf-8") as f:
        vacancies = json.load(f)

    print(f"📂 Загружено {len(vacancies)} вакансий.")
    print(f"🤖 Отправляю в DeepSeek пачками по {BATCH_SIZE}...\n")

    analyzed = []

    for i in range(0, len(vacancies), BATCH_SIZE):
        batch = vacancies[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(vacancies) + BATCH_SIZE - 1) // BATCH_SIZE

        print(f"📊 Пачка {batch_num}/{total_batches} (вакансии {i+1}-{i+len(batch)})...")

        # Оценки по индексам: даже если модель ответила частично,
        # ни одна вакансия не потеряется.
        scores_by_index = {}
        try:
            raw_response = evaluate_batch(batch)
            for item in parse_llm_response(raw_response):
                if not isinstance(item, dict) or "index" not in item:
                    continue
                try:
                    index = int(item["index"])
                    score = int(item["score"])
                except (TypeError, ValueError):
                    continue
                scores_by_index[index] = {
                    "score": score,
                    "reason": str(item.get("reason", "")).strip(),
                }
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")

        for position, vacancy in enumerate(batch, start=1):
            item = scores_by_index.get(position)
            vacancy = vacancy.copy()
            if item:
                vacancy["score"] = item["score"]
                vacancy["reason"] = item["reason"] or "Без пояснения"
            else:
                vacancy["score"] = -1
                vacancy["reason"] = "Ошибка анализа"
            analyzed.append(vacancy)

        print(f"   ✅ Оценено {len(scores_by_index)} из {len(batch)}")

    analyzed.sort(key=lambda x: x.get("score", 0), reverse=True)

    with open("analyzed_vacancies.json", "w", encoding="utf-8") as f:
        json.dump(analyzed, f, ensure_ascii=False, indent=4)

    top = [v for v in analyzed if v.get("score", 0) >= 70]
    middle = [v for v in analyzed if 40 <= v.get("score", 0) < 70]
    trash = [v for v in analyzed if 0 <= v.get("score", 0) < 40]
    errors = [v for v in analyzed if v.get("score", 0) < 0]

    print(f"\n{'='*50}")
    print(f"✅ АНАЛИЗ ЗАВЕРШЁН")
    print(f"{'='*50}")
    print(f"🔥 Топ (70+):       {len(top)} вакансий")
    print(f"🤔 Средние (40-69): {len(middle)} вакансий")
    print(f"🗑️  Мусор (<40):     {len(trash)} вакансий")
    if errors:
        print(f"⚠️  Не оценено:      {len(errors)} вакансий")
    print(f"\n📁 Файл: analyzed_vacancies.json")

    if not analyzed:
        return

    print(f"\n🏆 ТОП-5 ЛУЧШИХ ВАКАНСИЙ:")
    for v in analyzed[:5]:
        print(f"\n   [{v.get('score')}/100] {v['title']}")
        print(f"   Компания: {v['company']}")
        print(f"   Причина: {v.get('reason')}")


if __name__ == "__main__":
    main()
