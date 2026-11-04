import json

from config import CANDIDATE_INFO, ask_llm
from database import get_manual_queue, get_sent_links, init_db
from paths import ANALYZED_FILE, COVER_LETTERS_FILE
from utils import (
    backup_file,
    configure_stdout,
    read_json,
    try_read_json,
    write_json,
)

configure_stdout()

# ============================================
# НАСТРОЙКИ
# ============================================
TOP_N = 10                    # Сколько новых вакансий обрабатываем за раз
WRITER_TEMPERATURE = 0.7
MIN_LETTER_LENGTH = 80        # Короче — считаем, что модель сломалась
GENERATION_ATTEMPTS = 2
# ============================================


def normalize_letters(items):
    """Оставляет только корректные письма и убирает дубликаты по ссылке."""
    if not isinstance(items, list):
        return []
    result = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        if not link or link in seen:
            continue
        seen.add(link)
        result.append(item)
    return result


def select_pending(letters, sent_links, manual_links):
    """Письма прошлых запусков, которые ещё не отправлены и не ушли в ручную очередь."""
    return [
        item for item in normalize_letters(letters)
        if item["link"] not in sent_links and item["link"] not in manual_links
    ]


def select_new(analyzed, busy_links, limit=TOP_N, min_score=70):
    """Топовые вакансии, которых ещё нет в работе."""
    result = []
    seen = set(busy_links)
    for vacancy in analyzed:
        if not isinstance(vacancy, dict):
            continue
        link = vacancy.get("link")
        if not link or link in seen:
            continue
        if vacancy.get("score", 0) < min_score:
            continue
        result.append(vacancy)
        seen.add(link)
        if len(result) >= limit:
            break
    return result


def load_pending_letters():
    """Читает cover_letters.json. Битый файл откладывает в .broken, а не теряет молча."""
    try:
        return normalize_letters(read_json(COVER_LETTERS_FILE, []))
    except (json.JSONDecodeError, OSError) as e:
        backup = backup_file(COVER_LETTERS_FILE)
        suffix = f", копия: {backup.name}" if backup else ""
        print(f"⚠️ cover_letters.json поврежден ({e}){suffix}")
        return []


def generate_letter(vacancy):
    """Генерирует письмо и проверяет, что модель вернула текст, а не пустоту."""
    prompt = f"""Ты — опытный карьерный консультант. Напиши короткое сопроводительное письмо для отклика на вакансию.

ИНФОРМАЦИЯ О КАНДИДАТЕ:
{CANDIDATE_INFO}

ВАКАНСИЯ:
Название: {vacancy.get('title', '')}
Компания: {vacancy.get('company', '')}
Описание: {vacancy.get('snippet', '')}

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
    last_error = None
    for attempt in range(1, GENERATION_ATTEMPTS + 1):
        try:
            letter = ask_llm(prompt, temperature=WRITER_TEMPERATURE).strip()
            if len(letter) < MIN_LETTER_LENGTH:
                raise ValueError(f"слишком короткий ответ ({len(letter)} символов)")
            return letter
        except Exception as e:
            last_error = e
            print(f"   ⚠️ Попытка {attempt}/{GENERATION_ATTEMPTS} не удалась: {e}")
    raise last_error


def main():
    init_db()

    analyzed = try_read_json(ANALYZED_FILE, [])
    if not isinstance(analyzed, list):
        print("❌ analyzed_vacancies.json имеет неверный формат. Запусти hh_analyzer.py")
        return

    # Отправленные берем из SQLite, а не из устаревшего sent_log.json
    already_sent = get_sent_links()
    manual_links = {item["link"] for item in get_manual_queue()}

    # Неотправленные письма прошлого запуска сохраняем
    pending = select_pending(load_pending_letters(), already_sent, manual_links)

    print(f"📂 Всего вакансий в базе: {len(analyzed)}")
    print(f"📤 Уже отправлено откликов: {len(already_sent)}")
    if pending:
        print(f"📝 Неотправленных писем с прошлого запуска: {len(pending)}")

    busy_links = already_sent | manual_links | {item["link"] for item in pending}
    top_vacancies = select_new(analyzed, busy_links)

    if not top_vacancies and not pending:
        print("🎉 Нет новых вакансий для генерации писем. Все топовые уже отработаны.")
        return

    print(f"🔥 Новых топовых вакансий (70+): {len(top_vacancies)}")
    print("✍️  Генерирую письма...\n")

    results = list(pending)
    generated = 0

    for i, vacancy in enumerate(top_vacancies, start=1):
        print(f"[{i}/{len(top_vacancies)}] {vacancy.get('title')} — {vacancy.get('company')}")

        try:
            letter = generate_letter(vacancy)
            results.append({
                "title": vacancy.get("title", ""),
                "company": vacancy.get("company", ""),
                "link": vacancy["link"],
                "score": vacancy.get("score", 0),
                "reason": vacancy.get("reason", ""),
                "cover_letter": letter,
            })
            generated += 1
            print(f"   ✅ Письмо готово ({len(letter)} символов)")
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")

    # Сохраняем результат, не теряя неотправленные письма прошлых запусков
    write_json(COVER_LETTERS_FILE, results)

    print(f"\n{'='*50}")
    print(f"✅ ГОТОВО! Писем в очереди: {len(results)} (новых: {generated})")
    print(f"📁 Файл: {COVER_LETTERS_FILE.name}")
    print(f"{'='*50}")

    if results:
        print("\n📨 ПРИМЕР ПЕРВОГО ПИСЬМА:\n")
        print(f"Вакансия: {results[0].get('title')}")
        print(f"Компания: {results[0].get('company')}")
        print(f"Оценка: {results[0].get('score')}/100")
        print("\n--- ТЕКСТ ПИСЬМА ---\n")
        print(results[0].get("cover_letter", ""))
        print("\n--- КОНЕЦ ---")


if __name__ == "__main__":
    main()
