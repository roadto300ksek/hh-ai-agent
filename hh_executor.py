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


def send_letter_in_chat(page, letter):
    """Отправляет письмо в чате и проверяет, что hh.ru не показал ошибку."""
    log("   💬 Пытаюсь отправить письмо в чате...")
    try:
        add_btn = page.locator('text=Добавить сопроводительное').first
        if add_btn.count() > 0 and add_btn.is_visible():
            log("   🖱️ Нажимаю 'Добавить сопроводительное'...")
            add_btn.click()
            page.wait_for_timeout(2500)

        chat_input = page.locator('textarea').first
        if chat_input.count() == 0:
            chat_input = page.locator('div[contenteditable="true"]').first
        if chat_input.count() == 0:
            chat_input = page.locator('[data-qa="chatik-textarea"]').first

        if chat_input.count() == 0:
            log("   ❌ Не нашел поле ввода в чате.")
            take_screenshot(page, "chat_no_input")
            return False

        log("   ⌨️ Ввожу текст...")
        chat_input.click()
        page.wait_for_timeout(500)
        chat_input.fill("")
        page.wait_for_timeout(200)
        chat_input.fill(letter)
        page.wait_for_timeout(1000)

        # Отправляем по Enter (работает в 99% чатов hh)
        page.keyboard.press("Enter")
        page.wait_for_timeout(2000)

        if check_send_error(page):
            log("   ❌ hh.ru сообщил об ошибке отправки в чате.")
            take_screenshot(page, "chat_send_error")
            return False

        log("   ✅ Письмо отправлено в чат.")
        return True
    except Exception as e:
        log(f"   ⚠️ Ошибка в чате: {e}")
        take_screenshot(page, "chat_exception")
        return False


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

    # --- ПРОВЕРКА 1: МЫ УЖЕ В ЧАТЕ? (например, ты зашел вручную) ---
    if has_visible(page, 'text=Добавить сопроводительное') or has_visible(page, 'div[contenteditable="true"]'):
        log("   💬 Обнаружен интерфейс чата.")
        if send_letter_in_chat(page, letter):
            add_sent_application(link, title, company, score, status="sent")
            return "sent"
        add_to_manual_queue(link, title, company, "Не удалось отправить письмо в чате")
        return "chat_failed"

    # --- ПРОВЕРКА 2: МЫ УЖЕ ОТКЛИКАЛИСЬ РАНЕЕ? ---
    if has_visible(page, 'a:has-text("Перейти в чат")') or has_visible(page, 'text=Вы откликнулись'):
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

    # --- ПОСЛЕ КЛИКА: ЕСЛИ ОТКРЫЛСЯ ЧАТ ---
    if has_visible(page, 'text=Добавить сопроводительное') or has_visible(page, 'div[contenteditable="true"]'):
        log("   💬 Клик открыл чат. Отправляю письмо...")
        if send_letter_in_chat(page, letter):
            add_sent_application(link, title, company, score, status="sent")
            return "sent"
        add_to_manual_queue(link, title, company, "Не удалось отправить письмо в чате")
        return "chat_failed"

    # --- КЛАССИЧЕСКИЙ ПОПАП ---
    log("   📋 Классический попап. Ищу поле для письма...")
    if check_questions(page):
        log("   ⚠️ Вопросы работодателя. В ручную очередь.")
        add_to_manual_queue(link, title, company, "Требуются ответы на вопросы")
        return "manual_questions"

    letter_field = page.locator('[data-qa="vacancy-response-popup-form-letter-input"]').first
    if letter_field.count() == 0:
        toggle_btn = page.locator('[data-qa="vacancy-response-letter-toggle"]').first
        if toggle_btn.count() > 0:
            toggle_btn.click()
            page.wait_for_timeout(1500)
            letter_field = page.locator('[data-qa="vacancy-response-popup-form-letter-input"]').first

    if letter_field.count() > 0:
        try:
            letter_field.click()
            letter_field.fill(letter)
            log("   ✍️  Письмо вставлено в попап")
        except Exception:
            pass

    page.wait_for_timeout(1500)

    submit_btn = page.locator('[data-qa="vacancy-response-submit-popup"]').first
    if submit_btn.count() == 0:
        submit_btn = page.locator('button:has-text("Отправить")').first

    if submit_btn.count() > 0:
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

        log("   ✅ ОТКЛИК ОТПРАВЛЕН (попап)!")
        add_sent_application(link, title, company, score, status="sent")
        return "sent"

    if verify_response_sent(page):
        add_sent_application(link, title, company, score, status="sent")
        return "sent"

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
