"""Мелкие общие helpers: вывод, JSON, проверки страницы."""
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def configure_stdout(line_buffering=False):
    """UTF-8 в консоли: иначе Windows падает на emoji при перенаправлении вывода."""
    try:
        sys.stdout.reconfigure(
            encoding="utf-8", errors="replace", line_buffering=line_buffering
        )
    except Exception:
        pass


def log(message):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def read_json(path, default=None):
    """Читает JSON. Бросает исключение, если файл битый — вызывающий решает, что делать."""
    path = Path(path)
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def try_read_json(path, default):
    """Как read_json, но битый файл не роняет запуск."""
    try:
        return read_json(path, default)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️ Не удалось прочитать {Path(path).name}: {e}")
        return default


def write_json(path, data):
    """Атомарная запись: недописанный файл не останется при падении/остановке."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def backup_file(path):
    """Переименовывает поврежденный файл рядом, возвращая новый путь (или None)."""
    path = Path(path)
    if not path.exists():
        return None
    backup = path.with_suffix(path.suffix + f".broken-{datetime.now():%Y%m%d-%H%M%S}")
    try:
        path.replace(backup)
        return backup
    except OSError:
        return None


def clamp(value, low=0, high=100):
    return max(low, min(high, value))


def has_visible(page, selector, limit=5):
    """Проверяет видимые элементы. `count() > 0` ловит и скрытые дубли — отсюда ложные статусы."""
    try:
        locator = page.locator(selector)
        for i in range(min(locator.count(), limit)):
            if locator.nth(i).is_visible():
                return True
    except Exception:
        pass
    return False
