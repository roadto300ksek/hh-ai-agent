import subprocess
import sys
import time

from paths import (
    ANALYZED_FILE,
    BASE_DIR,
    COVER_LETTERS_FILE,
    STATE_FILE,
    VACANCIES_FILE,
)
from utils import configure_stdout

configure_stdout()

STEPS = [
    ("hh_scanner_multi.py", "СБОР СВЕЖИХ ВАКАНСИЙ (Playwright)", None),
    ("hh_analyzer.py", "АНАЛИЗ ВАКАНСИЙ ЧЕРЕЗ DEEPSEEK (Оценка 0-100)", VACANCIES_FILE),
    ("hh_writer.py", "ГЕНЕРАЦИЯ ПИСЕМ ДЛЯ ТОП-ВАКАНСИЙ", ANALYZED_FILE),
    ("hh_executor.py", "ОТПРАВКА ОТКЛИКОВ (Паузы и защита от бана)", COVER_LETTERS_FILE),
]


def run_step(script_name, description, required_file=None):
    print(f"\n{'='*70}")
    print(f"🚀 ЭТАП: {description}")
    print(f"📜 Скрипт: {script_name}")
    print(f"{'='*70}\n")

    if required_file is not None and not required_file.exists():
        print(f"❌ Нет файла {required_file.name}. Предыдущий этап не дал результата.")
        print("🛑 Цепочка остановлена.")
        sys.exit(1)

    started = time.time()
    try:
        subprocess.run(
            [sys.executable, str(BASE_DIR / script_name)],
            check=True,
            cwd=str(BASE_DIR),
        )
    except subprocess.CalledProcessError:
        print(f"\n❌ ОШИБКА при выполнении {script_name}.")
        print("🛑 Цепочка остановлена. Исправь ошибку и запусти заново.")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n🛑 Ты прервал выполнение {script_name}.")
        print("🛑 Цепочка остановлена.")
        sys.exit(1)

    print(f"⏱️  Этап занял {time.time() - started:.1f} сек.")


def main():
    print("🤖 ЗАПУСК ПОЛНОЙ ЦЕПОЧКИ AI-АГЕНТОВ ДЛЯ ПОИСКА РАБОТЫ")

    if not STATE_FILE.exists():
        print("❌ Файл сессии hh_state.json не найден.")
        print("🛑 Сначала запусти hh_login.py и войди в аккаунт.")
        sys.exit(1)

    print("⚠️  Если сессия hh.ru протухла, сначала запусти hh_login.py")

    for script_name, description, required_file in STEPS:
        run_step(script_name, description, required_file)

    print(f"\n{'='*70}")
    print("🎉 ВСЯ ЦЕПОЧКА УСПЕШНО ЗАВЕРШЕНА! Можешь идти отдыхать.")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
