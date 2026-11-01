import json
import time
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()  # Загружает переменные из .env
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
BATCH_SIZE = 10               # Сколько вакансий отправлять за один запрос к LLM
SLEEP_BETWEEN_BATCHES = 3     # Пауза между запросами (чтобы не словить rate limit)
# ============================================

# Профиль кандидата — под него будем оценивать вакансии
CANDIDATE_PROFILE = """
Кандидат: начинающий Python-разработчик, хочет работать в сфере автоматизации бизнес-процессов и AI-агентов.
Навыки: Python, Playwright (автоматизация браузера), OpenAI SDK (работа с LLM), REST API, JSON, парсинг данных, работа с cookies/сессиями.
Желаемая роль: Junior/Middle Python-разработчик (автоматизация), AI-инженер, RPA-разработчик, специалист по автоматизации бизнес-процессов.

ГЕОГРАФИЯ И ФОРМАТ РАБОТЫ:
- Идеально: удалённая работа (можно из любого города).
- Хорошо: гибрид или офис в <ГОРОД>е или <ГОРОД>ой области.
- Плохо: офис/гибрид в других городах (Москва, Питер и т.д.) без возможности удалёнки.

НЕ подходят: 1С-разработка, Java, C++, PHP, Senior-позиции, менеджеры по продажам, преподаватели, вакансии без Python, офис/гибрид в других регионах без удалёнки.

ШКАЛА ОЦЕНОК:
- 80-100: удалёнка + Python + автоматизация.
- 60-79: гибрид/офис в <ГОРОД>е + Python + автоматизация, либо удалёнка с частичным совпадением.
- 40-59: удалёнка, но стек совпадает частично, либо офис в <ГОРОД>е без автоматизации.
- 0-39: офис/гибрид в другом городе без удалёнки, или не тот стек, или не тот уровень.
"""

client = OpenAI(
    base_url="https://api.deepseek.com",
    api_key=DEEPSEEK_API_KEY,
)


def evaluate_batch(batch):
    """Отправляет пачку вакансий в DeepSeek и получает оценки."""
    # Формируем список вакансий для промпта
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
Формат ответа — строго JSON-массив, без лишнего текста:
[
  {{"index": 1, "score": 85, "reason": "Подходит: Python, автоматизация, junior-уровень"}},
  {{"index": 2, "score": 10, "reason": "Не подходит: 1С, нет Python"}}
]

Только JSON, без markdown-обёрток и пояснений.
"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def parse_llm_response(text):
    """Достаёт JSON из ответа LLM, даже если он обёрнут в ```json ... ```."""
    text = text.strip()
    if text.startswith("```"):
        # Убираем markdown-обёртку
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    return json.loads(text)


def main():
    # Загружаем собранные вакансии
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

            # Сопоставляем оценки с вакансиями
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
            # Если пачка упала — сохраняем её без оценок
            for v in batch:
                v_copy = v.copy()
                v_copy["score"] = -1
                v_copy["reason"] = "Ошибка анализа"
                analyzed.append(v_copy)

        # Пауза между пачками
        time.sleep(SLEEP_BETWEEN_BATCHES)

    # Сортируем по убыванию оценки
    analyzed.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Сохраняем результат
    with open("analyzed_vacancies.json", "w", encoding="utf-8") as f:
        json.dump(analyzed, f, ensure_ascii=False, indent=4)

    # Считаем статистику
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
        print(f"   Ссылка: {v['link']}")


if __name__ == "__main__":
    main()