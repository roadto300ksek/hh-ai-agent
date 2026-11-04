from playwright.sync_api import sync_playwright
import json
import time
import random
import os
import sys
from datetime import datetime, timedelta
from database import init_db, get_sent_links, add_sent_application, get_manual_queue, add_to_manual_queue

try:
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
except Exception:
    pass

# ============================================
# НАСТРОЙКИ
# ============================================
DAILY_LIMIT = 50
MIN_DELAY_SEC = 300
MAX_DELAY_SEC = 900
HEADLESS = False
SHOT_DIR = "executor_screenshots"
# ============================================

def log(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

def random_delay():
    delay = random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC)
    minutes = delay / 60
    log(f"⏳ Пауза {minutes:.1f} мин перед следующим откликом...")
    try:
        time.sleep(delay)
    except KeyboardInterrupt:
        log("🛑 Пауза прервана пользователем.")
        raise

def check_captcha(page):
    if page.locator('iframe[src*="captcha"]').count() > 0 or "captcha" in page.url.lower():
        return True
    return False

def check_auth_on_main(page):
    try:
        page.goto("https://hh.ru", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
    except Exception:
        return False

    auth_markers = [
        '[data-qa="mainmenu_applicantProfile"]', '[data-qa="mainmenu_myResumes"]',
        'a[href="/applicant/resumes"]', '[data-qa="account-menu-button"]'
    ]
    for marker in auth_markers:
        if page.locator(marker).count() > 0:
            return True
    if page.locator('text=Мои резюме').count() > 0:
        return True
    return False

def check_questions(page):
    if page.locator('[data-qa="vacancy-response-question"]').count() > 0: return True
    if page.locator('button:has-text("Ответить на вопросы")').count() > 0: return True
    return False

def verify_response_sent(page):
    if page.locator('text=Отклик отправлен').count() > 0: return True
    if page.locator('text=Вы откликнулись').count() > 0: return True
    return False

# Тексты, которыми hh.ru сообщает, что отклик НЕ ушел
SEND_ERROR_MARKERS = [
    'text=Не удалось отправить',
    'text=Произошла ошибка',
    'text=Попробуйте ещё раз',
    'text=Отклик не отправлен',
]

def check_send_error(page):
    for marker in SEND_ERROR_MARKERS:
        if page.locator(marker).count() > 0:
            return True
    return False

def send_letter_in_chat(page, letter):
    """Агрессивная функция отправки письма в чате"""
    log("   💬 Пытаюсь отправить письмо в чате...")
    try:
        # 1. Ждем кнопку "Добавить сопроводительное"
        add_btn = page.locator('text=Добавить сопроводительное').first
        if add_btn.count() > 0 and add_btn.is_visible():
            log("   🖱️ Нажимаю 'Добавить сопроводительное'...")
            add_btn.click()
            page.wait_for_timeout(2500) # Даем время форме открыться

        # 2. Ищем поле ввода (textarea или contenteditable)
        chat_input = page.locator('textarea').first
        if chat_input.count() == 0:
            chat_input = page.locator('div[contenteditable="true"]').first
        if chat_input.count() == 0:
            chat_input = page.locator('[data-qa="chatik-textarea"]').first

        if chat_input.count() > 0:
            log("   ⌨️ Ввожу текст...")
            chat_input.click()
            page.wait_for_timeout(500)
            chat_input.fill("") # Очищаем
            page.wait_for_timeout(200)
            chat_input.fill(letter)
            page.wait_for_timeout(1000)
            
            # Отправляем по Enter (работает в 99% чатов hh)
            page.keyboard.press("Enter")
            page.wait_for_timeout(2000)
            
            log("   ✅ ПИСЬМО ОТПРАВЛЕНО В ЧАТ!")
            return True
        else:
            log("   ❌ Не нашел поле ввода в чате.")
            page.screenshot(path=f"{SHOT_DIR}/chat_no_input_{datetime.now().strftime('%H%M%S')}.png")
            return False
    except Exception as e:
        log(f"   ⚠️ Ошибка в чате: {e}")
        return False

def respond_to_vacancy(page, vacancy):
    link = vacancy["link"]
    title = vacancy["title"]
    company = vacancy["company"]
    letter = vacancy["cover_letter"]
    score = vacancy.get("score", 0)

    log(f"🌐 Открываю: {link}")
    page.goto(link, wait_until="domcontentloaded")
    page.wait_for_timeout(random.randint(3000, 5000))

    if check_captcha(page):
        log("   🚨 КАПЧА! Останавливаю работу.")
        return "captcha"

    if page.locator('text=Вакансия в архиве').count() > 0:
        log(f"   ⏭️  Вакансия в архиве. Пропуск.")
        add_sent_application(link, title, company, score, status="archived")
        return "archived"

    # --- ПРОВЕРКА 1: МЫ УЖЕ В ЧАТЕ? (например, ты зашел вручную) ---
    if page.locator('text=Добавить сопроводительное').count() > 0 or page.locator('div[contenteditable="true"]').count() > 0:
        log("   💬 Обнаружен интерфейс чата.")
        if send_letter_in_chat(page, letter):
            add_sent_application(link, title, company, score, status="sent")
            return "sent"
        log("   ⚠️ Письмо в чат отправить не удалось.")
        add_to_manual_queue(link, title, company, "Не удалось отправить письмо в чате")
        return "chat_failed"

    # --- ПРОВЕРКА 2: МЫ УЖЕ ОТКЛИКАЛИСЬ РАНЕЕ? ---
    if page.locator('a:has-text("Перейти в чат")').count() > 0 or page.locator('text=Вы откликнулись').count() > 0:
        log(f"   ⏭️  Уже откликались ранее.")
        add_sent_application(link, title, company, score, status="already")
        return "already"

    # --- ИЩЕМ КНОПКУ "ОТКЛИКНУТЬСЯ" ---
    respond_btn = page.locator('[data-qa="vacancy-response-link-top"]').first
    if respond_btn.count() == 0: respond_btn = page.locator('a:has-text("Откликнуться")').first
    if respond_btn.count() == 0: respond_btn = page.locator('button:has-text("Откликнуться")').first

    if respond_btn.count() == 0:
        log(f"   ❌ Кнопка 'Откликнуться' не найдена.")
        return "no_button"

    try:
        respond_btn.click()
    except Exception:
        return "click_error"

    page.wait_for_timeout(random.randint(4000, 6000))

    if check_captcha(page):
        return "captcha"

    # --- ПОСЛЕ КЛИКА: ЕСЛИ ОТКРЫЛСЯ ЧАТ ---
    if page.locator('text=Добавить сопроводительное').count() > 0 or page.locator('div[contenteditable="true"]').count() > 0:
        log("   💬 Клик открыл чат. Отправляю письмо...")
        if send_letter_in_chat(page, letter):
            add_sent_application(link, title, company, score, status="sent")
            return "sent"
        log("   ⚠️ Письмо в чат отправить не удалось.")
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
        except Exception: pass

    page.wait_for_timeout(1500)

    submit_btn = page.locator('[data-qa="vacancy-response-submit-popup"]').first
    if submit_btn.count() == 0: submit_btn = page.locator('button:has-text("Отправить")').first

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

        log(f"   ✅ ОТКЛИК ОТПРАВЛЕН (попап)!")
        add_sent_application(link, title, company, score, status="sent")
        return "sent"

    if verify_response_sent(page):
        add_sent_application(link, title, company, score, status="sent")
        return "sent"

    return "no_submit"

def main():
    os.makedirs(SHOT_DIR, exist_ok=True)
    init_db()

    if not os.path.exists("cover_letters.json"):
        print("❌ Файл cover_letters.json не найден.")
        return

    with open("cover_letters.json", "r", encoding="utf-8") as f:
        cover_letters = json.load(f)

    already_sent_links = get_sent_links()
    log(f"📊 Всего откликов в базе: {len(already_sent_links)}")

    to_send = [v for v in cover_letters if v["link"] not in already_sent_links]
    if not to_send:
        log("🎉 Все письма из cover_letters.json уже обработаны.")
        return

    to_send = to_send[:DAILY_LIMIT]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        context = browser.new_context(
            storage_state="hh_state.json",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}, locale="ru-RU", timezone_id="Europe/Moscow"
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        page = context.new_page()

        log("🔐 Проверяю авторизацию...")
        if not check_auth_on_main(page):
            log("🛑 Не удалось подтвердить авторизацию.")
            browser.close()
            return

        sent_count = 0
        consecutive_errors = 0

        try:
            for i, vacancy in enumerate(to_send, start=1):
                log(f"\n{'='*60}\n📨 [{i}/{len(to_send)}] {vacancy['title']} - {vacancy['company']}\n{'='*60}")
                
                result = respond_to_vacancy(page, vacancy)

                if result == "sent":
                    sent_count += 1
                    consecutive_errors = 0
                elif result in ("already", "archived"):
                    consecutive_errors = 0
                elif result == "captcha":
                    log("🛑 Капча. Останавливаюсь.")
                    break
                elif result in ("no_button", "no_submit", "click_error", "chat_failed", "send_error"):
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

        try: browser.close()
        except: pass

    log(f"\n✅ ГОТОВО. Отправлено за запуск: {sent_count}. Всего в базе: {len(get_sent_links())}")

if __name__ == "__main__":
    main()