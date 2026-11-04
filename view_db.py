import sqlite3

# Подключаемся к базе
conn = sqlite3.connect('hh_agent.db')
cursor = conn.cursor()

print("=== ОТПРАВЛЕННЫЕ ОТКЛИКИ ===")
cursor.execute("SELECT title, company, score, status, sent_at FROM sent_applications")
for row in cursor.fetchall():
    print(f"[{row[2]}] {row[0]} — {row[1]} (Статус: {row[3]}, Время: {row[4]})")

print("\n=== РУЧНАЯ ОЧЕРЕДЬ ===")
cursor.execute("SELECT title, company, reason FROM manual_queue")
for row in cursor.fetchall():
    print(f"{row[0]} — {row[1]} (Причина: {row[2]})")

conn.close()