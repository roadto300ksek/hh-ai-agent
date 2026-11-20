"""Одна кнопка: весь цикл работы с hh.ru без участия пользователя.

Последовательно запускает:
1. сбор вакансий (hh_scanner_multi.py);
2. LLM-анализ (hh_analyzer.py);
3. отбор только активных вакансий (hh_active_filter.py);
4. генерацию 10 писем (hh_writer.py);
5. отправку 5 откликов с паузами 5–10 минут (hh_executor.py).

Прогресс пишется в auto_status.json — дашборд показывает текущий шаг.
Остановка из дашборда убивает всё дерево процессов (taskkill /T).
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from database import get_manual_queue, get_sent_links, init_db
from paths import ACTIVE_CANDIDATES_FILE, AUTO_STATUS_FILE, BASE_DIR, COVER_LETTERS_FILE
from utils import configure_stdout, log, read_json, write_json

configure_stdout(line_buffering=True)

STAGES = [
    ("Сбор вакансий", "hh_scanner_multi.py", ()),
    ("Анализ вакансий", "hh_analyzer.py", ()),
    (
        "Отбор активных вакансий",
        "hh_active_filter.py",
        ("--headless", "--top", "100"),
    ),
    (
        "Генерация писем",
        "hh_writer.py",
        ("--input", str(ACTIVE_CANDIDATES_FILE), "--limit", "10", "--min-score", "0"),
    ),
    (
        "Отправка откликов",
        "hh_executor.py",
        ("--headless", "--limit", "5", "--min-delay", "300", "--max-delay", "600"),
    ),
]


def status(stage: int, label: str, state: str = "running"):
    write_json(AUTO_STATUS_FILE, {
        "stage": stage,
        "total": len(STAGES),
        "label": label,
        "state": state,
        "updated": datetime.now().isoformat(timespec="seconds"),
    })


def run_stage(script: str, args: tuple[str, ...]) -> bool:
    command = [sys.executable, "-u", str(BASE_DIR / script), *args]
    log(f"▶️ {' '.join(command)}")
    try:
        result = subprocess.run(command, cwd=str(BASE_DIR), check=False)
    except Exception as e:
        log(f"❌ Не удалось запустить {script}: {e}")
        return False
    if result.returncode != 0:
        log(f"⚠️ {script} завершился с кодом {result.returncode}")
        return False
    return True


def busy_links() -> set[str]:
    """Вакансии, которые уже отправлены или ушли в ручную очередь."""
    manual = {item["link"] for item in get_manual_queue() if item.get("link")}
    return get_sent_links() | manual


def pending_letters() -> list[dict]:
    """Неотправленные письма с готовыми текстами."""
    busy = busy_links()
    data = read_json(COVER_LETTERS_FILE, []) or []
    if not isinstance(data, list):
        return []
    return [
        item for item in data
        if isinstance(item, dict)
        and item.get("link")
        and item.get("cover_letter")
        and item["link"] not in busy
    ]


def pending_active() -> list[dict]:
    """Активные вакансии, по которым ещё нет письма и отклика."""
    busy = busy_links()
    data = read_json(ACTIVE_CANDIDATES_FILE, []) or []
    if isinstance(data, dict):
        data = data.get("items", [])
    if not isinstance(data, list):
        return []
    return [
        item for item in data
        if isinstance(item, dict) and item.get("link") and item["link"] not in busy
    ]


def main():
    init_db()
    status(0, "Подготовка")
    log("=" * 70)
    log("🚀 Полный цикл запущен")
    log("=" * 70)

    # Умный пропуск: если данные уже есть, не сканируем заново.
    skip: set[int] = set()
    letters_ready = pending_letters()
    active_ready = pending_active()
    if letters_ready:
        skip = {1, 2, 3, 4}
        log(
            f"⚡ В очереди {len(letters_ready)} готовых писем. "
            "Сбор, анализ, отбор и генерация пропущены — сразу отправляем."
        )
    elif active_ready:
        skip = {1, 2}
        log(
            f"⚡ Уже есть {len(active_ready)} активных вакансий. "
            "Сбор и анализ пропущены — пишем письма и отправляем."
        )

    for index, (label, script, args) in enumerate(STAGES, start=1):
        if index in skip:
            continue
        if script == "hh_writer.py" and not pending_active():
            log("⏭️ Нет активных вакансий — письма и отклики пропускаются.")
            status(index, "Нет активных вакансий", state="skipped")
            continue
        if script == "hh_executor.py" and not pending_letters():
            log("⏭️ Нет писем в очереди — отправка пропускается.")
            status(index, "Нет писем в очереди", state="skipped")
            continue

        status(index, label)
        log(f"\n--- ЭТАП {index}/{len(STAGES)}: {label} ---")
        if not run_stage(script, args):
            status(index, f"Ошибка: {label}", state="error")
            log("🛑 Цикл остановлен из-за ошибки на этом этапе.")
            return

    status(len(STAGES), "Цикл завершён", state="done")
    log("\n✅ ПОЛНЫЙ ЦИКЛ ЗАВЕРШЁН")


if __name__ == "__main__":
    main()
