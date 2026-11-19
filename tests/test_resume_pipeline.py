import json
import unittest
from unittest.mock import patch

import build_user_profile
import hh_details_collector as collector
import hh_market_analyzer as market
import hh_resume_generator as gen
import hh_resume_targeter as targeter
from paths import (
    GENERATED_RESUMES_FILE,
    MARKET_TRENDS_FILE,
    RESUME_TARGETS_FILE,
    USER_PROFILE_FILE,
    VACANCY_DETAILS_FILE,
)


class TestDetailsCollector(unittest.TestCase):
    def test_select_candidates_skips_existing_and_honors_limit(self):
        vacancies = [
            {"link": f"https://hh.ru/vacancy/{index}", "title": str(index)}
            for index in range(1, 6)
        ]
        result = collector.select_candidates(
            vacancies, {"https://hh.ru/vacancy/2"}, limit=3
        )
        self.assertEqual(len(result), 3)
        links = [item["link"] for item in result]
        self.assertNotIn("https://hh.ru/vacancy/2", links)
        self.assertEqual(len(set(links)), 3)

    def test_select_candidates_skips_items_without_link(self):
        vacancies = [{"title": "без ссылки"}, {"link": "https://hh.ru/vacancy/1"}]
        result = collector.select_candidates(vacancies, set(), limit=10)
        self.assertEqual(len(result), 1)

    def test_is_login_url_detects_login_page(self):
        self.assertTrue(collector.is_login_url("https://hh.ru/account/login?role=applicant"))
        self.assertTrue(collector.is_login_url("https://hh.ru/login"))
        self.assertFalse(collector.is_login_url("https://hh.ru/vacancy/123"))

    def test_load_existing_drops_empty_descriptions(self):
        stored = {
            "meta": {},
            "items": [
                {"link": "https://hh.ru/vacancy/1", "description": "текст"},
                {"link": "https://hh.ru/vacancy/2", "description": ""},
                "мусор",
            ],
        }
        with patch.object(collector, "read_json", return_value=stored):
            data = collector.load_existing()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["link"], "https://hh.ru/vacancy/1")


class TestMarketAnalyzer(unittest.TestCase):
    def test_canonical_skill_aliases(self):
        self.assertEqual(market.canonical_skill("python"), "Python")
        self.assertEqual(market.canonical_skill("Python3"), "Python")
        self.assertEqual(market.canonical_skill("postgres"), "PostgreSQL")
        self.assertEqual(market.canonical_skill("rest api"), "REST API")
        self.assertEqual(market.canonical_skill("aiogram 3"), "aiogram")

    def test_canonical_skill_drops_generic(self):
        self.assertEqual(market.canonical_skill("опыт"), "")
        self.assertEqual(market.canonical_skill("командная работа"), "")

    def test_normalize_title_strips_level_and_punctuation(self):
        self.assertEqual(
            market.normalize_title("Junior Python-разработчик"),
            "Python-разработчик",
        )
        self.assertEqual(
            market.normalize_title("Middle Backend/разработчик"),
            "Backend разработчик",
        )
        self.assertEqual(
            market.normalize_title("Senior AI-инженер"),
            "AI-инженер",
        )

    def test_parse_batch_json_from_markdown(self):
        raw = '```json\n{"titles": ["Python"], "skills": ["FastAPI"], "soft": [], "pains": []}\n```'
        data = market.parse_batch_json(raw)
        self.assertEqual(data["titles"], ["Python"])
        self.assertEqual(data["skills"], ["FastAPI"])

    def test_parse_batch_json_rejects_garbage(self):
        with self.assertRaises(ValueError):
            market.parse_batch_json("не JSON")

    def test_with_share_counts_and_limits(self):
        from collections import Counter

        counter = Counter({"Python": 10, "Flask": 5, "Git": 1})
        result = market.with_share(counter, 20, 2)
        self.assertEqual(result[0]["name"], "Python")
        self.assertEqual(result[0]["share"], 0.5)
        self.assertEqual(len(result), 2)

    def test_cluster_pains_reads_dict_items(self):
        from collections import Counter

        counter = Counter({"рутина": 5})
        payload = json.dumps({"pains": [{"pain": "рутина", "count": 5}]})
        with patch.object(market, "ask_llm", return_value=payload):
            result = market.cluster_pains(counter)
        self.assertEqual(result[0]["pain"], "рутина")
        self.assertEqual(result[0]["count"], 5)

    def test_cluster_titles_adds_share(self):
        from collections import Counter

        counter = Counter({"python": 10})
        payload = json.dumps({"titles": [{"title": "Python-разработчик", "count": 8}]})
        with patch.object(market, "ask_llm", return_value=payload):
            result = market.cluster_titles(counter, 20)
        self.assertEqual(result[0]["name"], "Python-разработчик")
        self.assertEqual(result[0]["share"], 0.4)


class TestResumeTargeter(unittest.TestCase):
    def test_default_targets_are_ten(self):
        self.assertEqual(len(targeter.DEFAULT_TARGETS), 10)
        ranks = [t["rank"] for t in targeter.DEFAULT_TARGETS]
        self.assertEqual(ranks, list(range(1, 11)))

    def test_validate_targets_filters_empty(self):
        raw = [
            {"title": "Python-разработчик", "focus": "backend",
             "real_anchors": ["Python"], "match_keywords": ["python"]},
            {"title": ""},
            "мусор",
        ]
        result = targeter.validate_targets(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["focus"], "backend")
        self.assertEqual(result[0]["rank"], 1)

    def test_profile_summary_includes_projects(self):
        profile = {
            "level": "Junior",
            "format": ["удалённо"],
            "salary": {"note": "50–70"},
            "it_experience": "6 месяцев",
            "hard_skills": ["Python"],
            "soft_skills": ["командная работа"],
            "projects": [{"name": "hh-ai-agent", "result": "460+ карточек"}],
        }
        text = targeter.profile_summary(profile)
        self.assertIn("hh-ai-agent", text)
        self.assertIn("Python", text)

    def test_merge_with_defaults_keeps_allowed_categories(self):
        raw = [
            {"rank": 2, "focus": "backend", "title": "Backend"},
            {"rank": 1, "focus": "automation", "title": "Автоматизация"},
            {"rank": 3, "focus": "fullstack", "title": "Лишняя категория"},
        ]
        result = targeter.merge_with_defaults(raw)
        focuses = [item["focus"] for item in result]
        self.assertEqual(len(result), 10)
        self.assertEqual(focuses[0], "automation")
        self.assertEqual(focuses[1], "backend")
        self.assertNotIn("fullstack", focuses)
        self.assertEqual([item["rank"] for item in result], list(range(1, 11)))


class TestResumeGenerator(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "hard_skills": ["Python", "Flask", "SQLite", "Playwright"],
            "forbidden_claims": ["5 лет опыта", "C++"],
        }
        self.target = {
            "title": "Junior Python Backend",
            "focus": "backend",
            "real_anchors": ["Python", "Flask"],
            "missing": ["PostgreSQL"],
            "match_keywords": ["backend", "python", "flask"],
        }

    def test_clean_resume_filters_unknown_skills(self):
        raw = {
            "title": "Python-разработчик",
            "about": "Пишу на Python и Flask.",
            "skills": ["Python", "C++", "Flask"],
            "focus": "backend",
            "target_titles": ["Backend"],
            "match_keywords": ["python"],
            "honest_gaps": [],
        }
        resume, issues = gen.clean_resume(raw, self.profile, self.target, set())
        self.assertEqual(resume["skills"], ["Python", "Flask"])
        self.assertTrue(any("C++" in issue for issue in issues))

    def test_clean_resume_truncates_long_about(self):
        raw = {
            "title": "Python-разработчик",
            "about": "Я" * 1500,
            "skills": ["Python", "Flask", "SQLite"],
            "focus": "backend",
            "target_titles": ["Backend"],
            "match_keywords": ["python", "backend", "flask"],
            "honest_gaps": [],
        }
        resume, issues = gen.clean_resume(raw, self.profile, self.target, set())
        self.assertLessEqual(len(resume["about"]), 1000)
        self.assertTrue(any("обрезан" in issue for issue in issues))

    def test_shorten_about_keeps_sentence_boundary(self):
        text = ("Первое предложение. " * 80).strip()
        result = gen.shorten_about(text, 200)
        self.assertLessEqual(len(result), 200)
        self.assertTrue(result.endswith("."))

    def test_clean_resume_adds_salary_when_missing(self):
        raw = {
            "title": "Python-разработчик",
            "about": "Пишу на Python и Flask.",
            "skills": ["Python", "Flask", "SQLite"],
            "focus": "backend",
            "target_titles": ["Backend"],
            "match_keywords": ["python", "backend", "flask"],
            "honest_gaps": [],
        }
        resume, issues = gen.clean_resume(raw, self.profile, self.target, set())
        self.assertIn("50–70", resume["about"])
        self.assertLessEqual(len(resume["about"]), 1000)
        self.assertTrue(any("зарплат" in issue for issue in issues))

    def test_clean_resume_makes_title_unique(self):
        raw = {
            "title": "Python-разработчик",
            "about": "Текст",
            "skills": ["Python", "Flask", "SQLite"],
            "focus": "backend",
            "target_titles": ["Backend"],
            "match_keywords": ["python", "backend", "flask"],
            "honest_gaps": [],
        }
        resume, issues = gen.clean_resume(
            raw, self.profile, self.target, {"python-разработчик"}
        )
        self.assertNotEqual(resume["title"], "Python-разработчик")
        self.assertTrue(any("уникальным" in issue for issue in issues))

    def test_check_forbidden_detects_claims(self):
        resume = {
            "title": "Python-разработчик",
            "about": "У меня 5 лет опыта в IT.",
            "skills": ["Python"],
            "honest_gaps": [],
        }
        found = gen.check_forbidden(resume, self.profile)
        self.assertIn("5 лет опыта", found)

    def test_generate_resume_accepts_profile(self):
        raw = {
            "title": "Python-разработчик",
            "about": "Пишу на Python и Flask. Ожидания 50–70 тыс. ₽.",
            "skills": ["Python", "Flask", "SQLite"],
            "focus": "backend",
            "target_titles": ["Backend"],
            "match_keywords": ["python", "backend", "flask"],
            "honest_gaps": ["Нет PostgreSQL"],
        }
        with patch.object(gen, "ask_llm", return_value=json.dumps(raw)):
            resume, issues = gen.generate_resume(
                self.target, self.profile, "профиль", "рынок", set()
            )
        self.assertIsNotNone(resume)
        self.assertEqual(resume["id"], "backend")
        self.assertEqual(resume["skills"], ["Python", "Flask", "SQLite"])
        self.assertEqual(issues, [])

    def test_render_markdown_contains_titles_and_about(self):
        data = {
            "meta": {"created_at": "2026-11-19", "resumes_count": 1},
            "resumes": [{
                "title": "Python-разработчик",
                "about": "Пишу на Python.",
                "skills": ["Python", "Flask"],
                "focus": "backend",
                "target_titles": ["Backend"],
                "match_keywords": ["python"],
                "honest_gaps": ["Нет PostgreSQL"],
            }],
        }
        text = gen.render_markdown(data)
        self.assertIn("Python-разработчик", text)
        self.assertIn("Пишу на Python.", text)
        self.assertIn("Нет PostgreSQL", text)


class TestBuildProfile(unittest.TestCase):
    def test_profile_structure(self):
        profile = build_user_profile.build_profile()
        self.assertEqual(profile["level"], "Junior/Junior+")
        self.assertEqual(len(profile["projects"]), 3)
        self.assertIn("meme-bot", profile["projects"][2]["name"].lower())
        self.assertEqual(profile["salary"]["min"], 50000)
        self.assertEqual(profile["salary"]["comfort"], 70000)
        self.assertIn("Python", profile["hard_skills"])
        self.assertIn("коммерческий опыт в IT", profile["forbidden_claims"])
        self.assertTrue(profile["contacts"]["github"].startswith("https://"))


class TestPaths(unittest.TestCase):
    def test_new_paths_are_under_base_dir(self):
        for path in (
            VACANCY_DETAILS_FILE,
            MARKET_TRENDS_FILE,
            USER_PROFILE_FILE,
            RESUME_TARGETS_FILE,
            GENERATED_RESUMES_FILE,
        ):
            self.assertTrue(path.is_absolute())


if __name__ == "__main__":
    unittest.main()
