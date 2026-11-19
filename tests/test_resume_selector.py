import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import database
import hh_executor
import hh_resume_selector as selector


def fake_resumes():
    return [
        {
            "id": rid,
            "title": f"Резюме {rid}",
            "target_titles": [],
            "match_keywords": [],
        }
        for rid in (
            "automation", "bots", "parsing", "ai", "backend",
            "integration", "internal_tools", "qa", "data", "general",
        )
    ]


class TestResumeSelector(unittest.TestCase):
    def setUp(self):
        self.resumes = fake_resumes()
        self.hashes = {r["id"]: f"hash-{r['id']}" for r in self.resumes}

    def choose(self, title, description=""):
        return selector.choose_resume(
            {"title": title, "description": description},
            resumes=self.resumes,
            hashes=self.hashes,
        )

    def test_title_signals(self):
        cases = {
            "QA Automation Engineer (Python)": "qa",
            "Инженер по автоматизации тестирования": "qa",
            "Python-разработчик Telegram-ботов": "bots",
            "Разработчик бота для записи": "bots",
            "Парсинг данных и автоматизация": "parsing",
            "AI-инженер / LLM-разработчик": "ai",
            "Python-разработчик ИИ агента": "ai",
            "Data Engineer / ETL": "data",
            "RPA-разработчик": "automation",
            "Интегратор API": "integration",
            "Python-разработчик внутренних инструментов": "internal_tools",
            "Junior Python Backend-разработчик (REST API)": "backend",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(self.choose(title).resume_id, expected)

    def test_generic_title_falls_back_to_general(self):
        choice = self.choose("Python-разработчик")
        self.assertEqual(choice.resume_id, "general")
        self.assertTrue(choice.is_fallback)

    def test_description_fallback_needs_two_signals(self):
        one = self.choose("Разработчик", "Нужна помощь с ботами в проекте.")
        self.assertEqual(one.resume_id, "general")

        many = self.choose(
            "Разработчик",
            "Нужен Telegram-бот на aiogram: python-telegram-bot, модерация чатов.",
        )
        self.assertEqual(many.resume_id, "bots")
        self.assertFalse(many.is_fallback)

    def test_hash_is_returned(self):
        choice = self.choose("QA Automation Engineer")
        self.assertEqual(choice.hash, "hash-qa")

    def test_normalize_replaces_yo(self):
        self.assertEqual(selector.normalize("ПрИвЕт  ЁЖик"), "привет ежик")


class TestCaptchaDetection(unittest.TestCase):
    def make_page(self):
        page = MagicMock()
        page.url = "https://hh.ru/vacancy/1"
        return page

    @patch("hh_executor.has_visible", return_value=False)
    def test_no_captcha(self, mock_visible):
        self.assertFalse(hh_executor.check_captcha(self.make_page()))

    @patch("hh_executor.has_visible")
    def test_modal_captcha_is_detected(self, mock_visible):
        mock_visible.side_effect = (
            lambda page, selector: "капчу" in selector or "картинки" in selector
        )
        self.assertTrue(hh_executor.check_captcha(self.make_page()))


class TestSentApplicationResumeId(unittest.TestCase):
    def test_resume_id_saved_and_migration_works(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "test.db"
            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute(
                    "CREATE TABLE sent_applications (link TEXT PRIMARY KEY, title TEXT, "
                    "company TEXT, score INTEGER, sent_at TEXT, status TEXT)"
                )
                conn.commit()
            finally:
                conn.close()

            database.init_db(db_path)
            database.add_sent_application(
                "https://hh.ru/vacancy/1", "Python", "ООО", 70,
                status="sent", resume_id="backend", db_path=db_path,
            )

            conn = sqlite3.connect(str(db_path))
            try:
                columns = {
                    r[1] for r in conn.execute("PRAGMA table_info(sent_applications)")
                }
                row = conn.execute("SELECT resume_id FROM sent_applications").fetchone()
            finally:
                conn.close()
            self.assertIn("resume_id", columns)
            self.assertEqual(row[0], "backend")


if __name__ == "__main__":
    unittest.main()
