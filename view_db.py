from database import get_conn, init_db
from utils import configure_stdout

configure_stdout()


def main():
    init_db()

    with get_conn() as conn:
        print("=== ОТПРАВЛЕННЫЕ ОТКЛИКИ ===")
        rows = conn.execute(
            "SELECT title, company, score, status, sent_at FROM sent_applications "
            "ORDER BY sent_at DESC"
        ).fetchall()
        if not rows:
            print("Пока пусто.")
        for title, company, score, status, sent_at in rows:
            print(f"[{score}] {title} — {company} (Статус: {status}, Время: {sent_at})")

        print("\n=== РУЧНАЯ ОЧЕРЕДЬ ===")
        queue = conn.execute(
            "SELECT title, company, reason FROM manual_queue ORDER BY added_at DESC"
        ).fetchall()
        if not queue:
            print("Очередь пуста.")
        for title, company, reason in queue:
            print(f"{title} — {company} (Причина: {reason})")


if __name__ == "__main__":
    main()
