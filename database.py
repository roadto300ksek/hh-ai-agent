import sqlite3
from datetime import datetime
import os

DB_NAME = "hh_agent.db"
# Абсолютный путь: база всегда рядом с кодом, а не в текущей папке запуска
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_NAME)

def init_db():
    """Создает таблицы при первом запуске."""
    with sqlite3.connect(DB_PATH) as conn:
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
        conn.commit()

def get_sent_links():
    """Возвращает список ссылок, на которые уже откликались."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT link FROM sent_applications")
        return {row[0] for row in cursor.fetchall()}

def add_sent_application(link, title, company, score, status="sent"):
    """Записывает отклик в базу данных."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO sent_applications (link, title, company, score, sent_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (link, title, company, score, datetime.now().isoformat(), status))
        conn.commit()

def get_manual_queue():
    """Возвращает список вакансий из ручной очереди."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT link, title, company, reason FROM manual_queue")
        return [{"link": r[0], "title": r[1], "company": r[2], "reason": r[3]} for r in cursor.fetchall()]

def add_to_manual_queue(link, title, company, reason):
    """Добавляет вакансию в ручную очередь, если её там еще нет."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO manual_queue (link, title, company, reason, added_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (link, title, company, reason, datetime.now().isoformat()))
        conn.commit()
