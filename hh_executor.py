import random
import sys
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

from database import (
    add_sent_application,
    add_to_manual_queue,
    get_no_letter_links,
    get_sent_links,
    get_today_sent_count,
    init_db,
    remove_from_manual_queue,
)
from hh_browser import launch_context
from paths import COVER_LETTERS_FILE, SCREENSHOT_DIR
from utils import configure_stdout, has_visible, log, page_is_closed, try_read_json

configure_stdout(line_buffering=True)

# ============================================
# НАСТРОЙКИ
# ============================================
DAILY_LIMIT = 50
MIN_DELAY_SEC = 300
MAX_DELAY_SEC = 900
HEADLESS = False
# ============================================

SEND_ERROR_MARKERS = [
    'text=Не удалось отправить',
    'text=Произошла ошибка',
    'text=Попробуйте ещё раз',
    'text=Отклик не отправлен',
]

# Новый интерфейс hh.ru: чат отклика открывается в iframe chatik.hh.ru,
# а сопроводительное письмо добавляется уже после отправки отклика.
CHAT_FRAME_URL = "chatik.hh.ru"
CHAT_ADD_LETTER_QA = '[data-qa="chatik-chat-message-applicant-action"]'
CHAT_TEXTAREA_QA = '[data-qa="text-input"]'
CHAT_SEND_QA = '[data-qa="chatik-do-send-message"]'
CHAT_PREVIEW_QA = '[data-qa="chat-input-preview"]'
CHAT_RESPONSE_BUTTON_QA = '[data-qa="vacancy-response-link-view-topic"]'
NO_LETTER_TEXT = "Без сопроводительного письма"

ERROR_RESULTS = {
    "no_button",
    "no_submit",
    "click_error",
    "chat_failed",
    "send_error",
    "exception",
}


def random_delay():
    delay = random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC)
    log(f"⏳ Пауза {delay / 60:.1f} мин перед следующим откликом...")
    try:
        time.sleep(delay)
    except KeyboardInterrupt:
        log("🛑 Пауза прервана пользователем.")
        raise


def check_captcha(page):
    if "captcha" in page.url.lower():
        return True
    return has_visible(page, 'iframe[src*="captcha"]')


def check_auth_on_main(page):
    """Возвращает 'ok', 'captcha' или 'no'.

    Маркеры обновлены под новую вёрстку hh.ru: старые
    mainmenu_applicantProfile / mainmenu_myResumes больше не встречаются.
    """
    try:
        page.goto("https://hh.ru", wait_until="domcontentloaded")
        page.wait_for_timeout(8000)
    except Exception:
        return "no"

    if check_captcha(page):
        return "captcha"

    auth_markers = [
        '[data-qa="mainmenu_profileAndResumes"]',
        '[data-qa="mainmenu_applicantProfilePage"]',
        '[data-qa="mainmenu_applicantProfileDesktopDrop"]',
        'a[href*="/applicant/profile/me"]',
        'a[href*="/applicant/negotiations"]',
        'a[href*="/applicant/resumes"]',
    ]
    for marker in auth_markers:
        if has_visible(page, marker):
            return "ok"
    if has_visible(page, "text=Резюме и профиль") or has_visible(page, "text=Мои резюме"):
        return "ok"
    return "no"


def check_questions(page):
    return (
        has_visible(page, '[data-qa="vacancy-response-question"]')
        or has_visible(page, 'button:has-text("Ответить на вопросы")')
    )


def verify_response_sent(page):
    return (
        has_visible(page, 'text=Отклик отправлен')
        or has_visible(page, 'text=Вы откликнулись')
    )


def check_send_error(page):
    return any(has_visible(page, marker) for marker in SEND_ERROR_MARKERS)


def take_screenshot(page, prefix):
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{prefix}_{datetime.now():%H%M%S}.png"
    try:
        page.screenshot(path=str(path))
    except Exception:
        pass


def normalize_text(text):
    """Схлопывает пробелы и переводы строк для сравнения текста письма."""
    return " ".join((text or "").split())


def count_visible(container, selector, limit=5):
    """Сколько видимых элементов найдено внутри page/frame."""
    try:
        locator = container.locator(selector)
        return sum(
            1 for i in range(min(locator.count(), limit)) if locator.nth(i).is_visible()
        )
    except Exception:
        return 0


def find_chat_frame(page, timeout_ms=20000):
    """Ждёт загрузки iframe чата hh.ru и возвращает его."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if page_is_closed(page):
            return None
        try:
            frames = list(page.frames)
        except Exception:
            return None
        for frame in frames:
            if CHAT_FRAME_URL not in (frame.url or ""):
                continue
            try:
                if frame.locator(f"{CHAT_TEXTAREA_QA}, {CHAT_ADD_LETTER_QA}").count() > 0:
                    return frame
            except Exception:
                continue
        try:
            page.wait_for_timeout(500)
        except Exception:
            return None
    return None


def open_chat(page):
    """Открывает чат отклика. В новом интерфейсе это кнопка «Чат»."""
    frame = find_chat_frame(page, timeout_ms=2000)
    if frame:
        return frame

    selectors = (
        CHAT_RESPONSE_BUTTON_QA,
        'a:has-text("Перейти в чат")',
        'button:text-is("Чат")',
        'a:text-is("Чат")',
    )
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
        except Exception:
            continue
        for i in range(min(count, 5)):
            try:
                item = locator.nth(i)
                if not item.is_visible():
                    continue
                item.click()
            except Exception:
                continue
            frame = find_chat_frame(page)
            if frame:
                return frame
    return None


def letter_composer_is_open(frame):
    """Открыта ли карточка «Сопроводительное письмо» над полем ввода."""
    try:
        preview = frame.locator(CHAT_PREVIEW_QA)
        for i in range(min(preview.count(), 5)):
            item = preview.nth(i)
            if item.is_visible() and "Сопроводительное письмо" in item.inner_text():
                return True
    except Exception:
        pass
    return False


def chat_letter_state(frame, letter):
    """Что видно в чате: текст письма, плашка «Без письма», кнопка добавления."""
    try:
        body = normalize_text(frame.locator("body").inner_text())
    except Exception:
        return None

    snippet = normalize_text(letter)[:50]
    return {
        "snippet": bool(snippet) and snippet in body,
        "no_letter": NO_LETTER_TEXT in body,
        "add_button": count_visible(frame, CHAT_ADD_LETTER_QA),
    }


def chat_matches_vacancy(frame, title, company):
    """Проверяет, что открыт чат именно этой вакансии, а не предыдущей."""
    try:
        body = normalize_title(frame.locator("body").inner_text())
    except Exception:
        return False

    if title and normalize_title(title) in body:
        return True
    if company and normalize_title(company) in body:
        return True
    return False


def letter_draft_present(frame):
    """Есть ли в поле ввода неотправленный текст письма."""
    try:
        textarea = frame.locator(CHAT_TEXTAREA_QA).first
        if textarea.count() == 0 or not textarea.is_visible():
            return False
        return bool((textarea.input_value() or "").strip())
    except Exception:
        return False


def wait_letter_result(page, letter, before, timeout_sec=10):
    """Ждёт, пока письмо появится в переписке. True/False."""
    deadline = time.monotonic() + timeout_sec
    frame = None
    while time.monotonic() < deadline:
        frame = find_chat_frame(page, timeout_ms=500) or frame
        if frame is not None:
            after = chat_letter_state(frame, letter)
            if after is not None:
                if after["snippet"]:
                    return True
                if (
                    not after["no_letter"]
                    and after["add_button"] == 0
                    and (before["no_letter"] or before["add_button"] > 0)
                ):
                    return True
        page.wait_for_timeout(700)
    return False


def try_send_letter_once(page, letter, title="", company=""):
    """Одна попытка отправки письма.

    Возвращает 'sent', 'wrong_vacancy' или 'failed'. Ошибка на любом шаге
    не выбрасывается наружу — следующая попытка начнётся заново.
    """
    frame = open_chat(page)
    if frame is None:
        log("   ❌ Чат hh.ru не открылся.")
        return "failed"

    if (title or company) and not chat_matches_vacancy(frame, title, company):
        page.wait_for_timeout(1500)
        frame = find_chat_frame(page, timeout_ms=1000) or frame
        if not chat_matches_vacancy(frame, title, company):
            log("   ❌ Открылся чат другой вакансии. Письмо не отправляю.")
            return "wrong_vacancy"

    before = chat_letter_state(frame, letter) or {
        "snippet": False,
        "no_letter": False,
        "add_button": 0,
    }
    if before["snippet"]:
        log("   ✅ Письмо уже прикреплено к отклику.")
        return "sent"

    try:
        add_btn = frame.locator(CHAT_ADD_LETTER_QA).first
        if add_btn.count() > 0 and add_btn.is_visible():
            if letter_composer_is_open(frame):
                log("   ✍️ Поле сопроводительного письма уже открыто.")
            else:
                log("   🖱️ Нажимаю «Добавить сопроводительное»...")
                add_btn.click()
                page.wait_for_timeout(2000)
                frame = find_chat_frame(page, timeout_ms=3000) or frame
        else:
            log("   ⚠️ Кнопка «Добавить сопроводительное» не видна, пробую поле ввода.")
    except Exception as e:
        log(f"   ⚠️ Не удалось открыть поле письма: {e}")
        return "failed"

    textarea = frame.locator(CHAT_TEXTAREA_QA).first
    if textarea.count() == 0 or not textarea.is_visible():
        log("   ❌ Не нашёл поле ввода письма в чате.")
        return "failed"

    try:
        log("   ⌨️ Ввожу текст письма...")
        textarea.click()
        page.wait_for_timeout(300)
        textarea.fill(letter)
        page.wait_for_timeout(800)
    except Exception as e:
        log(f"   ⚠️ Не удалось ввести письмо: {e}")
        return "failed"

    # 1) Обычная отправка кнопкой.
    clicked = False
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            send_btn = frame.locator(CHAT_SEND_QA).first
            if send_btn.count() > 0 and send_btn.is_visible():
                send_btn.click()
                clicked = True
                break
        except Exception:
            pass
        page.wait_for_timeout(300)
        frame = find_chat_frame(page, timeout_ms=500) or frame

    if clicked:
        log("   📤 Нажал «Отправить», проверяю, что письмо прикрепилось...")
        if wait_letter_result(page, letter, before, timeout_sec=10):
            return "sent"

    # 2) Fallback: если кнопка не сработала, отправляем по Enter.
    if letter_draft_present(frame):
        log("   ↩️ Кнопка не сработала — отправляю по Enter.")
        try:
            frame.locator(CHAT_TEXTAREA_QA).first.press("Enter")
        except Exception as e:
            log(f"   ⚠️ Enter не сработал: {e}")
            return "failed"
        page.wait_for_timeout(1500)
        if wait_letter_result(page, letter, before, timeout_sec=10):
            return "sent"

    # 3) Последняя проверка: письмо могло уйти с задержкой.
    if wait_letter_result(page, letter, before, timeout_sec=3):
        return "sent"
    return "failed"


def send_letter_in_chat(page, letter, title="", company="", attempts=3):
    """Прикрепляет сопроводительное письмо к уже отправленному отклику.

    Работает внутри iframe chatik.hh.ru. Делает до `attempts` попыток:
    кнопка отправки, затем fallback по Enter. True возвращается только
    после того, как текст письма появился в переписке.
    """
    log("   💬 Открываю чат отклика...")
    for attempt in range(1, attempts + 1):
        if page_is_closed(page):
            return False
        try:
            result = try_send_letter_once(page, letter, title, company)
        except Exception as e:
            log(f"   ⚠️ Ошибка при отправке письма в чате: {e}")
            take_screenshot(page, "chat_exception")
            result = "failed"

        if result == "sent":
            if attempt > 1:
                log(f"   ✅ Письмо прикреплено с попытки {attempt}.")
            else:
                log("   ✅ Письмо прикреплено к отклику.")
            return True
        if result == "wrong_vacancy":
            take_screenshot(page, "chat_wrong_vacancy")
            return False
        if attempt < attempts:
            log(f"   🔁 Попытка {attempt}/{attempts} не удалась, пробую снова...")
            page.wait_for_timeout(2000)

    log("   ❌ Не удалось подтвердить, что письмо прикрепилось.")
    take_screenshot(page, "chat_not_confirmed")
    return False


def normalize_title(title):
    """Убирает различия в тире/пунктуации, чтобы сравнить название вакансии."""
    text = normalize_text(title).lower()
    return "".join(ch for ch in text if ch.isalnum() or ch == " ").strip()


def get_live_vacancy_title(page):
    for selector in ('[data-qa="vacancy-title"]', "h1"):
        try:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible():
                return locator.inner_text().strip()
        except Exception:
            continue
    return ""


def respond_to_vacancy(page, vacancy):
    link = vacancy["link"]
    title = vacancy.get("title", "")
    company = vacancy.get("company", "")
    letter = vacancy.get("cover_letter", "")
    score = vacancy.get("score", 0)

    log(f"🌐 Открываю: {link}")
    page.goto(link, wait_until="domcontentloaded")
    page.wait_for_timeout(random.randint(3000, 5000))

    if check_captcha(page):
        log("   🚨 КАПЧА! Останавливаю работу.")
        return "captcha"

    if has_visible(page, 'text=Вакансия в архиве'):
        log("   ⏭️  Вакансия в архиве. Пропуск.")
        add_sent_application(link, title, company, score, status="archived")
        return "archived"

    # Защита от письма не под ту вакансию: название на hh.ru могло измениться
    # после сканирования (реальный случай: 139082046).
    live_title = get_live_vacancy_title(page)
    if live_title and title and normalize_title(live_title) != normalize_title(title):
        log(f"   ⚠️ На hh.ru вакансия называется «{live_title}», а письмо — под «{title}».")
        log("   ⏭️  Пропускаю, чтобы не отправить письмо не под ту вакансию.")
        add_to_manual_queue(link, live_title, company, "Название вакансии изменилось")
        return "title_mismatch"

    # --- МЫ УЖЕ ОТКЛИКАЛИСЬ РАНЕЕ? ---
    if page.locator(CHAT_RESPONSE_BUTTON_QA).count() > 0 or has_visible(
        page, 'a:has-text("Перейти в чат")'
    ):
        log("   ⏭️  Уже откликались ранее.")
        add_sent_application(link, title, company, score, status="already")
        return "already"

    # --- ИЩЕМ КНОПКУ "ОТКЛИКНУТЬСЯ" ---
    respond_btn = page.locator('[data-qa="vacancy-response-link-top"]').first
    if respond_btn.count() == 0:
        respond_btn = page.locator('a:has-text("Откликнуться")').first
    if respond_btn.count() == 0:
        respond_btn = page.locator('button:has-text("Откликнуться")').first

    if respond_btn.count() == 0:
        log("   ❌ Кнопка 'Откликнуться' не найдена.")
        return "no_button"

    try:
        respond_btn.click()
    except Exception:
        return "click_error"

    page.wait_for_timeout(random.randint(4000, 6000))

    if check_captcha(page):
        return "captcha"

    # --- ВОПРОСЫ РАБОТОДАТЕЛЯ ---
    if check_questions(page):
        log("   ⚠️ Вопросы работодателя. В ручную очередь.")
        add_to_manual_queue(link, title, company, "Требуются ответы на вопросы")
        return "manual_questions"

    # --- КЛАССИЧЕСКИЙ ПОПАП С ПОЛЕМ ПИСЬМА ---
    letter_field = page.locator('[data-qa="vacancy-response-popup-form-letter-input"]').first
    if letter_field.count() == 0:
        toggle_btn = page.locator('[data-qa="vacancy-response-letter-toggle"]').first
        if toggle_btn.count() > 0:
            toggle_btn.click()
            page.wait_for_timeout(1500)
            letter_field = page.locator('[data-qa="vacancy-response-popup-form-letter-input"]').first

    if letter_field.count() > 0:
        log("   📋 Классический попап. Вставляю письмо...")
        try:
            letter_field.click()
            letter_field.fill(letter)
            log("   ✍️  Письмо вставлено в попап")
        except Exception as e:
            log(f"   ❌ Не удалось вставить письмо: {e}")
            add_to_manual_queue(link, title, company, "Не удалось заполнить письмо в попапе")
            return "send_error"

        page.wait_for_timeout(1000)

        submit_btn = page.locator('[data-qa="vacancy-response-submit-popup"]').first
        if submit_btn.count() == 0:
            submit_btn = page.locator('button:has-text("Отправить")').first

        if submit_btn.count() == 0:
            log("   ❌ Не нашёл кнопку отправки отклика.")
            add_to_manual_queue(link, title, company, "Не найдена кнопка отправки отклика")
            return "no_submit"

        try:
            submit_btn.click()
            page.wait_for_timeout(2500)
        except Exception as e:
            log(f"   ⚠️ Не удалось нажать 'Отправить': {e}")
            return "click_error"

        # Не считаем отклик отправленным, если hh.ru показал ошибку
        if check_send_error(page):
            log("   ❌ hh.ru сообщил об ошибке отправки.")
            add_to_manual_queue(link, title, company, "Ошибка отправки отклика")
            return "send_error"

        if not (
            verify_response_sent(page)
            or page.locator(CHAT_RESPONSE_BUTTON_QA).count() > 0
        ):
            log("   ⚠️ Нет подтверждения, что отклик ушёл. В ручную очередь.")
            add_to_manual_queue(link, title, company, "Нет подтверждения отправки отклика")
            return "no_submit"

        log("   ✅ ОТКЛИК ОТПРАВЛЕН (попап) с письмом!")
        add_sent_application(link, title, company, score, status="sent")
        return "sent"

    # --- НОВЫЙ ИНТЕРФЕЙС: отклик уходит сразу, письмо добавляется в чате ---
    if (
        page.locator(CHAT_RESPONSE_BUTTON_QA).count() > 0
        or has_visible(page, 'text=Вы откликнулись')
        or find_chat_frame(page, timeout_ms=2000)
    ):
        log("   💬 Отклик отправлен. Прикрепляю письмо в чате...")
        if send_letter_in_chat(page, letter, title, company):
            add_sent_application(link, title, company, score, status="sent")
            return "sent"

        log("   ⚠️ Отклик ушёл, но письмо не прикрепилось. В ручную очередь.")
        add_sent_application(link, title, company, score, status="no_letter")
        add_to_manual_queue(
            link, title, company, "Отклик отправлен без письма — прикрепи вручную в чате"
        )
        return "chat_failed"

    return "no_submit"


def build_queue(cover_letters, already_sent, limit):
    """Валидные письма без дублей, которые ещё не отправлены."""
    result = []
    seen = set(already_sent)
    for vacancy in cover_letters:
        if not isinstance(vacancy, dict):
            continue
        link = vacancy.get("link")
        letter = vacancy.get("cover_letter")
        if not link or not letter or link in seen:
            continue
        seen.add(link)
        result.append(vacancy)
        if len(result) >= limit:
            break
    return result


def retry_failed_letters(page, cover_letters):
    """Финальный проход по сегодняшним откликам без письма.

    Пробует прикрепить письмо ещё раз. При успехе статус меняется на sent,
    а вакансия убирается из ручной очереди. Возвращает число исправленных.
    """
    day = datetime.now().strftime("%Y-%m-%d")
    failed = get_no_letter_links(day=day)
    if not failed:
        return 0

    by_link = {}
    for vacancy in cover_letters or []:
        if isinstance(vacancy, dict) and vacancy.get("link"):
            by_link[vacancy["link"]] = vacancy

    candidates = [
        by_link[link]
        for link in failed
        if link in by_link and by_link[link].get("cover_letter")
    ]
    if not candidates:
        log("🔁 Есть отклики без письма, но текстов писем для них нет.")
        return 0

    log(f"\n{'='*60}")
    log(f"🔁 ПОВТОР: прикрепить письмо к {len(candidates)} откликам без письма")
    log(f"{'='*60}")

    fixed = 0
    for i, vacancy in enumerate(candidates, start=1):
        if page_is_closed(page):
            log("🛑 Браузер закрыт. Останавливаюсь.")
            break

        link = vacancy["link"]
        title = vacancy.get("title", "")
        company = vacancy.get("company", "")
        log(f"\n🔁 [{i}/{len(candidates)}] {title} - {company}")

        try:
            page.goto(link, wait_until="domcontentloaded")
            page.wait_for_timeout(random.randint(3000, 5000))
        except Exception as e:
            log(f"   ⚠️ Не удалось открыть вакансию: {e}")
            continue

        if check_captcha(page):
            log("   🚨 КАПЧА! Останавливаю повторную отправку.")
            break

        live_title = get_live_vacancy_title(page)
        if live_title and title and normalize_title(live_title) != normalize_title(title):
            log(f"   ⚠️ На hh.ru вакансия называется «{live_title}». Письмо не подходит.")
            continue

        if send_letter_in_chat(page, vacancy.get("cover_letter", ""), title, company):
            add_sent_application(
                link, title, company, vacancy.get("score", 0), status="sent"
            )
            remove_from_manual_queue(link)
            fixed += 1
            log("   ✅ Статус исправлен на sent, убрано из ручной очереди.")
        else:
            log("   ⚠️ Письмо снова не прикрепилось — оставляю в ручной очереди.")
            page.wait_for_timeout(random.randint(5000, 10000))

    return fixed


def main():
    init_db()

    cover_letters = try_read_json(COVER_LETTERS_FILE, None)
    if cover_letters is None:
        print("❌ Файл cover_letters.json не найден или поврежден.")
        sys.exit(1)
    if not isinstance(cover_letters, list):
        print("❌ cover_letters.json имеет неверный формат.")
        sys.exit(1)

    already_sent = get_sent_links()
    sent_today = get_today_sent_count()
    remaining = max(0, DAILY_LIMIT - sent_today)

    today = datetime.now().strftime("%Y-%m-%d")
    retry_links = get_no_letter_links(day=today)

    log(f"📊 Всего откликов в базе: {len(already_sent)}")
    log(f"📅 Отправлено сегодня: {sent_today}/{DAILY_LIMIT}")
    if retry_links:
        log(f"🔁 Сегодня без письма: {len(retry_links)} — будет повторная попытка.")

    if remaining == 0 and not retry_links:
        log("🛑 Дневной лимит исчерпан. Возвращайся завтра.")
        return

    to_send = build_queue(cover_letters, already_sent, remaining)
    if not to_send and not retry_links:
        log("🎉 Все письма из cover_letters.json уже обработаны.")
        return

    if to_send:
        log(f"📨 К отправке за запуск: {len(to_send)}")

    with sync_playwright() as p:
        try:
            browser, context = launch_context(p, headless=HEADLESS)
        except FileNotFoundError as e:
            log(f"🛑 {e}")
            sys.exit(1)

        try:
            page = context.new_page()

            log("🔐 Проверяю авторизацию...")
            auth = check_auth_on_main(page)
            if auth == "captcha":
                log("🛑 Капча на главной. Реши её вручную и запусти снова.")
                sys.exit(1)
            if auth != "ok":
                if page_is_closed(page):
                    log("🛑 Браузер закрыт. Останавливаюсь.")
                    sys.exit(1)
                log("🛑 Не удалось подтвердить авторизацию. Запусти hh_login.py.")
                sys.exit(1)

            sent_count = 0
            consecutive_errors = 0
            captcha_hit = False

            for i, vacancy in enumerate(to_send, start=1):
                if page_is_closed(page):
                    log("🛑 Браузер закрыт. Останавливаюсь.")
                    sys.exit(1)

                log(f"\n{'='*60}\n📨 [{i}/{len(to_send)}] {vacancy.get('title')} - {vacancy.get('company')}\n{'='*60}")

                try:
                    result = respond_to_vacancy(page, vacancy)
                except Exception as e:
                    if page_is_closed(page) or "has been closed" in str(e).lower():
                        log("🛑 Браузер закрыт. Останавливаюсь.")
                        sys.exit(1)
                    log(f"   ❌ Исключение: {e}")
                    result = "exception"

                if result == "sent":
                    sent_count += 1
                    consecutive_errors = 0
                elif result in ("already", "archived", "manual_questions"):
                    consecutive_errors = 0
                elif result == "captcha":
                    log("🛑 Капча. Останавливаюсь.")
                    captcha_hit = True
                    break
                elif result in ERROR_RESULTS:
                    consecutive_errors += 1
                    if consecutive_errors >= 3:
                        log("🛑 Три ошибки подряд. Стоп.")
                        break
                else:
                    consecutive_errors = 0

                if i < len(to_send):
                    # Архив/уже отправлено/чужое название — это просто пропуск,
                    # не тратим на них 5–15 минут.
                    if result in ("archived", "already", "title_mismatch"):
                        page.wait_for_timeout(random.randint(8000, 15000))
                    else:
                        random_delay()

            if not captcha_hit:
                sent_count += retry_failed_letters(page, cover_letters)

        except KeyboardInterrupt:
            log("\n🛑 СТОП по команде пользователя (Ctrl+C).")
            sys.exit(130)
        finally:
            try:
                browser.close()
            except Exception:
                pass

    log(f"\n✅ ГОТОВО. Отправлено за запуск: {sent_count}.")
    log(f"📅 Всего сегодня: {get_today_sent_count()}/{DAILY_LIMIT}. В базе: {len(get_sent_links())}")


if __name__ == "__main__":
    main()
