import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

def run_step(script_name, description):
    print(f"\n{'='*70}")
    print(f"🚀 ЭТАП: {description}")
    print(f"📜 Скрипт: {script_name}")
    print(f"{'='*70}\n")
    
    try:
        # Запускаем скрипт как отдельный процесс, используя тот же Python
        subprocess.run([sys.executable, script_name], check=True)
    except subprocess.CalledProcessError:
        print(f"\n❌ ОШИБКА при выполнении {script_name}.")
        print("🛑 Цепочка остановлена. Исправь ошибку и запусти заново.")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n🛑 Ты прервал выполнение {script_name}.")
        print("🛑 Цепочка остановлена.")
        sys.exit(1)

def main():
    print("🤖 ЗАПУСК ПОЛНОЙ ЦЕПОЧКИ AI-АГЕНТОВ ДЛЯ ПОИСКА РАБОТЫ")
    print("⚠️  Внимание: если твоя сессия hh.ru протухла, сначала запусти hh_login.py")
    
    # Этап 1: Сканер вакансий
    run_step("hh_scanner_multi.py", "СБОР СВЕЖИХ ВАКАНСИЙ (Playwright)")
    
    # Этап 2: Анализатор
    run_step("hh_analyzer.py", "АНАЛИЗ ВАКАНСИЙ ЧЕРЕЗ DEEPSEEK (Оценка 0-100)")
    
    # Этап 3: Копирайтер
    run_step("hh_writer.py", "ГЕНЕРАЦИЯ ПИСЕМ ДЛЯ ТОП-ВАКАНСИЙ")
    
    # Этап 4: Исполнитель
    run_step("hh_executor.py", "ОТПРАВКА ОТКЛИКОВ (С паузами и защитой от бана)")
    
    print(f"\n{'='*70}")
    print("🎉 ВСЯ ЦЕПОЧКА УСПЕШНО ЗАВЕРШЕНА! Можешь идти отдыхать.")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()