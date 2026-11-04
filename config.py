"""Общие настройки проекта: профиль кандидата и единая точка вызова LLM."""
import os
import time

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

MODEL_NAME = "deepseek-chat"
BASE_URL = "https://api.deepseek.com"

# ============================================
# ПРОФИЛЬ КАНДИДАТА (используется анализатором)
# ============================================
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

# ============================================
# ИНФОРМАЦИЯ ДЛЯ ПИСЕМ (используется копирайтером)
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


def get_client():
    """Создает клиент DeepSeek. Понятно падает, если ключ не настроен."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY не найден. Создай файл .env и добавь строку "
            "DEEPSEEK_API_KEY=твой_ключ"
        )
    return OpenAI(base_url=BASE_URL, api_key=api_key)


def ask_llm(prompt, temperature=0.2, json_mode=False, retries=3, base_delay=3):
    """Запрос к LLM с повторами и экспоненциальной паузой.

    Один сбой сети или лимита больше не роняет всю пачку вакансий.
    """
    client = get_client()
    extra = {"response_format": {"type": "json_object"}} if json_mode else {}

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                **extra,
            )
            return response.choices[0].message.content
        except Exception as e:
            last_error = e
            if attempt < retries:
                delay = base_delay * (2 ** (attempt - 1))
                print(f"   ⚠️ Ошибка LLM (попытка {attempt}/{retries}): {e}")
                print(f"   🔄 Повтор через {delay} сек...")
                time.sleep(delay)

    raise last_error
