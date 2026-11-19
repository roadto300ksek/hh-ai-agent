import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from database import DB_PATH, get_today_sent_count, init_db
from hh_resume_selector import choose_for_vacancy
from paths import (
    ACTIVE_CANDIDATES_FILE,
    ANALYZED_FILE,
    BASE_DIR,
    COVER_LETTERS_FILE,
    CREATED_RESUMES_FILE,
    GENERATED_RESUMES_FILE,
    STATE_FILE,
)
from utils import read_json

st.set_page_config(page_title="HH AI-Agent", page_icon="🤖", layout="wide")

st.markdown(
    """
    <style>
      [data-testid="stAppDeployButton"] { display: none; }
      .block-container { padding-top: 2rem; max-width: 1440px; }
      .hero {
        background: linear-gradient(120deg, #111827 0%, #312e81 60%, #4f46e5 100%);
        color: white; padding: 26px 32px; border-radius: 18px; margin-bottom: 22px;
        box-shadow: 0 10px 28px rgba(17, 24, 39, .18);
      }
      .hero h1 { margin: 0; font-size: 32px; letter-spacing: -.5px; }
      .hero p { margin: 8px 0 0; font-size: 15px; opacity: .85; }
      [data-testid="stMetric"] {
        background: #fff; border: 1px solid #e5e7eb; border-radius: 14px;
        padding: 14px 18px; box-shadow: 0 2px 10px rgba(15, 23, 42, .05);
      }
      [data-testid="stTabs"] [role="tab"] { border-radius: 10px 10px 0 0; font-weight: 600; }
      [data-testid="stTabs"] [role="tab"][aria-selected="true"] { background: #eef2ff; color: #3730a3; }
      div[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; border: 1px solid #e5e7eb; }
      section[data-testid="stSidebar"] { background: #f8fafc; border-right: 1px solid #e5e7eb; }
      .stButton > button { border-radius: 10px; }
      .status-pill { padding: 3px 10px; border-radius: 999px; font-size: 13px; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)

init_db()

DASHBOARD_LOG = BASE_DIR / "dashboard.log"


def get_db_data(query):
    """Читает данные из SQLite. Ошибку не прячем — покажем её в интерфейсе."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    try:
        return pd.read_sql_query(query, conn)
    finally:
        conn.close()


def tail_log(path, lines=100):
    if not path.exists():
        return "Лог пока пуст."
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return "".join(f.readlines()[-lines:]) or "Лог пока пуст."


def process_running():
    proc = st.session_state.get("run_proc")
    return proc is not None and proc.poll() is None


def start_script(label, script, args=()):
    """Запускает любой скрипт фоново, вывод пишет в dashboard.log."""
    log_file = DASHBOARD_LOG.open("a", encoding="utf-8")
    log_file.write(
        f"\n{'='*70}\n{label}: {datetime.now():%d.%m.%Y %H:%M:%S}\n"
        f"Команда: {script} {' '.join(args)}\n{'='*70}\n"
    )
    log_file.flush()

    st.session_state.run_proc = subprocess.Popen(
        [sys.executable, "-u", str(BASE_DIR / script), *args],
        cwd=str(BASE_DIR),
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    st.session_state.run_label = label
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


def resume_title_map():
    data = read_json(GENERATED_RESUMES_FILE, {}) or {}
    return {
        item.get("id", ""): item.get("title", "")
        for item in data.get("resumes", [])
        if isinstance(item, dict)
    }


def resume_hash_map():
    data = read_json(CREATED_RESUMES_FILE, {}) or {}
    return {
        rid: info.get("hash", "")
        for rid, info in (data.get("resumes") or {}).items()
        if isinstance(info, dict)
    }


@st.fragment(run_every="2s")
def render_process_status():
    """Живой статус единственного запущенного из дашборда процесса."""
    if process_running():
        label = st.session_state.get("run_label", "процесс")
        st.info(f"⏳ Работает: {label}")
        if st.button("Остановить процесс", width="stretch"):
            stop_agent()
            st.toast("Процесс остановлен.", icon="🛑")
            st.rerun()
    elif st.session_state.get("run_proc") is not None:
        st.success("✅ Последний запуск завершён.")


# --- Боковая панель (Управление) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/4712/4712035.png", width=100)
    st.title("Управление")
    st.markdown("---")

    st.subheader("🚀 Запуск агентов")
    st.caption("Все запуски — во вкладке «⚙️ Ручной запуск».")
    render_process_status()

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
st.markdown(
    """
    <div class="hero">
      <h1>🤖 Панель управления AI-агентом</h1>
      <p>Поиск вакансий, честные резюме и отклики под присмотром. Управление — вкладка «⚙️ Ручной запуск».</p>
    </div>
    """,
    unsafe_allow_html=True,
)

try:
    sent_df = get_db_data("SELECT * FROM sent_applications ORDER BY sent_at DESC")
    queue_df = get_db_data("SELECT * FROM manual_queue ORDER BY added_at DESC")
    sent_today = get_today_sent_count()
except Exception as e:
    st.error(f"Не удалось прочитать базу данных {DB_PATH}: {e}")
    st.stop()

letters = read_json(COVER_LETTERS_FILE, []) or []
if not isinstance(letters, list):
    letters = []
sent_links = set(sent_df["link"].astype(str)) if "link" in sent_df.columns else set()
pending_letters = [item for item in letters if isinstance(item, dict) and item.get("link") not in sent_links]

titles = resume_title_map()
hashes = resume_hash_map()

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric(label="📤 Всего откликов", value=len(sent_df))
with col2:
    st.metric(label="📅 Отправлено сегодня", value=sent_today)
with col3:
    st.metric(label="✉️ Писем в очереди", value=len(pending_letters))
with col4:
    st.metric(label="✋ В ручной очереди", value=len(queue_df))

if not sent_df.empty and "sent_at" in sent_df.columns:
    last_sent = sent_df["sent_at"].dropna().max()
    if last_sent:
        try:
            pretty = datetime.fromisoformat(last_sent).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            pretty = str(last_sent)
        st.caption(f"Последний отклик: {pretty}")

st.markdown("---")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📤 Отклики",
    "✉️ Очередь писем",
    "🗂 Резюме",
    "📋 Ручная очередь",
    "⚙️ Ручной запуск",
    "📜 Лог запуска",
])

with tab1:
    st.subheader("История откликов")

    if not sent_df.empty:
        display = sent_df.copy()
        resume_ids = display["resume_id"] if "resume_id" in display.columns else pd.Series("", index=display.index)
        display["Резюме"] = resume_ids.map(
            lambda rid: titles.get(rid, rid if isinstance(rid, str) else "")
        )
        if "sent_at" in display.columns:
            display[" sent_dt"] = pd.to_datetime(display["sent_at"], errors="coerce")

        with st.container(border=True):
            st.caption("Фильтры")
            period = st.selectbox("Период", ["Все", "Сегодня", "Последние 7 дней"], index=0)
            if period == "Сегодня":
                display = display[
                    display[" sent_dt"] >= pd.Timestamp(datetime.now().date())
                ]
            elif period == "Последние 7 дней":
                display = display[
                    display[" sent_dt"] >= pd.Timestamp.now() - timedelta(days=7)
                ]

            statuses = st.multiselect(
                "Статус",
                options=sorted(display["status"].dropna().unique().tolist()),
                default=[],
            )
            if statuses:
                display = display[display["status"].isin(statuses)]

            query = st.text_input("Поиск по вакансии или компании")
            if query:
                mask = (
                    display.get("title", pd.Series(dtype=str)).fillna("").str.contains(query, case=False)
                    | display.get("company", pd.Series(dtype=str)).fillna("").str.contains(query, case=False)
                )
                display = display[mask]

        display = display.rename(columns={
            "title": "Вакансия", "company": "Компания",
            "score": "Оценка ИИ", "sent_at": "Время",
            "status": "Статус", "link": "Ссылка",
        })
        status_labels = {
            "sent": "✅ отправлено",
            "no_letter": "⚠️ без письма",
            "archived": "⏭️ архив",
            "manual_questions": "✋ вопросы",
            "chat_failed": "⚠️ чат",
            "send_error": "❌ ошибка",
            "no_submit": "❌ не отправлено",
        }
        if "Статус" in display.columns:
            display["Статус"] = display["Статус"].map(
                lambda value: status_labels.get(value, value)
            )
        columns = [
            column for column in
            ["Вакансия", "Компания", "Оценка ИИ", "Статус", "Резюме", "Время", "Ссылка"]
            if column in display.columns
        ]
        st.caption(f"Показано: {len(display)} из {len(sent_df)}")
        st.dataframe(display[columns], width="stretch", hide_index=True)
    else:
        st.info("Пока нет отправленных откликов.")

with tab2:
    st.subheader("Очередь сопроводительных писем")
    if letters:
        rows = []
        for item in letters:
            if not isinstance(item, dict):
                continue
            link = item.get("link", "")
            rows.append({
                "Вакансия": item.get("title", ""),
                "Компания": item.get("company", ""),
                "Оценка": item.get("score", 0),
                "Статус": "✅ отправлено" if link in sent_links else "🕓 в очереди",
                "Ссылка": link,
                "Письмо": item.get("cover_letter", ""),
            })
        letters_df = pd.DataFrame(rows)
        st.dataframe(
            letters_df.drop(columns=["Письмо"]),
            width="stretch",
            hide_index=True,
        )
        selected = st.selectbox(
            "Посмотреть письмо",
            options=range(len(letters_df)),
            format_func=lambda i: letters_df.iloc[i]["Вакансия"],
        )
        st.text_area(
            "Текст письма",
            value=letters_df.iloc[selected]["Письмо"],
            height=220,
            disabled=True,
        )
    else:
        st.info("Очередь писем пуста. Сгенерируйте письма во вкладке «Ручной запуск».")

with tab3:
    st.subheader("Резюме для автоотбора")
    resume_rows = []
    for item in (read_json(GENERATED_RESUMES_FILE, {}) or {}).get("resumes", []):
        if not isinstance(item, dict):
            continue
        rid = item.get("id", "")
        resume_rows.append({
            "id": rid,
            "Должность": item.get("title", ""),
            "Хэш hh": hashes.get(rid, "")[:12],
            "Навыки": ", ".join(item.get("skills", [])),
        })
    if resume_rows:
        st.dataframe(pd.DataFrame(resume_rows), width="stretch", hide_index=True)
        rid = st.selectbox(
            "Проверить подбор резюме по вакансии",
            options=[item.get("link", "") for item in letters if isinstance(item, dict)],
        )
        vacancy = next((v for v in letters if isinstance(v, dict) and v.get("link") == rid), None)
        if vacancy and st.button("Подобрать резюме"):
            choice = choose_for_vacancy(vacancy)
            st.success(f"{choice.resume_id} — {choice.title}")
            st.caption(choice.reason)
    else:
        st.info("generated_resumes.json не найден.")

with tab4:
    st.subheader("Вакансии, требующие ручного вмешательства")
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

with tab5:
    st.subheader("Ручной запуск агентов")
    running = process_running()

    with st.container(border=True):
        st.markdown("##### 📨 Отклики")
        c1, c2, c3 = st.columns(3)
        with c1:
            limit = st.number_input("Лимит откликов", min_value=1, max_value=50, value=5)
        with c2:
            min_delay = st.number_input("Минимальная пауза, мин", min_value=0, max_value=60, value=5)
        with c3:
            max_delay = st.number_input("Максимальная пауза, мин", min_value=0, max_value=60, value=10)
        if st.button("Запустить отправку откликов", disabled=running, type="primary"):
            start_script(
                "Отклики (executor)",
                "hh_executor.py",
                (
                    "--headless",
                    "--limit", str(limit),
                    "--min-delay", str(min_delay * 60),
                    "--max-delay", str(max_delay * 60),
                ),
            )
            st.toast("Отклики запущены. Смотрите вкладку «Лог запуска».", icon="🚀")
            st.rerun()

    with st.container(border=True):
        st.markdown("##### ✍️ Письма")
        source = st.radio(
            "Источник вакансий",
            ["Только активные", "Все проанализированные"],
            horizontal=True,
            help="Активные — после проверки через Playwright: без архива и уже отправленных.",
        )
        if ACTIVE_CANDIDATES_FILE.exists():
            active_count = len(read_json(ACTIVE_CANDIDATES_FILE, []) or [])
            st.caption(f"В списке активных: {active_count} вакансий")
        else:
            st.warning("Список активных ещё не создан — нажмите «Обновить список активных».")

        c1, c2 = st.columns([2, 1])
        with c1:
            letter_limit = st.number_input(
                "Сколько писем сгенерировать", min_value=1, max_value=50, value=10
            )
        with c2:
            st.write("")
            if st.button("Обновить список активных", disabled=running):
                start_script(
                    "Отбор активных вакансий",
                    "hh_active_filter.py",
                    ("--headless", "--top", "100"),
                )
                st.toast("Проверка вакансий запущена. Это займёт несколько минут.", icon="🔍")
                st.rerun()

        use_active = source == "Только активные"
        if st.button(
            "Сгенерировать письма",
            disabled=running or (use_active and not ACTIVE_CANDIDATES_FILE.exists()),
            type="primary",
        ):
            src = ACTIVE_CANDIDATES_FILE if use_active else ANALYZED_FILE
            start_script(
                "Генерация писем (writer)",
                "hh_writer.py",
                ("--input", str(src), "--limit", str(letter_limit), "--min-score", "0"),
            )
            st.toast("Генерация писем запущена.", icon="✍️")
            st.rerun()

    with st.container(border=True):
        st.markdown("##### 📝 Резюме на hh.ru")
        st.caption("Перезапишет «О себе», навыки и должности у всех 10 резюме. Займёт около 12 минут.")
        if st.button("Обновить тексты 10 резюме", disabled=running):
            start_script(
                "Обновление резюме (filler)",
                "hh_resume_filler.py",
                ("--all", "--update", "--headless"),
            )
            st.toast("Обновление резюме запущено.", icon="📝")
            st.rerun()

    if running and st.button("Остановить текущий процесс"):
        stop_agent()
        st.toast("Процесс остановлен.", icon="🛑")
        st.rerun()

with tab6:
    st.subheader("Лог запуска")
    if DASHBOARD_LOG.exists():
        st.caption(
            f"Файл: {DASHBOARD_LOG.name} · "
            f"изменён {datetime.fromtimestamp(DASHBOARD_LOG.stat().st_mtime):%d.%m.%Y %H:%M:%S}"
        )
    st.code(tail_log(DASHBOARD_LOG), language="text")
