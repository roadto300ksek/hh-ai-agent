import json
import os
import sys

from config import CANDIDATE_INFO, ask_llm
from database import get_manual_queue, get_sent_links, init_db

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ============================================
# НАСТРОЙКИ
# ============================================
TOP_N = 10                    # Сколько новых вакансий обрабатываем за раз
WRITER_TEMPERATURE = 0.7
LETTERS_FILE = "cover_letters.json"
# ============================================


def load_json(path, default):
    if os.path.exists(path):
        # utf-8-sig — чтобы файлы, отредактированные в Блокноте с BOM, не ломали запуск
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return default


def load_pending_letters():
    """Письма из прошлого запуска, которые ещё не были отправлены.

    Раньше файл перезаписывался целиком, и неотправленные письма терялись
    (например, если исполнитель упёрся в капчу).
    """
    letters = load_json(LETTERS_FILE, [])
    if not isinstance(letters, list):
        return []
    return [item for item in letters if isinstance(item, dict) and item.get("link")]


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
    return ask_llm(prompt, temperature=WRITER_TEMPERATURE).strip()


def main():
    init_db()

    # Загружаем проанализированные вакансии
    if not os.path.exists("analyzed_vacancies.json"):
        print("❌ Файл analyzed_vacancies.json не найден. Сначала запусти hh_analyzer.py")
        return

    with open("analyzed_vacancies.json", "r", encoding="utf-8-sig") as f:
        all_vacancies = json.load(f)

    # Отправленные берем из SQLite, а не из устаревшего sent_log.json
    already_sent = get_sent_links()
    manual_links = {item["link"] for item in get_manual_queue()}

    # Неотправленные письма прошлого запуска сохраняем
    pending = [
        item for item in load_pending_letters()
        if item["link"] not in already_sent and item["link"] not in manual_links
    ]

    print(f"📂 Всего вакансий в базе: {len(all_vacancies)}")
    print(f"📤 Уже отправлено откликов: {len(already_sent)}")
    if pending:
        print(f"📝 Неотправленных писем с прошлого запуска: {len(pending)}")

    busy_links = already_sent | manual_links | {item["link"] for item in pending}

    # Фильтруем: топ с оценкой >= 70, исключая уже обработанные
    top_vacancies = [
        v for v in all_vacancies
        if v.get("score", 0) >= 70 and v.get("link") not in busy_links
    ][:TOP_N]

    if not top_vacancies and not pending:
        print("🎉 Нет новых вакансий для генерации писем. Все топовые уже отработаны.")
        return

    print(f"🔥 Новых топовых вакансий (70+): {len(top_vacancies)}")
    print(f"✍️  Генерирую письма...\n")

    results = list(pending)

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

    # Сохраняем результат, не теряя неотправленные письма прошлых запусков
    with open(LETTERS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=4)

    print(f"\n{'='*50}")
    print(f"✅ ГОТОВО! Писем в очереди: {len(results)} "
          f"(новых: {len(results) - len(pending)})")
    print(f"📁 Файл: {LETTERS_FILE}")
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
