import streamlit as st
import sqlite3
import pandas as pd
import subprocess
import sys
import os
from datetime import datetime

from database import DB_PATH, init_db

# Настройка страницы
st.set_page_config(page_title="HH AI-Agent", page_icon="🤖", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Функции для работы с БД ---
def get_db_data(query):
    """Читает данные из SQLite. Ошибку не прячем — покажем её в интерфейсе."""
    conn = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query(query, conn)
    finally:
        conn.close()

# Создаем таблицы, если база еще не инициализирована
init_db()

# --- Боковая панель (Управление) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/4712/4712035.png", width=100)
    st.title("Управление")
    st.markdown("---")
    
    st.subheader("🚀 Запуск агентов")
    if st.button("Запустить полный цикл (Run All)", use_container_width=True, type="primary"):
        st.toast("Агент запущен! Проверь консоль для просмотра логов.", icon="🚀")
        # Запускаем run_all.py в фоне из папки проекта
        subprocess.Popen([sys.executable, os.path.join(BASE_DIR, "run_all.py")], cwd=BASE_DIR)
    
    if st.button("Обновить данные", use_container_width=True):
        st.rerun()

    st.markdown("---")
    st.info("Статус системы: 🟢 Онлайн\n\nБаза данных: SQLite\nСтек: Python, Playwright, LLM")

# --- Основная часть (Дашборд) ---
st.title("🤖 Панель управления AI-агентом")
st.markdown("Автоматизация поиска и отклика на вакансии HeadHunter")

# Считаем статистику
try:
    sent_df = get_db_data("SELECT * FROM sent_applications ORDER BY sent_at DESC")
    queue_df = get_db_data("SELECT * FROM manual_queue ORDER BY added_at DESC")
except Exception as e:
    st.error(f"Не удалось прочитать базу данных {DB_PATH}: {e}")
    st.stop()

# Метрики
col1, col2, col3 = st.columns(3)
with col1:
    st.metric(label="📤 Всего откликов", value=len(sent_df))
with col2:
    st.metric(label="✋ В ручной очереди", value=len(queue_df))
with col3:
    # Считаем отправленные сегодня
    today = datetime.now().strftime("%Y-%m-%d")
    sent_today = len(sent_df[sent_df['sent_at'].fillna('').str.startswith(today)]) if not sent_df.empty else 0
    st.metric(label="📅 Отправлено сегодня", value=sent_today)

st.markdown("---")

# Вкладки
tab1, tab2 = st.tabs(["📤 История откликов", "📋 Ручная очередь"])

with tab1:
    st.subheader("Отправленные отклики")
    if not sent_df.empty:
        # Красиво переименовываем колонки для таблицы
        sent_df_display = sent_df.rename(columns={
            "title": "Вакансия", "company": "Компания", 
            "score": "Оценка ИИ", "sent_at": "Время", "status": "Статус", "link": "Ссылка"
        })
        # Выводим только нужные колонки
        st.dataframe(
            sent_df_display[["Вакансия", "Компания", "Оценка ИИ", "Статус", "Время", "Ссылка"]],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Пока нет отправленных откликов.")

with tab2:
    st.subheader("Вакансии с вопросами (Требуют ручного вмешательства)")
    if not queue_df.empty:
        queue_df_display = queue_df.rename(columns={
            "title": "Вакансия", "company": "Компания", 
            "reason": "Причина", "link": "Ссылка", "added_at": "Добавлено"
        })
        st.dataframe(
            queue_df_display[["Вакансия", "Компания", "Причина", "Ссылка"]],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.success("Ручная очередь пуста! Агент справляется сам.")