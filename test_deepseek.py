from openai import OpenAI

# ВСТАВЬ СЮДА СВОЙ КЛЮЧ ОТ DEEPSEEK
API_KEY = "REMOVED_LEAKED_KEY"

client = OpenAI(
    base_url="https://api.deepseek.com",  # Адрес API DeepSeek
    api_key=API_KEY,
)

try:
    response = client.chat.completions.create(
        model="deepseek-flash",  # Актуальная быстрая модель
        messages=[
            {
                "role": "user",
                "content": "Напиши короткое сопроводительное письмо на вакансию Python-разработчик. Мои навыки: Python, Playwright, LLM, автоматизация. Без воды, по делу."
            }
        ],
        # Можно включить режим размышления, если нужно более глубокое рассуждение
        # extra_body={"thinking": {"type": "enabled"}},
    )
    print("✅ Успех! Вот твоё тестовое письмо:\n")
    print(response.choices[0].message.content)
except Exception as e:
    print(f"❌ Ошибка: {e}")