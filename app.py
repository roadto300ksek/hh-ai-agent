import os
import sqlite3
import subprocess
import sys
from datetime import datetime

import pandas as pd
import streamlit as st

from database import DB_PATH, get_today_sent_count, init_db
from paths import BASE_DIR, RUN_LOG, STATE_FILE

st.set_page_config(page_title="HH AI-Agent", page_icon="🤖", layout="wide")

init_db()


def get_db_data(query):
    """Читает данные из SQLite. Ошибку не прячем — покажем её в интерфейсе."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    try:
        return pd.read_sql_query(query, conn)
    finally:
        conn.close()


def tail_log(lines=100):
    if not RUN_LOG.exists():
        return "Лог пока пуст."
    with RUN_LOG.open("r", encoding="utf-8", errors="replace") as f:
        return "".join(f.readlines()[-lines:]) or "Лог пока пуст."


def process_running():
    proc = st.session_state.get("run_proc")
    return proc is not None and proc.poll() is None


def start_agent():
    """Запускает run_all.py в фоне: вывод построчно пишется в run_all.log.

    - stdin=DEVNULL: из дашборда нет консоли, поэтому капча не должна ждать input().
    - -u и PYTHONUNBUFFERED: логи появляются сразу, а не пачками по 8 КБ.
    """
    log_file = RUN_LOG.open("a", encoding="utf-8")
    log_file.write(
        f"\n{'='*70}\n"
        f"Запуск: {datetime.now():%d.%m.%Y %H:%M:%S}\n"
        f"{'='*70}\n"
    )
    log_file.flush()

    st.session_state.run_proc = subprocess.Popen(
        [sys.executable, "-u", str(BASE_DIR / "run_all.py")],
        cwd=str(BASE_DIR),
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    log_file.close()


def stop_agent():
    """Останавливает агента вместе с дочерними процессами (Windows: taskkill /T)."""
    proc = st.session_state.get("run_proc")
    if proc is None:
        return

    if proc.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    st.session_state.run_proc = None


@st.fragment(run_every="2s")
def render_agent_controls():
    """Кнопки запуска/остановки + живой статус процесса."""
    running = process_running()

    if st.button(
        "Запустить полный цикл (Run All)",
        width="stretch",
        type="primary",
        disabled=running,
    ):
        start_agent()
        st.toast("Агент запущен. Логи — во вкладке «Лог запуска».", icon="🚀")
        st.rerun()

    if running:
        if st.button("Остановить агента", width="stretch"):
            stop_agent()
            st.toast("Агент остановлен.", icon="🛑")
            st.rerun()
        st.info("⏳ Агент работает. Логи обновляются в файле run_all.log.")
    elif st.session_state.get("run_proc") is not None:
        st.success("✅ Последний запуск завершён.")


@st.fragment(run_every="2s")
def render_log():
    """Лог обновляется сам, кнопка «Обновить» больше не нужна."""
    if RUN_LOG.exists():
        st.caption(
            f"Файл: {RUN_LOG.name} · "
            f"изменён {datetime.fromtimestamp(RUN_LOG.stat().st_mtime):%d.%m.%Y %H:%M:%S}"
        )
    st.code(tail_log(), language="text")


# --- Боковая панель (Управление) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/4712/4712035.png", width=100)
    st.title("Управление")
    st.markdown("---")

    st.subheader("🚀 Запуск агентов")
    render_agent_controls()

    if st.button("Обновить данные", width="stretch"):
        st.rerun()

    st.markdown("---")
    state_status = "🟢 сессия сохранена" if STATE_FILE.exists() else "🔴 нет hh_state.json"
    st.info(
        f"Статус системы: {state_status}\n\n"
        f"База данных: {DB_PATH.name}\n"
        "Стек: Python, Playwright, LLM"
    )
    if not STATE_FILE.exists():
        st.warning("Сначала запусти `python hh_login.py` и войди в аккаунт.")

# --- Основная часть (Дашборд) ---
st.title("🤖 Панель управления AI-агентом")
st.markdown("Автоматизация поиска и отклика на вакансии HeadHunter")

try:
    sent_df = get_db_data("SELECT * FROM sent_applications ORDER BY sent_at DESC")
    queue_df = get_db_data("SELECT * FROM manual_queue ORDER BY added_at DESC")
    sent_today = get_today_sent_count()
except Exception as e:
    st.error(f"Не удалось прочитать базу данных {DB_PATH}: {e}")
    st.stop()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric(label="📤 Всего откликов", value=len(sent_df))
with col2:
    st.metric(label="✋ В ручной очереди", value=len(queue_df))
with col3:
    st.metric(label="📅 Отправлено сегодня", value=sent_today)

if not sent_df.empty and "sent_at" in sent_df.columns:
    last_sent = sent_df["sent_at"].dropna().max()
    if last_sent:
        try:
            pretty = datetime.fromisoformat(last_sent).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            pretty = str(last_sent)
        st.caption(f"Последний отклик: {pretty}")

st.markdown("---")

tab1, tab2, tab3 = st.tabs(["📤 История откликов", "📋 Ручная очередь", "📜 Лог запуска"])

with tab1:
    st.subheader("Отправленные отклики")
    if not sent_df.empty:
        display = sent_df.rename(columns={
            "title": "Вакансия", "company": "Компания",
            "score": "Оценка ИИ", "sent_at": "Время",
            "status": "Статус", "link": "Ссылка",
        })
        columns = [
            column for column in
            ["Вакансия", "Компания", "Оценка ИИ", "Статус", "Время", "Ссылка"]
            if column in display.columns
        ]
        st.dataframe(display[columns], width="stretch", hide_index=True)
    else:
        st.info("Пока нет отправленных откликов.")

with tab2:
    st.subheader("Вакансии с вопросами (Требуют ручного вмешательства)")
    if not queue_df.empty:
        display = queue_df.rename(columns={
            "title": "Вакансия", "company": "Компания",
            "reason": "Причина", "link": "Ссылка", "added_at": "Добавлено",
        })
        columns = [
            column for column in ["Вакансия", "Компания", "Причина", "Ссылка"]
            if column in display.columns
        ]
        st.dataframe(display[columns], width="stretch", hide_index=True)
    else:
        st.success("Ручная очередь пуста! Агент справляется сам.")

with tab3:
    st.subheader("Лог последнего запуска")
    render_log()
