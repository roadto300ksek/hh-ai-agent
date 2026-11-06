import json

from config import CANDIDATE_PROFILE, ask_llm
from paths import ANALYZED_FILE, VACANCIES_FILE
from utils import clamp, configure_stdout, try_read_json, write_json

configure_stdout()

# ============================================
# НАСТРОЙКИ
# ============================================
BATCH_SIZE = 10
ANALYZER_TEMPERATURE = 0.2
MIN_REASON_LENGTH = 3
MAX_REASON_LENGTH = 300
# ============================================


def evaluate_batch(batch):
    vacancies_text = ""
    for i, v in enumerate(batch, start=1):
        vacancies_text += (
            f"\n[{i}] Название: {v.get('title', 'без названия')}\n"
            f"Компания: {v.get('company', 'не указана')}\n"
            f"Описание: {v.get('snippet', '')}\n"
        )

    prompt = f"""Ты — карьерный ассистент. Оцени вакансии для кандидата.

ПРОФИЛЬ КАНДИДАТА:
{CANDIDATE_PROFILE}

ВАКАНСИИ:
{vacancies_text}

ЗАДАЧА:
Для каждой вакансии верни оценку от 0 до 100 (где 100 — идеальное совпадение) и короткую причину (1 предложение).
ОБРАТИ ОСОБОЕ ВНИМАНИЕ НА УРОВЕНЬ ОПЫТА! Junior и Junior+ подходят, стажёр тоже. Если Middle/Senior/Lead — оценка 0-10.

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


def normalize_scores(items):
    """Приводит ответ модели к {index: {score, reason}} и отбрасывает мусор."""
    result = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item["index"])
            score = clamp(int(item["score"]))
        except (KeyError, TypeError, ValueError):
            continue
        reason = str(item.get("reason", "")).strip()
        if len(reason) < MIN_REASON_LENGTH:
            reason = "Без пояснения"
        result[index] = {"score": score, "reason": reason[:MAX_REASON_LENGTH]}
    return result


def analyze(vacancies, batch_size=BATCH_SIZE):
    """Оценивает вакансии. Ошибка пачки не теряет вакансии: они получают score=-1."""
    analyzed = []
    total_batches = (len(vacancies) + batch_size - 1) // batch_size

    for number, start in enumerate(range(0, len(vacancies), batch_size), start=1):
        batch = vacancies[start:start + batch_size]
        print(f"📊 Пачка {number}/{total_batches} (вакансии {start + 1}-{start + len(batch)})...")

        scores_by_index = {}
        try:
            raw_response = evaluate_batch(batch)
            scores_by_index = normalize_scores(parse_llm_response(raw_response))
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")

        for position, vacancy in enumerate(batch, start=1):
            item = scores_by_index.get(position)
            vacancy = dict(vacancy)
            if item:
                vacancy["score"] = item["score"]
                vacancy["reason"] = item["reason"]
            else:
                vacancy["score"] = -1
                vacancy["reason"] = "Ошибка анализа"
            analyzed.append(vacancy)

        print(f"   ✅ Оценено {len(scores_by_index)} из {len(batch)}")

    return analyzed


def main():
    vacancies = try_read_json(VACANCIES_FILE, None)
    if vacancies is None:
        print("❌ Файл vacancies.json не найден или поврежден.")
        return
    if not isinstance(vacancies, list) or not vacancies:
        print("❌ vacancies.json пуст. Сначала запусти сканер.")
        return

    print(f"📂 Загружено {len(vacancies)} вакансий.")
    print(f"🤖 Отправляю в DeepSeek пачками по {BATCH_SIZE}...\n")

    analyzed = analyze(vacancies)
    analyzed.sort(key=lambda x: x.get("score", 0), reverse=True)

    top = [v for v in analyzed if v.get("score", 0) >= 70]
    middle = [v for v in analyzed if 40 <= v.get("score", 0) < 70]
    trash = [v for v in analyzed if 0 <= v.get("score", 0) < 40]
    errors = [v for v in analyzed if v.get("score", 0) < 0]

    if not top and not middle and not trash:
        print("\n⚠️ Ни одной вакансии не удалось оценить. Старый analyzed_vacancies.json сохранен.")
        return

    write_json(ANALYZED_FILE, analyzed)

    print(f"\n{'='*50}")
    print("✅ АНАЛИЗ ЗАВЕРШЁН")
    print(f"{'='*50}")
    print(f"🔥 Топ (70+):       {len(top)} вакансий")
    print(f"🤔 Средние (40-69): {len(middle)} вакансий")
    print(f"🗑️  Мусор (<40):     {len(trash)} вакансий")
    if errors:
        print(f"⚠️  Не оценено:      {len(errors)} вакансий")
    print(f"\n📁 Файл: {ANALYZED_FILE.name}")

    print("\n🏆 ТОП-5 ЛУЧШИХ ВАКАНСИЙ:")
    for v in analyzed[:5]:
        print(f"\n   [{v.get('score')}/100] {v.get('title', 'без названия')}")
        print(f"   Компания: {v.get('company', 'не указана')}")
        print(f"   Причина: {v.get('reason')}")


if __name__ == "__main__":
    main()
