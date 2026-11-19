"""Создание и наполнение резюме на hh.ru через Playwright.

Что делает:
1. Дублирует базовое резюме (чтобы унаследовать опыт, образование и контакты).
2. Задаёт уникальное название должности и специализацию.
3. Заполняет «О себе» и навыки из generated_resumes.json.
4. Проверяет результат и сохраняет хэши в hh_created_resumes.json.

Примеры:
    python hh_resume_filler.py --list
    python hh_resume_filler.py --ids bots,ai
    python hh_resume_filler.py --all
    python hh_resume_filler.py --all --update      # обновить тексты у созданных
    python hh_resume_filler.py --id general --hash 3d26396dff116c7e930039ed1f4f6e7a66794c
"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from hh_browser import launch_context
from paths import CREATED_RESUMES_FILE, GENERATED_RESUMES_FILE
from utils import configure_stdout, log, read_json, write_json

HH = "https://hh.ru"

# id специализации hh.ru -> поисковая строка для дерева специальностей
SPEC_SEARCH = {
    96: "Программист",
    124: "Тестировщик",
    156: "BI-аналитик",
}

# Какие специализации ставить для каждого типа резюме.
SPEC_BY_FOCUS = {
    "qa": [124, 96],
    "data": [156, 96],
}
DEFAULT_SPECS = [96]

BLOCK_MARKERS = (
    "подтвердите, что вы не робот",
    "доступ ограничен",
    "слишком много запросов",
    "не робот",
    "войдите в аккаунт",
)


class HhBlocked(RuntimeError):
    """hh.ru показал капчу, ограничение или потребовал логин."""


def norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def dismiss_cookies(page):
    loc = page.locator('[data-qa="cookies-policy-informer-accept"]')
    try:
        if loc.count() and loc.first.is_visible():
            loc.first.click(timeout=3000)
            page.wait_for_timeout(600)
    except Exception:
        pass


def check_blocked(page):
    """Останавливаемся, если hh показал капчу/ограничение/логин."""
    url = page.url
    if "/account/login" in url or "/login" in url:
        raise HhBlocked(f"Похоже, сессия истекла: {url}")
    try:
        body = norm(page.locator("body").inner_text(timeout=5000))[:4000]
    except Exception:
        return
    for marker in BLOCK_MARKERS:
        if marker in body:
            raise HhBlocked(f"hh.ru показал ограничение: «{marker}». Остановился.")


def load_resumes():
    data = read_json(GENERATED_RESUMES_FILE, default={}) or {}
    resumes = data.get("resumes", [])
    if not resumes:
        raise SystemExit(
            f"Нет данных в {GENERATED_RESUMES_FILE.name}. "
            "Сначала запусти hh_resume_generator.py"
        )
    return {r["id"]: r for r in resumes}


def load_state():
    return read_json(CREATED_RESUMES_FILE, default={}) or {}


def save_state(state):
    write_json(CREATED_RESUMES_FILE, state)


def resume_hash_from_url(url):
    match = re.search(r"[?&]resume=([0-9a-f]{32,})", url)
    return match.group(1) if match else None


# ---------------------------------------------------------------- создание


def duplicate_resume(page, source_hash):
    """Дублирует резюме и возвращает хэш черновика."""
    page.goto(f"{HH}/applicant/resumes", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    dismiss_cookies(page)
    check_blocked(page)

    link = page.locator(f'[data-qa="resume-card-link-{source_hash}"]')
    if link.count() == 0:
        raise RuntimeError(
            f"Не нашёл резюме-источник {source_hash} в списке резюме. "
            "Проверь хэш или открой /applicant/resumes вручную."
        )

    card = link.first.locator('xpath=ancestor::*[@data-qa="resume"]')
    card.locator('[data-qa="resume-list-action-more"]').first.click()
    page.wait_for_timeout(1000)
    page.locator('[data-qa="operations-list-duplicate-resume"]').first.click()
    page.wait_for_timeout(5000)

    new_hash = resume_hash_from_url(page.url)
    if not new_hash:
        raise RuntimeError(f"Не удалось получить хэш дубликата из URL: {page.url}")
    log(f"  дубликат создан: {new_hash}")
    return new_hash


def pick_specializations(page, spec_ids):
    """Отмечает специализации в модалке «Уточните специальность»."""
    modal = page.locator('[data-qa="modal-overlay"]')
    if modal.count() == 0:
        return False

    search = page.locator('[data-qa="tree-selector-search-input"]').first
    chosen = 0
    for spec_id in spec_ids:
        query = SPEC_SEARCH.get(spec_id, "Программист")
        search.fill(query)
        page.wait_for_timeout(1500)
        item = page.locator(f'[data-qa="tree-selector-item tree-selector-item-{spec_id}"]').first
        if item.count() == 0:
            log(f"  ⚠️ специализация {spec_id} не найдена по запросу «{query}»")
            continue
        item.click()
        page.wait_for_timeout(700)
        chosen += 1

    log(f"  специализаций выбрано: {chosen}")
    save = modal.locator('button:has-text("Сохранить")').first
    save.click()
    page.wait_for_timeout(3000)
    return True


def set_profession(page, hash_, title, spec_ids):
    """Задаёт название должности и специализацию, публикует черновик."""
    page.goto(
        f"{HH}/profile/resume/professional_role?resume={hash_}",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    page.wait_for_timeout(4000)
    dismiss_cookies(page)
    check_blocked(page)

    select_job = page.locator('[data-qa="resume-profile-card-select-job"]')
    if select_job.count() and select_job.first.is_visible():
        select_job.first.click()
        page.wait_for_timeout(1500)

    field = page.locator('[data-qa="resume-profile-position-input"]').first
    field.fill(title)
    page.wait_for_timeout(2500)

    suggest = page.locator('[data-qa="suggest-item-cell"]')
    if suggest.count():
        suggest.first.click()
        page.wait_for_timeout(2500)

    pick_specializations(page, spec_ids)

    # Возвращаемся на экран профессии и сохраняем
    next_btn = page.locator('[data-qa="resume-profile-next-screen"]')
    if next_btn.count():
        next_btn.first.scroll_into_view_if_needed()
        try:
            next_btn.first.click(timeout=10000)
        except Exception:
            next_btn.first.click(force=True)
        page.wait_for_timeout(4500)

    check_blocked(page)
    body = norm(page.locator("body").inner_text(timeout=6000))
    if "уже существует резюме с такой должностью" in body:
        raise RuntimeError(f"hh.ru уже имеет резюме с должностью «{title}»")

    log(f"  опубликовано: {page.url}")


def set_title_if_changed(page, hash_, title):
    """Меняет название должности, если оно отличается от сгенерированного."""
    page.goto(f"{HH}/resume/edit/{hash_}/position", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3500)
    dismiss_cookies(page)
    check_blocked(page)

    field = page.locator('[data-qa="resume-edit-title-suggest"]').first
    current = field.input_value()
    if norm(current) == norm(title):
        log("  заголовок уже актуален")
        return

    field.fill(title)
    page.wait_for_timeout(1500)
    save = page.locator('[data-qa="resume-partial-edit-save"]').first
    save.click()
    page.wait_for_timeout(4000)
    check_blocked(page)
    body = norm(page.locator("body").inner_text(timeout=6000))
    if "уже существует резюме с такой должностью" in body:
        raise RuntimeError(f"hh.ru уже имеет резюме с должностью «{title}»")
    log(f"  заголовок обновлён: {title}")


def set_about(page, hash_, text):
    page.goto(f"{HH}/resume/edit/{hash_}/about", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3500)
    dismiss_cookies(page)
    check_blocked(page)

    textarea = page.locator('[data-qa="resume-editor-about"]').first
    textarea.fill(text)
    page.wait_for_timeout(700)
    page.locator('[data-qa="resume-partial-edit-save"]').first.click()
    page.wait_for_timeout(3500)
    check_blocked(page)
    log("  «О себе» сохранено")


def add_skill(page, skill):
    """Добавляет навык: сначала пробует подсказку hh, иначе создаёт свой."""
    inp = page.locator('[data-qa="chips-trigger-input"]').first
    inp.fill(skill)
    page.wait_for_timeout(1000)
    own = page.locator('[data-qa="suggest-item-user-input"]')
    if own.count():
        own.first.click()
    else:
        inp.press("Enter")
    page.wait_for_timeout(600)


def set_skill_levels(page):
    """Ставит «Базовый» всем навыкам на экране уровней и сохраняет."""
    page.wait_for_timeout(1500)
    try:
        page.evaluate(
            """
            () => {
              for (const input of document.querySelectorAll('input[type="radio"]')) {
                if (input.name.endsWith('Базовый')) input.click();
              }
            }
            """
        )
        page.wait_for_timeout(800)
    except Exception as exc:
        log(f"  ⚠️ не удалось выставить уровни: {exc}")

    save = page.locator('[data-qa="resume-partial-edit-save"]')
    if save.count():
        save.first.click()
        page.wait_for_timeout(4000)


def set_skills(page, hash_, skills):
    page.goto(f"{HH}/resume/edit/{hash_}/keySkills", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3500)
    dismiss_cookies(page)
    check_blocked(page)

    removed = 0
    for _ in range(80):
        btns = page.locator('[data-qa="chip-delete-action"]')
        if btns.count() == 0:
            break
        btns.first.click()
        removed += 1
        page.wait_for_timeout(120)

    for skill in skills:
        add_skill(page, skill)

    count = page.locator('[data-qa="chip-delete-action"]').count()
    log(f"  навыков: удалено {removed}, добавлено {count}")

    page.locator('[data-qa="resume-partial-edit-save"]').first.click()
    page.wait_for_timeout(4000)

    if "skillsLevels" in page.url:
        set_skill_levels(page)

    check_blocked(page)


def verify_resume(page, hash_, expected):
    page.goto(f"{HH}/resume/{hash_}", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    check_blocked(page)
    body = norm(page.locator("body").inner_text(timeout=8000))
    title_ok = norm(expected["title"]) in body
    about_ok = norm(expected["about"][:60]) in body
    skills_found = sum(1 for s in expected["skills"] if norm(s) in body)
    log(
        f"  проверка: заголовок={'ок' if title_ok else 'НЕТ'}, "
        f"о себе={'ок' if about_ok else 'НЕТ'}, "
        f"навыки={skills_found}/{len(expected['skills'])}"
    )
    return title_ok and about_ok and skills_found >= max(6, len(expected["skills"]) - 2)


# ---------------------------------------------------------------- runner


def process_resume(page, resume, state, source_hash, existing_hash=None):
    rid = resume["id"]
    log(f"=== {rid}: {resume['title']}")

    if existing_hash:
        hash_ = existing_hash
        log(f"  использую готовое резюме {hash_}")
        state.setdefault("resumes", {})[rid] = {
            "hash": hash_,
            "title": resume["title"],
            "source": "manual",
            "updated": datetime.now().isoformat(timespec="seconds"),
        }
        save_state(state)
        # у готового резюме меняем наполнение
        set_title_if_changed(page, hash_, resume["title"])
        set_about(page, hash_, resume["about"])
        set_skills(page, hash_, resume["skills"])
    else:
        hash_ = duplicate_resume(page, source_hash)
        specs = SPEC_BY_FOCUS.get(resume.get("focus"), DEFAULT_SPECS)
        set_profession(page, hash_, resume["title"], specs)
        state.setdefault("resumes", {})[rid] = {
            "hash": hash_,
            "title": resume["title"],
            "source": source_hash,
            "updated": datetime.now().isoformat(timespec="seconds"),
        }
        save_state(state)
        set_about(page, hash_, resume["about"])
        set_skills(page, hash_, resume["skills"])

    ok = verify_resume(page, hash_, resume)
    state["resumes"][rid]["verified"] = ok
    save_state(state)
    return ok


def main():
    configure_stdout(line_buffering=True)
    parser = argparse.ArgumentParser(description="Создание резюме на hh.ru")
    parser.add_argument("--ids", help="через запятую: bots,ai,qa")
    parser.add_argument("--all", action="store_true", help="все резюме из generated_resumes.json")
    parser.add_argument("--id", help="одно резюме по id")
    parser.add_argument("--hash", help="взять существующее резюме вместо создания")
    parser.add_argument("--update", action="store_true",
                        help="обновить «О себе» и навыки у уже созданных резюме")
    parser.add_argument("--source-hash", help="хэш резюме-источника для дублирования")
    parser.add_argument("--force", action="store_true", help="перезаписать уже готовые")
    parser.add_argument("--list", action="store_true", help="показать статус и выйти")
    parser.add_argument("--headless", action="store_true", help="без окна браузера")
    args = parser.parse_args()

    resumes = load_resumes()
    state = load_state()

    if args.list:
        created = state.get("resumes", {})
        for rid, resume in resumes.items():
            info = created.get(rid)
            status = "готово" if info else "нет"
            extra = f" {info['hash']}" if info else ""
            log(f"{rid:15} {status:7} {resume['title']}{extra}")
        return

    if args.id:
        ids = [args.id]
    elif args.ids:
        ids = [x.strip() for x in args.ids.split(",") if x.strip()]
    elif args.all:
        ids = list(resumes)
    else:
        parser.error("Укажи --id, --ids, --all или --list")

    unknown = [x for x in ids if x not in resumes]
    if unknown:
        parser.error(f"Неизвестные id: {', '.join(unknown)}")

    source_hash = args.source_hash or state.get("source_hash")
    if not source_hash and not args.hash:
        parser.error(
            "Не знаю, какое резюме дублировать. Передай --source-hash <хэш> "
            "(хэш видно в адресе резюме на hh.ru)."
        )
    if source_hash:
        state["source_hash"] = source_hash

    created = state.get("resumes", {})
    with sync_playwright() as p:
        browser, context = launch_context(p, headless=args.headless)
        page = context.new_page()
        results = {}
        try:
            for rid in ids:
                if args.update:
                    info = created.get(rid)
                    if not info:
                        log(f"=== {rid}: ещё не создано, --update пропускает")
                        continue
                    results[rid] = process_resume(
                        page, resumes[rid], state, source_hash,
                        existing_hash=info["hash"],
                    )
                    page.wait_for_timeout(15000)
                    continue
                if rid in created and not args.force and not args.hash:
                    log(f"=== {rid}: уже создано ({created[rid]['hash']}), пропускаю")
                    continue
                results[rid] = process_resume(
                    page, resumes[rid], state, source_hash, existing_hash=args.hash
                )
                args.hash = None  # --hash относится только к одному id
                # пауза между резюме: снижает риск срабатывания антибота hh.ru
                page.wait_for_timeout(15000)
        except HhBlocked as exc:
            log(f"🛑 {exc}")
            log("Остановился, чтобы не усугубить блокировку. Проверь hh.ru вручную.")
        finally:
            browser.close()

    if results:
        log("Итог:")
        for rid, ok in results.items():
            log(f"  {rid}: {'ок' if ok else 'проверь вручную'}")


if __name__ == "__main__":
    main()
