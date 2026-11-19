"""Отобрать активные вакансии из проанализированных перед генерацией писем.

Открывает страницы через Playwright и отбрасывает архивные, уже отправленные
и вакансии без кнопки отклика. Результат сохраняется в active_candidates.json —
именно его удобно скармливать hh_writer.py, чтобы не тратить письма на архив.

Запуск:
    python hh_active_filter.py --headless --top 50
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from database import get_manual_queue, get_sent_links, init_db
from hh_browser import launch_context
from hh_details_collector import read_description
from paths import ANALYZED_FILE, ACTIVE_CANDIDATES_FILE
from utils import configure_stdout, log, read_json, write_json

configure_stdout(line_buffering=True)

BLOCK_MARKERS = ("запретил доступ", "hh.ru недоступен", "Пройдите капчу")


def load_vacancies(path: Path) -> list[dict]:
    data = read_json(path, [])
    if isinstance(data, dict):
        data = data.get("items") or data.get("vacancies") or []
    return [item for item in data if isinstance(item, dict) and item.get("link")]


def main():
    parser = argparse.ArgumentParser(description="Отбор активных вакансий")
    parser.add_argument("--input", type=Path, default=ANALYZED_FILE)
    parser.add_argument("--output", type=Path, default=ACTIVE_CANDIDATES_FILE)
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--pause", type=float, default=2.5, help="пауза между страницами, сек")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    init_db()
    sent = get_sent_links()
    manual = {item["link"] for item in get_manual_queue()}

    vacancies = load_vacancies(args.input)
    seen = set()
    candidates = []
    for vacancy in vacancies:
        link = vacancy["link"]
        if link in sent or link in manual or link in seen:
            continue
        seen.add(link)
        candidates.append(vacancy)

    candidates.sort(key=lambda v: v.get("score", 0), reverse=True)
    candidates = candidates[: args.top]
    log(f"📊 Проверяю {len(candidates)} вакансий из {args.input.name}")

    active = []
    statuses = {}
    with sync_playwright() as p:
        browser, context = launch_context(p, headless=args.headless)
        page = context.new_page()
        try:
            for index, vacancy in enumerate(candidates, start=1):
                link = vacancy["link"]
                try:
                    page.goto(link, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(2200)
                    body = page.locator("body").inner_text(timeout=5000)
                except Exception as e:
                    statuses["error"] = statuses.get("error", 0) + 1
                    log(f"[{index}] ⚠️ Ошибка: {str(e)[:80]}")
                    continue

                if any(marker in body for marker in BLOCK_MARKERS):
                    log("🛑 hh.ru заблокировал доступ или показал капчу. Останавливаюсь.")
                    break

                archived = "Вакансия в архиве" in body
                responded = "Вы откликнулись" in body
                has_button = page.locator('[data-qa="vacancy-response-link-top"]').count() > 0

                if archived:
                    status = "архив"
                elif responded:
                    status = "уже откликались"
                elif not has_button:
                    status = "нет кнопки"
                else:
                    status = "активна"

                statuses[status] = statuses.get(status, 0) + 1
                if status == "активна":
                    item = dict(vacancy)
                    if not item.get("snippet"):
                        item["snippet"] = read_description(page)[:2500]
                    active.append(item)
                    log(f"[{index}] ✅ {vacancy.get('title', '')[:55]}")
                else:
                    log(f"[{index}] ⏭️ {status}: {vacancy.get('title', '')[:55]}")

                page.wait_for_timeout(int(args.pause * 1000))
        finally:
            browser.close()

    write_json(args.output, active)
    log("=" * 60)
    log(f"Активных: {len(active)}. Статусы: {statuses}")
    log(f"📁 Файл: {args.output}")


if __name__ == "__main__":
    main()
