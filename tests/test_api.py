"""Перевірка реальних сценаріїв з окремою тимчасовою SQLite-базою."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import ScheduleStore, SEED, APIError


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ScheduleStore(Path(self.temp.name) / "test.sqlite3")
        self.store.initialize()
        self.teacher = {"X-Demo-Role": "teacher"}
        self.roster = [s for s in SEED["students"] if s["class_name"] == "6-А"]
        self.student = {"X-Demo-Role": "student", "X-Student-Id": self.roster[0]["id"]}
        self.other = {"X-Demo-Role": "student", "X-Student-Id": self.roster[1]["id"]}
        self.lesson_id = "t:2026-09-14:0"

    def tearDown(self):
        self.temp.cleanup()

    def call(self, method, path, body=None, user=None, **query):
        return self.store.dispatch(method, path, query, body or {}, user or self.teacher)

    def lesson(self, user=None):
        return self.call("GET", "/api/lesson", user=user, id=self.lesson_id)

    def grade(self, value=10):
        return self.call("PUT", "/api/grades", {"lesson_id": self.lesson_id, "grades": [{"student_id": self.roster[0]["id"], "grade": value, "feedback": "Добре попрацював"}]})

    def test_edit_is_specific_to_date_and_stale_edit_rejected(self):
        original = self.lesson()["lesson"]
        payload = dict(original, topic="Нова тема", online=bool(original["online"]))
        saved = self.call("PUT", "/api/lesson", payload)["lesson"]
        self.assertEqual(saved["topic"], "Нова тема")
        self.assertEqual(saved["version"], 1)
        with self.assertRaises(APIError) as error:
            self.call("PUT", "/api/lesson", payload)
        self.assertEqual(error.exception.status, 409)
        next_week = self.call("GET", "/api/lesson", id="t:2026-09-21:0")["lesson"]
        self.assertEqual(next_week["topic"], original["topic"])

    def test_add_saturday_and_delete_persists_after_restart(self):
        payload = dict(self.lesson()["lesson"], date="2026-09-19", online=False, topic="Додаткове заняття", position=6)
        added = self.call("POST", "/api/lessons", payload)["lesson"]
        self.assertEqual(len(self.call("GET", "/api/week", start="2026-09-14")["lessons"]), 26)
        self.call("DELETE", "/api/lesson", {"id": added["id"], "version": added["version"]})
        restarted = ScheduleStore(self.store.database)
        restarted.initialize()
        self.assertEqual(len(restarted.dispatch("GET", "/api/week", {"start": "2026-09-14"}, {}, self.teacher)["lessons"]), 25)

    def test_grades_are_individual_and_survive_restart(self):
        self.grade(11)
        self.assertEqual(self.lesson(self.student)["grades"][0]["grade"], 11)
        self.assertEqual(self.lesson(self.other)["grades"], [])
        self.store = ScheduleStore(self.store.database)
        self.store.initialize()
        self.assertEqual(self.lesson(self.student)["grades"][0]["grade"], 11)
        self.grade(None)
        self.assertEqual(self.lesson(self.student)["grades"], [])

    def test_invalid_grade_batch_does_not_partially_save(self):
        self.grade(9)
        with self.assertRaises(APIError):
            self.call("PUT", "/api/grades", {"lesson_id": self.lesson_id, "grades": [{"student_id": self.roster[0]["id"], "grade": 7}, {"student_id": self.roster[1]["id"], "grade": 13}]})
        self.assertEqual(self.lesson(self.student)["grades"][0]["grade"], 9)

    def test_student_cannot_edit_lessons_or_grade(self):
        payload = dict(self.lesson()["lesson"], online=True)
        for method, path, data in [("PUT", "/api/lesson", payload), ("POST", "/api/lessons", payload), ("DELETE", "/api/lesson", payload), ("PUT", "/api/grades", {"lesson_id": self.lesson_id, "grades": []})]:
            with self.assertRaises(APIError) as error:
                self.call(method, path, data, user=self.student)
            self.assertEqual(error.exception.status, 403)

    def test_notes_are_private_and_persistent(self):
        self.call("PUT", "/api/note", {"lesson_id": self.lesson_id, "body": "Мій особистий запис"}, user=self.student)
        self.assertEqual(self.lesson(self.student)["note"], "Мій особистий запис")
        self.assertEqual(self.lesson(self.other)["note"], "")
        self.assertEqual(self.lesson()["note"], "")
        self.store.initialize()
        self.assertEqual(self.lesson(self.student)["note"], "Мій особистий запис")

    def test_comments_shared_in_class_and_only_owner_changes_them(self):
        comment = self.call("POST", "/api/comments", {"lesson_id": self.lesson_id, "body": "Чи буде практика?"}, user=self.student)
        self.assertEqual(self.lesson()["comments"][0]["body"], "Чи буде практика?")
        self.assertFalse(self.lesson(self.other)["comments"][0]["own"])
        with self.assertRaises(APIError) as error:
            self.call("DELETE", "/api/comment", comment, user=self.other)
        self.assertEqual(error.exception.status, 403)
        self.call("PUT", "/api/comment", dict(comment, body="Виправлений коментар"), user=self.student)
        self.assertEqual(self.lesson(self.other)["comments"][0]["body"], "Виправлений коментар")
        self.call("DELETE", "/api/comment", comment, user=self.student)
        self.assertEqual(self.lesson()["comments"], [])

    def test_other_class_cannot_read_or_write_to_lesson(self):
        sid = next(s["id"] for s in SEED["students"] if s["class_name"] != "6-А")
        user = {"X-Demo-Role": "student", "X-Student-Id": sid}
        for method, path, data, query in [("GET", "/api/lesson", {}, {"id": self.lesson_id}), ("PUT", "/api/note", {"lesson_id": self.lesson_id, "body": "Чужий запис"}, {})]:
            with self.assertRaises(APIError) as error:
                self.call(method, path, data, user=user, **query)
            self.assertEqual(error.exception.status, 403)

    def test_deletion_hides_one_date_but_preserves_associated_records(self):
        self.grade(10)
        self.call("DELETE", "/api/lesson", {"id": self.lesson_id, "version": 0})
        self.assertEqual(len(self.call("GET", "/api/week", start="2026-09-14")["lessons"]), 24)
        self.assertEqual(len(self.call("GET", "/api/week", start="2026-09-21")["lessons"]), 25)
        self.assertEqual(self.store.query("SELECT grade FROM grades WHERE lesson_id = ?", (self.lesson_id,))[0]["grade"], 10)

    def test_class_cannot_change_after_grades_or_notes(self):
        self.grade()
        original = self.lesson()["lesson"]
        with self.assertRaises(APIError) as error:
            self.call("PUT", "/api/lesson", dict(original, class_name="6-Б", online=True))
        self.assertEqual(error.exception.status, 409)


if __name__ == "__main__":
    unittest.main()
