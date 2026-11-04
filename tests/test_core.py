import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import database
from hh_analyzer import normalize_scores, parse_llm_response
from hh_executor import build_queue
from hh_scanner_multi import build_search_url, normalize_link
from hh_writer import normalize_letters, select_new, select_pending
from utils import clamp, read_json, write_json


class TestAnalyzerParsing(unittest.TestCase):
    def test_parses_json_object(self):
        data = parse_llm_response('{"results": [{"index": 1, "score": 85, "reason": "ok"}]}')
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["score"], 85)

    def test_parses_markdown_wrapped_json(self):
        data = parse_llm_response('```json\n{"results": [{"index": 2, "score": 10}]}\n```')
        self.assertEqual(data[0]["index"], 2)

    def test_parses_plain_list(self):
        data = parse_llm_response('[{"index": 1, "score": 40}]')
        self.assertEqual(data[0]["score"], 40)

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            parse_llm_response("не JSON")
        with self.assertRaises(ValueError):
            parse_llm_response('{"foo": []}')

    def test_normalize_clamps_and_skips_bad_items(self):
        result = normalize_scores([
            {"index": 1, "score": 150, "reason": "top"},
            {"index": 2, "score": -10, "reason": "bad"},
            {"index": "abc", "score": 50},
            {"score": 50},
            "мусор",
        ])
        self.assertEqual(result[1]["score"], 100)
        self.assertEqual(result[2]["score"], 0)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["reason"], "top")


class TestScannerHelpers(unittest.TestCase):
    def test_url_contains_filters_and_page(self):
        url = build_search_url("Python автоматизация", 1)
        params = parse_qs(urlparse(url).query)
        self.assertEqual(params["text"], ["Python автоматизация"])
        self.assertEqual(params["page"], ["1"])
        self.assertEqual(params["area"], ["113"])
        self.assertEqual(params["schedule"], ["remote"])
        self.assertEqual(params["experience"], ["noExperience,between1And3"])

    def test_normalize_link(self):
        self.assertEqual(
            normalize_link("/vacancy/123?from=serp"),
            "https://hh.ru/vacancy/123",
        )
        self.assertEqual(
            normalize_link("https://hh.ru/vacancy/456?from=serp"),
            "https://hh.ru/vacancy/456",
        )
        self.assertIsNone(normalize_link(None))


class TestWriterSelection(unittest.TestCase):
    def test_normalize_letters(self):
        items = [
            {"link": "a"},
            {"link": "a"},
            {"link": "b"},
            {"no_link": 1},
            "мусор",
        ]
        self.assertEqual([i["link"] for i in normalize_letters(items)], ["a", "b"])

    def test_select_pending_excludes_sent_and_manual(self):
        letters = [{"link": "a"}, {"link": "b"}, {"link": "c"}]
        pending = select_pending(letters, {"a"}, {"b"})
        self.assertEqual([i["link"] for i in pending], ["c"])

    def test_select_new_filters_score_limit_and_duplicates(self):
        analyzed = [
            {"link": "a", "score": 95},
            {"link": "a", "score": 95},
            {"link": "b", "score": 69},
            {"link": "c", "score": 80},
            {"link": "d", "score": 90},
        ]
        result = select_new(analyzed, {"c"}, limit=2)
        self.assertEqual([i["link"] for i in result], ["a", "d"])


class TestExecutorQueue(unittest.TestCase):
    def test_build_queue_skips_invalid_and_sent(self):
        letters = [
            {"link": "a", "cover_letter": "text"},
            {"link": "a", "cover_letter": "text"},
            {"link": "b", "cover_letter": "text"},
            {"link": "c"},
            {"link": "d", "cover_letter": "text"},
        ]
        queue = build_queue(letters, {"b"}, limit=10)
        self.assertEqual([i["link"] for i in queue], ["a", "d"])


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        database.init_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sent_links_are_unique(self):
        database.add_sent_application("a", "t", "c", 90, db_path=self.db)
        database.add_sent_application("a", "t2", "c2", 80, db_path=self.db)
        self.assertEqual(database.get_sent_links(self.db), {"a"})

    def test_status_upgrades_to_sent(self):
        database.add_sent_application("a", "t", "c", 50, status="archived", db_path=self.db)
        database.add_sent_application("a", "t", "c", 90, status="sent", db_path=self.db)
        with database.get_conn(self.db) as conn:
            status = conn.execute(
                "SELECT status FROM sent_applications WHERE link = 'a'"
            ).fetchone()[0]
        self.assertEqual(status, "sent")

    def test_sent_status_is_not_downgraded(self):
        database.add_sent_application("a", "t", "c", 90, status="sent", db_path=self.db)
        database.add_sent_application("a", "t", "c", 90, status="archived", db_path=self.db)
        with database.get_conn(self.db) as conn:
            status = conn.execute(
                "SELECT status FROM sent_applications WHERE link = 'a'"
            ).fetchone()[0]
        self.assertEqual(status, "sent")

    def test_today_count_counts_only_sent(self):
        database.add_sent_application("a", "t", "c", 90, status="sent", db_path=self.db)
        database.add_sent_application("b", "t", "c", 10, status="archived", db_path=self.db)
        self.assertEqual(database.get_today_sent_count(self.db), 1)

    def test_manual_queue_deduplicates(self):
        database.add_to_manual_queue("a", "t", "c", "reason", db_path=self.db)
        database.add_to_manual_queue("a", "t", "c", "reason", db_path=self.db)
        self.assertEqual(len(database.get_manual_queue(self.db)), 1)


class TestUtils(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp(150), 100)
        self.assertEqual(clamp(-5), 0)
        self.assertEqual(clamp(42), 42)

    def test_atomic_json_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"
            write_json(path, {"ключ": "значение"})
            self.assertEqual(read_json(path), {"ключ": "значение"})
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
