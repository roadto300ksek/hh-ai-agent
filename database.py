import sqlite3
from contextlib import contextmanager
from datetime import datetime

from paths import DB_PATH


@contextmanager
def get_conn(db_path=DB_PATH):
    """Соединение SQLite, которое гарантированно закрывается.

    `with sqlite3.connect(...)` коммитит, но НЕ закрывает соединение —
    на Windows это оставляло открытые файлы и блокировки.
    """
    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path=DB_PATH):
    """Создает таблицы при первом запуске."""
    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        # Таблица для отправленных откликов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sent_applications (
                link TEXT PRIMARY KEY,
                title TEXT,
                company TEXT,
                score INTEGER,
                sent_at TEXT,
                status TEXT
            )
        ''')
        # Таблица для ручной очереди (где требуются ответы)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS manual_queue (
                link TEXT PRIMARY KEY,
                title TEXT,
                company TEXT,
                reason TEXT,
                added_at TEXT
            )
        ''')


def get_sent_links(db_path=DB_PATH):
    """Возвращает список ссылок, на которые уже откликались."""
    with get_conn(db_path) as conn:
        cursor = conn.execute("SELECT link FROM sent_applications")
        return {row[0] for row in cursor.fetchall()}


def get_today_sent_count(db_path=DB_PATH):
    """Сколько откликов реально отправлено сегодня (для дневного лимита)."""
    day = datetime.now().strftime("%Y-%m-%d")
    with get_conn(db_path) as conn:
        cursor = conn.execute(
            "SELECT COUNT(*) FROM sent_applications "
            "WHERE status = 'sent' AND sent_at LIKE ?",
            (f"{day}%",),
        )
        return cursor.fetchone()[0]


def add_sent_application(link, title, company, score, status="sent", db_path=DB_PATH):
    """Записывает отклик. Статус 'sent' имеет приоритет над archived/already."""
    with get_conn(db_path) as conn:
        conn.execute('''
            INSERT INTO sent_applications (link, title, company, score, sent_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(link) DO UPDATE SET
                title = excluded.title,
                company = excluded.company,
                score = excluded.score,
                status = CASE
                    WHEN excluded.status = 'sent' THEN 'sent'
                    ELSE sent_applications.status
                END,
                sent_at = CASE
                    WHEN excluded.status = 'sent' THEN excluded.sent_at
                    ELSE sent_applications.sent_at
                END
        ''', (link, title, company, score, datetime.now().isoformat(), status))


def get_manual_queue(db_path=DB_PATH):
    """Возвращает список вакансий из ручной очереди."""
    with get_conn(db_path) as conn:
        cursor = conn.execute("SELECT link, title, company, reason FROM manual_queue")
        return [
            {"link": r[0], "title": r[1], "company": r[2], "reason": r[3]}
            for r in cursor.fetchall()
        ]


def add_to_manual_queue(link, title, company, reason, db_path=DB_PATH):
    """Добавляет вакансию в ручную очередь, если её там еще нет."""
    with get_conn(db_path) as conn:
        conn.execute('''
            INSERT INTO manual_queue (link, title, company, reason, added_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(link) DO NOTHING
        ''', (link, title, company, reason, datetime.now().isoformat()))
