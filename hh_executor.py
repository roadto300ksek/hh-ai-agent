from playwright.sync_api import sync_playwright
import json
import time
import random
import os
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(line_buffering=True)

# ============================================
# НАСТРОЙКИ
# ============================================
DAILY_LIMIT = 50
MIN_DELAY_SEC = 300
MAX_DELAY_SEC = 900
HEADLESS = False
SHOT_DIR = "executor_screenshots"
MANUAL_QUEUE_FILE = "manual_queue.json"
# ============================================

LOG_FILE = "sent_log.json"


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def log(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def add_to_manual_queue(manual_queue, link, title, company, reason):
    """Добавляет вакансию в ручную очередь, только если её там ещё нет."""
    for item in manual_queue:
        if item.get("link") == link:
            return False  # Уже есть
    manual_queue.append({
        "link": link,
        "title": title,
        "company": company,
        "reason": reason
    })
    return True


def random_delay():
    delay = random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC)
    minutes = delay / 60
    log(f"⏳ Пауза {minutes:.1f} мин перед следующим откликом...")
    log("   (можно остановить Ctrl+C, если нужно)")
    try:
        time.sleep(delay)
    except KeyboardInterrupt:
        log("🛑 Пауза прервана пользователем. Продолжаю работу.")
        raise


def check_captcha(page):
    if page.locator('iframe[src*="captcha"]').count() > 0:
        return True
    if "captcha" in page.url.lower():
        return True
    return False


def check_auth_on_main(page):
    try:
        page.goto("https://hh.ru", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
    except Exception as e:
        log(f"   ⚠️ Не удалось открыть hh.ru: {e}")
        return False

    auth_markers = [
        '[data-qa="mainmenu_applicantProfile"]',
        '[data-qa="mainmenu_myResumes"]',
        'a[href="/applicant/resumes"]',
        'a[href*="applicant/resumes"]',
        '[data-qa="account-menu-button"]',
    ]
    for marker in auth_markers:
        if page.locator(marker).count() > 0:
            log(f"   ✅ Авторизация подтверждена (найден '{marker}')")
            return True

    if page.locator('text=Мои резюме').count() > 0 or page.locator('text=Резюме и профиль').count() > 0:
        log("   ✅ Авторизация подтверждена (по тексту меню)")
        return True

    return False


def is_already_applied(page):
    """Улучшенная проверка: отклик уже отправлен?"""
    # Признак 1: кнопка "Перейти в чат" (значит отклик уже был)
    if page.locator('a:has-text("Перейти в чат")').count() > 0:
        return True
    if page.locator('button:has-text("Перейти в чат")').count() > 0:
        return True

    # Признак 2: кнопка "Оставить отзыв" (тоже значит отклик был)
    if page.locator('a:has-text("Оставить отзыв")').count() > 0:
        return True
    if page.locator('button:has-text("Оставить отзыв")').count() > 0:
        return True

    # Признак 3: текст "Вы откликнулись" или "Отклик отправлен"
    if page.locator('text=Вы откликнулись').count() > 0:
        return True
    if page.locator('text=Отклик отправлен').count() > 0:
        return True

    # Признак 4: старая проверка через href
    if page.locator('[data-qa="vacancy-response-link-top"][href*="already"]').count() > 0:
        return True

    # Признак 5: бейдж "Отклик отправлен" на странице
    if page.locator('[data-qa="vacancy-response-link-top"]').count() == 0 and \
       page.locator('[data-qa="vacancy-response-link-bottom"]').count() == 0 and \
       page.locator('a:has-text("Откликнуться")').count() == 0 and \
       page.locator('button:has-text("Откликнуться")').count() == 0:
        # Нет ни одной кнопки "Откликнуться" — значит либо уже откликнулись, либо что-то другое
        return True

    return False


def check_questions(page):
    if page.locator('[data-qa="vacancy-response-question"]').count() > 0:
        return True
    if page.locator('button:has-text("Ответить на вопросы")').count() > 0:
        return True
    if page.locator('[data-qa="task-question"]').count() > 0:
        return True
    return False


def verify_response_sent(page):
    """Проверяет, ушёл ли отклик на самом деле."""
    if page.locator('text=Отклик отправлен').count() > 0:
        return True
    if page.locator('[data-qa="vacancy-response-success"]').count() > 0:
        return True
    if page.locator('a:has-text("Перейти в чат")').count() > 0:
        return True
    if page.locator('button:has-text("Перейти в чат")').count() > 0:
        return True
    if page.locator('a:has-text("Оставить отзыв")').count() > 0:
        return True
    if page.locator('[data-qa="chatik"]').count() > 0:
        return True
    if page.locator('text=Вы откликнулись').count() > 0:
        return True
    return False


def respond_to_vacancy(page, vacancy, manual_queue):
    link = vacancy["link"]
    title = vacancy["title"]
    company = vacancy["company"]
    letter = vacancy["cover_letter"]

    log(f"🌐 Открываю: {link}")
    page.goto(link, wait_until="domcontentloaded")
    page.wait_for_timeout(random.randint(3000, 6000))

    if check_captcha(page):
        log("   🚨 КАПЧА! Останавливаю работу.")
        return "captcha"

    # === УЛУЧШЕННАЯ ПРОВЕРКА "УЖЕ ОТКЛИКАЛИСЬ" ===
    if is_already_applied(page):
        log(f"   ⏭️  Уже откликались ранее (обнаружены признаки отклика).")
        return "already"

    # --- КНОПКА "ОТКЛИКНУТЬСЯ" ---
    respond_btn = page.locator('[data-qa="vacancy-response-link-top"]').first
    if respond_btn.count() == 0:
        respond_btn = page.locator('[data-qa="vacancy-response-link-bottom"]').first
    if respond_btn.count() == 0:
        respond_btn = page.locator('a:has-text("Откликнуться")').first
    if respond_btn.count() == 0:
        respond_btn = page.locator('button:has-text("Откликнуться")').first

    if respond_btn.count() == 0:
        log(f"   ❌ Кнопка 'Откликнуться' не найдена.")
        page.screenshot(path=f"{SHOT_DIR}/no_button_{link.split('/')[-1]}.png")
        return "no_button"

    try:
        respond_btn.click()
    except Exception as e:
        log(f"   ❌ Клик не удался: {e}")
        return "click_error"

    page.wait_for_timeout(random.randint(3000, 5000))

    if check_captcha(page):
        log("   🚨 КАПЧА после клика! Стоп.")
        return "captcha"

    # ============================================================
    # ВАРИАНТ 1: ЧАТ-ИНТЕРФЕЙС
    # ============================================================
    chat_field = page.locator('[data-qa="chatik-textarea"]').first
    if chat_field.count() == 0:
        chat_field = page.locator('textarea[placeholder*="сопроводительное"]').first
    if chat_field.count() == 0:
        chat_field = page.locator('textarea[placeholder*="Введите текст"]').first
    if chat_field.count() == 0:
        chat_field = page.locator('textarea[placeholder*="Сообщение"]').first
    if chat_field.count() == 0:
        chat_field = page.locator('[contenteditable="true"][data-qa*="chat"]').first

    if chat_field.count() > 0:
        log("   💬 Обнаружен чат-интерфейс. Пытаюсь вставить письмо...")
        try:
            chat_field.click()
            page.wait_for_timeout(500)
            chat_field.fill(letter)
            log(f"   ✍️  Письмо вставлено в чат ({len(letter)} символов)")
            page.wait_for_timeout(random.randint(1000, 2000))

            send_btn = page.locator('[data-qa="chatik-submit-button"]').first
            if send_btn.count() == 0:
                send_btn = page.locator('[data-qa="chatik-submit"]').first
            if send_btn.count() == 0:
                send_btn = page.locator('button[type="submit"]').first
            if send_btn.count() == 0:
                send_btn = page.locator('button:has(svg)').last

            if send_btn.count() > 0:
                try:
                    send_btn.click()
                    page.wait_for_timeout(random.randint(2000, 4000))
                except Exception as e:
                    log(f"   ⚠️  Не удалось нажать кнопку отправки: {e}")
        except Exception as e:
            log(f"   ⚠️  Не удалось вставить письмо в чат: {e}")

        if verify_response_sent(page):
            log(f"   ✅ ОТКЛИК ОТПРАВЛЕН (проверено по факту)!")
            return "sent"
        else:
            log(f"   ⚠️  Признаков отправки нет. Возможно, отклик уже был.")
            return "already"

    # ============================================================
    # ВАРИАНТ 2: КЛАССИЧЕСКИЙ ПОПАП
    # ============================================================
    log("   📋 Классический попап. Ищу поле для письма...")

    if check_questions(page):
        log("   ⚠️ Вопросы работодателя. В ручную очередь.")
        added = add_to_manual_queue(manual_queue, link, title, company,
                                    "Требуются ответы на вопросы работодателя")
        if added:
            log("   📝 Добавлено в ручную очередь.")
        else:
            log("   📝 Уже было в ручной очереди.")
        close_btn = page.locator('[data-qa="modal-close"]').first
        if close_btn.count() > 0:
            try:
                close_btn.click()
            except Exception:
                pass
        return "manual_questions"

    letter_field = page.locator('[data-qa="vacancy-response-popup-form-letter-input"]').first
    if letter_field.count() == 0:
        toggle_btn = page.locator('[data-qa="vacancy-response-letter-toggle"]').first
        if toggle_btn.count() > 0:
            try:
                toggle_btn.click()
                page.wait_for_timeout(1500)
                letter_field = page.locator('[data-qa="vacancy-response-popup-form-letter-input"]').first
                log("   🔄 Открыл поле для сопроводительного письма")
            except Exception as e:
                log(f"   ⚠️  Не открылось поле: {e}")

    if letter_field.count() > 0:
        try:
            letter_field.click()
            page.wait_for_timeout(500)
            letter_field.fill(letter)
            log(f"   ✍️  Письмо вставлено ({len(letter)} символов)")
        except Exception as e:
            log(f"   ⚠️  Не вставилось письмо: {e}")

    page.wait_for_timeout(random.randint(1500, 3000))

    submit_btn = page.locator('[data-qa="vacancy-response-submit-popup"]').first
    if submit_btn.count() == 0:
        submit_btn = page.locator('button:has-text("Отправить")').first
    if submit_btn.count() == 0:
        submit_btn = page.locator('button:has-text("Откликнуться")').first

    if submit_btn.count() > 0:
        try:
            submit_btn.click()
            page.wait_for_timeout(random.randint(2000, 4000))
            log(f"   ✅ ОТКЛИК ОТПРАВЛЕН!")
            return "sent"
        except Exception as e:
            log(f"   ⚠️  Не удалось нажать 'Отправить': {e}")

    if verify_response_sent(page):
        log(f"   ✅ ОТКЛИК ОТПРАВЛЕН (проверено по факту)!")
        return "sent"

    log(f"   ❌ Отклик не ушёл.")
    page.screenshot(path=f"{SHOT_DIR}/no_submit_{link.split('/')[-1]}.png")
    return "no_submit"


def main():
    os.makedirs(SHOT_DIR, exist_ok=True)

    if not os.path.exists("cover_letters.json"):
        print("❌ Файл cover_letters.json не найден. Сначала запусти hh_writer.py")
        return

    cover_letters = load_json("cover_letters.json", [])
    sent_log = load_json(LOG_FILE, {"sent_links": [], "history": []})
    manual_queue = load_json(MANUAL_QUEUE_FILE, [])
    already_sent_links = set(sent_log.get("sent_links", []))

    # Чистим дубликаты в manual_queue на старте
    seen_links = set()
    clean_queue = []
    for item in manual_queue:
        if item.get("link") not in seen_links:
            seen_links.add(item.get("link"))
            clean_queue.append(item)
    manual_queue = clean_queue
    save_json(MANUAL_QUEUE_FILE, manual_queue)

    recent_sent = [h for h in sent_log.get("history", [])
                   if datetime.fromisoformat(h["sent_at"]) > datetime.now() - timedelta(hours=24)]

    if len(recent_sent) >= DAILY_LIMIT:
        log(f"🛑 Достигнут дневной лимит откликов ({DAILY_LIMIT}).")
        return

    remaining_limit = DAILY_LIMIT - len(recent_sent)
    log(f"📊 Отправлено за последние 24 часа: {len(recent_sent)}. Осталось: {remaining_limit}")

    to_send = [v for v in cover_letters if v["link"] not in already_sent_links]
    if not to_send:
        log("🎉 Все письма уже отправлены.")
        return

    to_send = to_send[:remaining_limit]

    log(f"📋 Всего писем: {len(cover_letters)}")
    log(f"📤 Уже отправлено: {len(already_sent_links)}")
    log(f"✉️  К отправке сейчас: {len(to_send)}")
    log("")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = browser.new_context(
            storage_state="hh_state.json",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )

        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        page = context.new_page()

        log("🔐 Проверяю авторизацию на главной hh.ru...")
        if not check_auth_on_main(page):
            log("🛑 Не удалось подтвердить авторизацию.")
            log("   Запусти hh_login.py, залогинься заново, сохрани сессию — и перезапусти меня.")
            try:
                browser.close()
            except Exception:
                pass
            return

        sent_count = 0
        consecutive_errors = 0

        try:
            for i, vacancy in enumerate(to_send, start=1):
                log(f"\n{'='*60}")
                log(f"📨 [{i}/{len(to_send)}] {vacancy['title']} — {vacancy['company']}")
                log(f"{'='*60}")

                result = respond_to_vacancy(page, vacancy, manual_queue)

                if result == "sent":
                    sent_log["sent_links"].append(vacancy["link"])
                    sent_log["history"].append({
                        "link": vacancy["link"],
                        "title": vacancy["title"],
                        "company": vacancy["company"],
                        "score": vacancy["score"],
                        "sent_at": datetime.now().isoformat(),
                    })
                    save_json(LOG_FILE, sent_log)
                    sent_count += 1
                    consecutive_errors = 0
                elif result == "already":
                    # Тоже записываем в sent_log, чтобы в будущем не тратить время
                    sent_log["sent_links"].append(vacancy["link"])
                    sent_log["history"].append({
                        "link": vacancy["link"],
                        "title": vacancy["title"],
                        "company": vacancy["company"],
                        "score": vacancy["score"],
                        "sent_at": datetime.now().isoformat(),
                        "note": "already_applied"
                    })
                    save_json(LOG_FILE, sent_log)
                    consecutive_errors = 0
                elif result == "captcha":
                    log("🛑 Капча. Останавливаюсь. Пройди вручную и перезапусти.")
                    break
                elif result in ("no_button", "no_submit", "click_error", "submit_error"):
                    consecutive_errors += 1
                    log(f"   ⚠️  Ошибка подряд: {consecutive_errors}")
                    if consecutive_errors >= 3:
                        log("🛑 Три ошибки подряд. Что-то сломалось. Останавливаюсь.")
                        break
                else:
                    consecutive_errors = 0

                save_json(MANUAL_QUEUE_FILE, manual_queue)

                if i < len(to_send):
                    random_delay()

        except KeyboardInterrupt:
            log("\n🛑 СТОП по команде пользователя (Ctrl+C). Сохраняю прогресс...")
            save_json(LOG_FILE, sent_log)
            save_json(MANUAL_QUEUE_FILE, manual_queue)

        try:
            browser.close()
        except Exception:
            pass

    log(f"\n{'='*60}")
    log(f"✅ ГОТОВО.")
    log(f"📤 Отправлено за этот запуск: {sent_count}")
    log(f"📊 Всего в базе: {len(sent_log['sent_links'])}")
    log(f"📋 В ручной очереди: {len(manual_queue)}")
    log(f"📁 Лог: {LOG_FILE}")
    log(f"📁 Ручная очередь: {MANUAL_QUEUE_FILE}")
    log(f"{'='*60}")


if __name__ == "__main__":
    main()