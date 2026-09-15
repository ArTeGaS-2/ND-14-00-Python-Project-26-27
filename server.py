"""API навчального розкладу: SQLite зберігає датовані зміни, оцінки та записи.

Демонстраційні ролі вибираються в інтерфейсі. Це не система справжнього входу.
"""

import json
import re
import sqlite3
import uuid
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent
SEED = json.loads((ROOT / "seed.json").read_text(encoding="utf-8"))
FIELDS = ["id", "date", "class_name", "subject", "topic", "start_time", "end_time", "position", "room", "online", "deleted", "version"]


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def require(condition, message, status=400):
    if not condition:
        raise APIError(status, message)


def checked_date(value):
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), "Вкажи правильну дату.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise APIError(400, "Такої дати не існує.")
    require(2000 <= parsed.year <= 2100, "Обери дату між 2000 та 2100 роками.")
    return parsed


def text_field(value, label, limit, required=True):
    require(isinstance(value, str), f"Перевір поле «{label}».")
    value = value.strip()
    require((bool(value) or not required) and len(value) <= limit, f"Поле «{label}»: {'1' if required else '0'}–{limit} символів.")
    return value


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ScheduleStore:
    def __init__(self, database):
        self.database = Path(database)

    def initialize(self):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] == 0:
                schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
                db.executescript("BEGIN;\n" + schema + "\nPRAGMA user_version=1;\nCOMMIT;")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def query(self, sql, params=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def actor(self, headers):
        role = headers.get("X-Demo-Role", "")
        require(role in ("teacher", "student"), "Обери режим учня або викладача.", 403)
        student = next((s for s in SEED["students"] if s["id"] == headers.get("X-Student-Id")), None)
        require(role != "student" or student is not None, "Обери профіль учня.", 403)
        return {"role": role, "student": student}

    def templates(self, day):
        return [dict(item, id=f"t:{day.isoformat()}:{i}", date=day.isoformat(), version=0, deleted=0)
                for i, item in enumerate(SEED["templates"][day.weekday()] if day.weekday() < 5 else [])]

    def lesson(self, lesson_id):
        rows = self.query("SELECT * FROM lesson_overrides WHERE id = ?", (lesson_id,))
        if rows:
            require(not rows[0]["deleted"], "Заняття видалене. Онови розклад.", 404)
            return rows[0]
        match = re.fullmatch(r"t:(\d{4}-\d{2}-\d{2}):(\d+)", lesson_id)
        if match:
            items = self.templates(checked_date(match[1]))
            if int(match[2]) < len(items):
                return items[int(match[2])]
        raise APIError(404, "Заняття не знайдено.")

    def allowed_lesson(self, lesson_id, actor):
        item = self.lesson(lesson_id)
        require(actor["role"] == "teacher" or item["class_name"] == actor["student"]["class_name"], "Це заняття іншого класу.", 403)
        return item

    def week(self, start, actor):
        first = checked_date(start)
        last = first + timedelta(days=6)
        values = {}
        for i in range(7):
            for item in self.templates(first + timedelta(days=i)):
                values[item["id"]] = item
        for item in self.query("SELECT * FROM lesson_overrides WHERE date >= ? AND date <= ?", (start, last.isoformat())):
            values[item["id"]] = item
        lessons = [item for item in values.values() if not item["deleted"] and
                   (actor["role"] == "teacher" or item["class_name"] == actor["student"]["class_name"])]
        return {"lessons": sorted(lessons, key=lambda item: (item["date"], item["start_time"], item["position"], item["id"]))}

    def details(self, lesson_id, actor):
        item = self.allowed_lesson(lesson_id, actor)
        roster = [student for student in SEED["students"] if student["class_name"] == item["class_name"]]
        grade_rows = self.query("SELECT * FROM grades WHERE lesson_id = ?", (lesson_id,))
        note = ""
        if actor["role"] == "student":
            roster = [actor["student"]]
            grade_rows = [row for row in grade_rows if row["student_id"] == actor["student"]["id"]]
            rows = self.query("SELECT body FROM student_notes WHERE lesson_id = ? AND student_id = ?", (lesson_id, actor["student"]["id"]))
            note = rows[0]["body"] if rows else ""
        comments = self.query("SELECT * FROM comments WHERE lesson_id = ? ORDER BY created_at, id", (lesson_id,))
        names = {student["id"]: student["name"] for student in SEED["students"]}
        for comment in comments:
            comment["author"] = names.get(comment["student_id"], "Учень")
            comment["own"] = actor["role"] == "student" and comment["student_id"] == actor["student"]["id"]
        return {"lesson": item, "students": roster, "grades": grade_rows, "note": note, "comments": comments}

    def validate_lesson(self, data, previous=None):
        day = checked_date(data.get("date"))
        if previous:
            require(day.isoformat() == previous["date"], "Дату наявного заняття змінити не можна. Додай його на інший день.")
        result = {"date": day.isoformat()}
        for key, label, limit, required in [("class_name", "Клас", 30, True), ("subject", "Предмет", 100, True), ("topic", "Тема", 300, True), ("room", "Кабінет", 40, False)]:
            result[key] = text_field(data.get(key, ""), label, limit, required)
        require(result["class_name"] in SEED["classes"], "Обери клас зі списку.")
        for key in ("start_time", "end_time"):
            require(isinstance(data.get(key), str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", data[key]), "Перевір час уроку.")
            result[key] = data[key]
        require(result["start_time"] < result["end_time"], "Кінець уроку має бути після початку.")
        require(type(data.get("position")) is int and 1 <= data["position"] <= 20, "Номер уроку: від 1 до 20.")
        require(type(data.get("online")) is bool, "Перевір формат уроку.")
        result.update(position=data["position"], online=int(data["online"]), deleted=0)
        if previous and previous["class_name"] != result["class_name"]:
            activity = sum(self.query(f"SELECT COUNT(*) AS n FROM {table} WHERE lesson_id = ?", (previous["id"],))[0]["n"] for table in ("grades", "student_notes", "comments"))
            require(not activity, "До заняття вже є оцінки або записи. Створи нове заняття для іншого класу.", 409)
        return result

    def write_lesson(self, item, expected):
        require(type(expected) is int and expected >= 0, "Онови заняття перед збереженням.")
        values = dict(item, version=1)
        updates = ", ".join(f"{key}=excluded.{key}" for key in FIELDS if key not in ("id", "version"))
        sql = f"INSERT INTO lesson_overrides ({', '.join(FIELDS)}) VALUES ({', '.join('?' for _ in FIELDS)}) ON CONFLICT(id) DO UPDATE SET {updates}, version=lesson_overrides.version+1 WHERE lesson_overrides.version = ?"
        with self.connect() as db:
            result = db.execute(sql, [values[key] for key in FIELDS] + [expected])
            require(result.rowcount == 1, "Це заняття вже змінилося в іншій вкладці. Онови розклад і повтори зміни.", 409)

    def dispatch(self, method, path, query, data, headers):
        actor = self.actor(headers)
        if method == "GET" and path == "/api/bootstrap":
            return {"classes": SEED["classes"], "students": SEED["students"], "demo": True}
        if method == "GET" and path == "/api/week":
            return self.week(query.get("start", ""), actor)
        if method == "GET" and path == "/api/lesson":
            return self.details(query.get("id", ""), actor)
        if method == "POST" and path == "/api/lessons":
            require(actor["role"] == "teacher", "Додавати заняття може викладач.", 403)
            item = self.validate_lesson(data)
            item["id"] = "a:" + str(uuid.uuid4())
            self.write_lesson(item, 0)
            return {"lesson": self.lesson(item["id"])}
        if path == "/api/lesson" and method in ("PUT", "DELETE"):
            require(actor["role"] == "teacher", "Змінювати заняття може викладач.", 403)
            previous = self.lesson(data.get("id", ""))
            require(type(data.get("version")) is int and data["version"] == previous["version"], "Це заняття вже змінилося. Онови його перед збереженням.", 409)
            item = dict(previous, deleted=1) if method == "DELETE" else dict(self.validate_lesson(data, previous), id=previous["id"])
            self.write_lesson(item, data.get("version"))
            return {"deleted": True} if method == "DELETE" else {"lesson": self.lesson(item["id"])}
        if method == "PUT" and path == "/api/grades":
            require(actor["role"] == "teacher", "Ставити оцінки може викладач.", 403)
            item = self.lesson(data.get("lesson_id", ""))
            rows = data.get("grades")
            require(isinstance(rows, list) and 0 < len(rows) <= 100, "Перевір список оцінок.")
            roster = {s["id"] for s in SEED["students"] if s["class_name"] == item["class_name"]}
            seen, operations = set(), []
            for row in rows:
                require(isinstance(row, dict), "Перевір список оцінок.")
                sid, grade = row.get("student_id"), row.get("grade")
                require(sid in roster and sid not in seen, "Перевір учня в оцінюванні.")
                seen.add(sid)
                feedback = text_field(row.get("feedback", ""), "Коментар до оцінки", 1000, False)
                require(grade is None or type(grade) is int and 1 <= grade <= 12, "Оцінка має бути від 1 до 12.")
                if grade is None:
                    operations.append(("DELETE FROM grades WHERE lesson_id = ? AND student_id = ?", (item["id"], sid)))
                else:
                    operations.append(("INSERT INTO grades (lesson_id, student_id, grade, feedback, updated_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(lesson_id, student_id) DO UPDATE SET grade=excluded.grade, feedback=excluded.feedback, updated_at=excluded.updated_at", (item["id"], sid, grade, feedback, now())))
            with self.connect() as db:
                for sql, values in operations:
                    db.execute(sql, values)
            return {"saved": True}
        if method == "PUT" and path == "/api/note":
            require(actor["role"] == "student", "Обери профіль учня для запису.", 403)
            item = self.allowed_lesson(data.get("lesson_id", ""), actor)
            body = text_field(data.get("body", ""), "Запис", 5000, False)
            with self.connect() as db:
                db.execute("INSERT INTO student_notes (lesson_id, student_id, body, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(lesson_id, student_id) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at", (item["id"], actor["student"]["id"], body, now()))
            return {"saved": True}
        if method == "POST" and path == "/api/comments":
            require(actor["role"] == "student", "Коментар залишає обраний учень.", 403)
            item = self.allowed_lesson(data.get("lesson_id", ""), actor)
            body = text_field(data.get("body", ""), "Коментар", 2000)
            comment_id = str(uuid.uuid4())
            with self.connect() as db:
                db.execute("INSERT INTO comments (id, lesson_id, student_id, body, created_at) VALUES (?, ?, ?, ?, ?)", (comment_id, item["id"], actor["student"]["id"], body, now()))
            return {"id": comment_id}
        if path == "/api/comment" and method in ("PUT", "DELETE"):
            require(actor["role"] == "student", "Змінювати можна власні коментарі.", 403)
            rows = self.query("SELECT * FROM comments WHERE id = ?", (data.get("id", ""),))
            require(bool(rows), "Коментар не знайдено.", 404)
            require(rows[0]["student_id"] == actor["student"]["id"], "Це коментар іншого учня.", 403)
            self.allowed_lesson(rows[0]["lesson_id"], actor)
            with self.connect() as db:
                if method == "DELETE":
                    db.execute("DELETE FROM comments WHERE id = ?", (rows[0]["id"],))
                else:
                    db.execute("UPDATE comments SET body = ? WHERE id = ?", (text_field(data.get("body", ""), "Коментар", 2000), rows[0]["id"]))
            return {"saved": True}
        raise APIError(404, "Такого запиту немає.")
