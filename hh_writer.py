import json
import time
import os
from openai import OpenAI

# ============================================
# НАСТРОЙКИ
# ============================================
DEEPSEEK_API_KEY = "ВАШ_КЛЮЧ_ЗДЕСЬ"  # ВСТАВЬ СЮДА СВОЙ КЛЮЧ ОТ DEEPSEEK
TOP_N = 10                    # Сколько лучших вакансий обрабатываем
SLEEP_BETWEEN = 3             # Пауза между запросами (секунды)
# ============================================

CANDIDATE_INFO = """
Имя: <ИМЯ>
Город: <ГОРОД>
Формат работы: удалёнка (приоритет) или гибрид/офис в <ГОРОД>е
Резюме: Python-разработчик, специализация — автоматизация бизнес-процессов и AI-агенты.

Опыт и навыки:
- Python (основной язык)
- Playwright (автоматизация браузера, обход антибот-защиты, парсинг)
- OpenAI SDK / DeepSeek API (интеграция LLM в продукты)
- REST API, JSON, работа с cookies/сессиями
- Git, Flask

Пет-проекты:
1. Telegram-бот для изучения иностранных языков (Python, OpenAI API, Flask, gTTS, Git).
2. Мультиагентная система для автоматизации поиска работы на HeadHunter (Python, Playwright, LLM, REST API).

Тон письма: уверенный, но без пафоса. Деловой, живой, без штампов типа "стрессоустойчивый" и "командный игрок".
"""

client = OpenAI(
    base_url="https://api.deepseek.com",
    api_key=DEEPSEEK_API_KEY,
)

LOG_FILE = "sent_log.json"


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def generate_letter(vacancy):
    """Генерирует сопроводительное письмо под конкретную вакансию."""
    prompt = f"""Ты — опытный карьерный консультант. Напиши короткое сопроводительное письмо для отклика на вакансию.

ИНФОРМАЦИЯ О КАНДИДАТЕ:
{CANDIDATE_INFO}

ВАКАНСИЯ:
Название: {vacancy['title']}
Компания: {vacancy['company']}
Описание: {vacancy['snippet']}

ТРЕБОВАНИЯ К ПИСЬМУ:
- Длина: 4-6 предложений (не больше!).
- НЕ начинать с обращения по названию компании. Название компании может быть неудачным, длинным или странным — не упоминай его в начале.
- Начать можно с фразы "Здравствуйте!" или сразу с сути (например, "Меня заинтересовала вакансия...").
- В первых двух предложениях — зацепка: почему кандидат подходит именно под эту вакансию.
- Упомянуть конкретные релевантные навыки из описания вакансии.
- НЕ использовать шаблонные фразы ("стрессоустойчивый", "командный игрок", "быстро обучаюсь").
- НЕ пересказывать резюме целиком — только 1-2 ключевых факта.
- Тон: уверенный, живой, деловой.
- В конце — готовность обсудить детали.
- НЕ выдумывать опыт, которого нет.
- НЕ писать "Уважаемая компания" или "Дорогая команда".
- В письме НЕ упоминать название компании вообще (ни в начале, ни в середине).

Верни ТОЛЬКО текст письма, без пояснений и без markdown.
"""
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


def main():
    # Загружаем проанализированные вакансии
    if not os.path.exists("analyzed_vacancies.json"):
        print("❌ Файл analyzed_vacancies.json не найден. Сначала запусти hh_analyzer.py")
        return

    with open("analyzed_vacancies.json", "r", encoding="utf-8") as f:
        all_vacancies = json.load(f)

    # Загружаем список уже отправленных
    sent_log = load_json(LOG_FILE, {"sent_links": [], "history": []})
    already_sent = set(sent_log.get("sent_links", []))

    print(f"📂 Всего вакансий в базе: {len(all_vacancies)}")
    print(f"📤 Уже отправлено откликов: {len(already_sent)}")

    # Фильтруем: топ с оценкой >= 70, исключая уже отправленные
    top_vacancies = [
        v for v in all_vacancies
        if v.get("score", 0) >= 70 and v.get("link") not in already_sent
    ][:TOP_N]

    if not top_vacancies:
        print("🎉 Нет новых вакансий для генерации писем. Все топовые уже отработаны.")
        return

    print(f"🔥 Новых топовых вакансий (70+): {len(top_vacancies)}")
    print(f"✍️  Генерирую письма...\n")

    results = []

    for i, vacancy in enumerate(top_vacancies, start=1):
        print(f"[{i}/{len(top_vacancies)}] {vacancy['title']} — {vacancy['company']}")

        try:
            letter = generate_letter(vacancy)
            results.append({
                "title": vacancy["title"],
                "company": vacancy["company"],
                "link": vacancy["link"],
                "score": vacancy["score"],
                "reason": vacancy.get("reason", ""),
                "cover_letter": letter,
            })
            print(f"   ✅ Письмо готово ({len(letter)} символов)")
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")

        time.sleep(SLEEP_BETWEEN)

    # Сохраняем результат
    with open("cover_letters.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=4)

    print(f"\n{'='*50}")
    print(f"✅ ГОТОВО! Сгенерировано {len(results)} писем.")
    print(f"📁 Файл: cover_letters.json")
    print(f"{'='*50}")

    if results:
        print(f"\n📨 ПРИМЕР ПЕРВОГО ПИСЬМА:\n")
        print(f"Вакансия: {results[0]['title']}")
        print(f"Компания: {results[0]['company']}")
        print(f"Оценка: {results[0]['score']}/100")
        print(f"\n--- ТЕКСТ ПИСЬМА ---\n")
        print(results[0]["cover_letter"])
        print(f"\n--- КОНЕЦ ---")


if __name__ == "__main__":
    main()