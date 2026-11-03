import json
import time
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# ============================================
# НАСТРОЙКИ
# ============================================
BATCH_SIZE = 10
SLEEP_BETWEEN_BATCHES = 3
# ============================================

# Профиль кандидата с жестким фильтром на Junior
CANDIDATE_PROFILE = """
Кандидат: начинающий Python-разработчик (Junior/Стажер/Intern), хочет работать в сфере автоматизации бизнес-процессов и AI-агентов.
Навыки: Python, Playwright, OpenAI SDK, REST API, JSON, парсинг данных, работа с cookies/сессиями.
Желаемая роль: Junior Python-разработчик, AI-инженер (Junior), RPA-разработчик (Junior), Стажер.

ГЕОГРАФИЯ И ФОРМАТ РАБОТЫ:
- Идеально: удалённая работа.
- Хорошо: гибрид или офис в <ГОРОД>е.
- Плохо: офис/гибрид в других городах без возможности удалёнки.

ВАЖНО (УРОВЕНЬ ОПЫТА):
- Ищем СТРОГО Junior, Intern, стажер, без опыта или с опытом 1 год.
- Если в вакансии написано "Middle", "Middle+", "Senior", "Lead" или требуется опыт "от 2-3 лет", "3-6 лет" — ставь оценку 0-10.
- Если требуется опыт "1-3 года" — оценивай внимательно, если стек совпадает, можешь поставить 40-60.

НЕ подходят: 1С-разработка, Java, C++, PHP, менеджеры по продажам, преподаватели, вакансии без Python.
"""

client = OpenAI(
    base_url="https://api.deepseek.com",
    api_key=DEEPSEEK_API_KEY,
)


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

Формат ответа — строго JSON-массив, без лишнего текста:
[
  {{"index": 1, "score": 85, "reason": "Подходит: Python, автоматизация, junior-уровень"}},
  {{"index": 2, "score": 10, "reason": "Не подходит: Middle+, требуется опыт 3 года"}}
]

Только JSON, без markdown-оберток и пояснений.
"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def parse_llm_response(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    return json.loads(text)


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

        try:
            raw_response = evaluate_batch(batch)
            scores = parse_llm_response(raw_response)

            for item in scores:
                idx = item["index"] - 1
                if 0 <= idx < len(batch):
                    vacancy = batch[idx].copy()
                    vacancy["score"] = item["score"]
                    vacancy["reason"] = item["reason"]
                    analyzed.append(vacancy)
            print(f"   ✅ Обработано {len(scores)} вакансий")
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")
            for v in batch:
                v_copy = v.copy()
                v_copy["score"] = -1
                v_copy["reason"] = "Ошибка анализа"
                analyzed.append(v_copy)

        time.sleep(SLEEP_BETWEEN_BATCHES)

    analyzed.sort(key=lambda x: x.get("score", 0), reverse=True)

    with open("analyzed_vacancies.json", "w", encoding="utf-8") as f:
        json.dump(analyzed, f, ensure_ascii=False, indent=4)

    top = [v for v in analyzed if v.get("score", 0) >= 70]
    middle = [v for v in analyzed if 40 <= v.get("score", 0) < 70]
    trash = [v for v in analyzed if v.get("score", 0) < 40]

    print(f"\n{'='*50}")
    print(f"✅ АНАЛИЗ ЗАВЕРШЁН")
    print(f"{'='*50}")
    print(f"🔥 Топ (70+):       {len(top)} вакансий")
    print(f"🤔 Средние (40-69): {len(middle)} вакансий")
    print(f"🗑️  Мусор (<40):     {len(trash)} вакансий")
    print(f"\n📁 Файл: analyzed_vacancies.json")

    print(f"\n🏆 ТОП-5 ЛУЧШИХ ВАКАНСИЙ:")
    for v in analyzed[:5]:
        print(f"\n   [{v.get('score')}/100] {v['title']}")
        print(f"   Компания: {v['company']}")
        print(f"   Причина: {v.get('reason')}")


if __name__ == "__main__":
    main()