import random
import sys
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

from database import (
    add_sent_application,
    add_to_manual_queue,
    get_sent_links,
    get_today_sent_count,
    init_db,
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


def send_letter_in_chat(page, letter, title="", company=""):
    """Прикрепляет сопроводительное письмо к уже отправленному отклику.

    Работает внутри iframe chatik.hh.ru. Возвращает True только после того,
    как текст письма появился в переписке (или исчезла плашка «Без письма»).
    """
    log("   💬 Открываю чат отклика...")
    frame = open_chat(page)
    if frame is None:
        log("   ❌ Чат hh.ru не открылся.")
        take_screenshot(page, "chat_not_opened")
        return False

    if (title or company) and not chat_matches_vacancy(frame, title, company):
        page.wait_for_timeout(1500)
        frame = find_chat_frame(page, timeout_ms=1000) or frame
        if not chat_matches_vacancy(frame, title, company):
            log("   ❌ Открылся чат другой вакансии. Письмо не отправляю.")
            take_screenshot(page, "chat_wrong_vacancy")
            return False

    before = chat_letter_state(frame, letter) or {
        "snippet": False,
        "no_letter": False,
        "add_button": 0,
    }
    if before["snippet"]:
        log("   ✅ Письмо уже прикреплено к отклику.")
        return True

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

        textarea = frame.locator(CHAT_TEXTAREA_QA).first
        if textarea.count() == 0 or not textarea.is_visible():
            log("   ❌ Не нашёл поле ввода письма в чате.")
            take_screenshot(page, "chat_no_input")
            return False

        log("   ⌨️ Ввожу текст письма...")
        textarea.click()
        page.wait_for_timeout(300)
        textarea.fill(letter)
        page.wait_for_timeout(1000)

        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            send_btn = frame.locator(CHAT_SEND_QA).first
            if send_btn.count() > 0 and send_btn.is_visible():
                break
            page.wait_for_timeout(300)
            frame = find_chat_frame(page, timeout_ms=500) or frame
        else:
            send_btn = frame.locator(CHAT_SEND_QA).first

        if send_btn.count() == 0 or not send_btn.is_visible():
            log("   ❌ Кнопка отправки письма не появилась.")
            take_screenshot(page, "chat_no_send_button")
            return False

        send_btn.click()
        log("   📤 Письмо отправлено, проверяю, что оно прикрепилось...")
        page.wait_for_timeout(2500)

        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            frame = find_chat_frame(page, timeout_ms=500) or frame
            after = chat_letter_state(frame, letter)
            if after is None:
                page.wait_for_timeout(700)
                continue
            if after["snippet"]:
                log("   ✅ Письмо прикреплено к отклику.")
                return True
            if (
                not after["no_letter"]
                and after["add_button"] == 0
                and (before["no_letter"] or before["add_button"] > 0)
            ):
                log("   ✅ Письмо прикреплено к отклику.")
                return True
            page.wait_for_timeout(700)

        log("   ❌ Не удалось подтвердить, что письмо прикрепилось.")
        take_screenshot(page, "chat_not_confirmed")
        return False
    except Exception as e:
        log(f"   ⚠️ Ошибка при отправке письма в чате: {e}")
        take_screenshot(page, "chat_exception")
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

    log(f"📊 Всего откликов в базе: {len(already_sent)}")
    log(f"📅 Отправлено сегодня: {sent_today}/{DAILY_LIMIT}")

    if remaining == 0:
        log("🛑 Дневной лимит исчерпан. Возвращайся завтра.")
        return

    to_send = build_queue(cover_letters, already_sent, remaining)
    if not to_send:
        log("🎉 Все письма из cover_letters.json уже обработаны.")
        return

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
