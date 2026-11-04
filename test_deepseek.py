import os

from dotenv import load_dotenv
from openai import OpenAI

# Ключ берется из .env и никогда не хранится в коде
load_dotenv()
API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not API_KEY:
    raise SystemExit(
        "❌ DEEPSEEK_API_KEY не найден. Добавь в файл .env строку:\n"
        "DEEPSEEK_API_KEY=твой_ключ"
    )

client = OpenAI(
    base_url="https://api.deepseek.com",  # Адрес API DeepSeek
    api_key=API_KEY,
)

try:
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "user",
                "content": "Напиши короткое сопроводительное письмо на вакансию Python-разработчик. Мои навыки: Python, Playwright, LLM, автоматизация. Без воды, по делу."
            }
        ],
    )
    print("✅ Успех! Вот твоё тестовое письмо:\n")
    print(response.choices[0].message.content)
except Exception as e:
    print(f"❌ Ошибка: {e}")
