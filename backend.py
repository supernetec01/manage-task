"""Shared SQLite storage and authorization for the Content Marketing workspace."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("SUPERNET_DATA_DIR", str(ROOT / "data"))).resolve()
MANAGERS = {"admin", "manager"}
ROLES = {"admin", "manager", "content", "intern"}
STAGE_KEYS = ("script", "shoot", "edit")
STAGE_LABELS = {"script": "Kịch bản", "shoot": "Quay", "edit": "Dựng"}
TZ = timezone(timedelta(hours=7))
PASSWORD_ITERATIONS = 350_000
SESSION_SECONDS = 12 * 60 * 60


class APIError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(message)


def now():
    return datetime.now(TZ).isoformat(timespec="seconds")


def today():
    return datetime.now(TZ).date().isoformat()


def connect():
    con = sqlite3.connect(DATA_DIR / "supernet.db", timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def initialize():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        DATA_DIR.chmod(0o700)
    except OSError:
        pass
    with connect() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            capacity REAL NOT NULL DEFAULT 40,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            csrf TEXT NOT NULL,
            expires REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id),
            kind TEXT NOT NULL,
            period TEXT NOT NULL,
            payload TEXT NOT NULL,
            UNIQUE(owner_id, kind, period)
        );
        CREATE TABLE IF NOT EXISTS login_attempts (
            key TEXT PRIMARY KEY,
            count INTEGER NOT NULL,
            window REAL NOT NULL
        );
        """)
    try:
        (DATA_DIR / "supernet.db").chmod(0o600)
    except OSError:
        pass


def public_user(row):
    return {"id": row["id"], "name": row["name"], "username": row["username"],
            "role": row["role"], "active": bool(row["active"]), "capacity": row["capacity"]}


def text(data, key, *, required=False, maxlen=4000, default=""):
    value = data.get(key, default)
    if not isinstance(value, str) or len(value) > maxlen:
        raise APIError(400, f"Thông tin '{key}' không hợp lệ (tối đa {maxlen} ký tự).")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise APIError(400, f"Thông tin '{key}' chứa ký tự không hợp lệ.")
    value = value.strip()
    if required and not value:
        raise APIError(400, f"Vui lòng nhập '{key}'.")
    return value


def number(value, field, low=0, high=100000):
    if isinstance(value, bool):
        raise APIError(400, f"{field} không hợp lệ.")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise APIError(400, f"{field} không hợp lệ.")
    if not math.isfinite(value) or not low <= value <= high:
        raise APIError(400, f"{field} phải từ {low} đến {high}.")
    return value


def date_value(value, field="Ngày"):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise APIError(400, f"{field} phải có dạng YYYY-MM-DD.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise APIError(400, f"{field} không hợp lệ.")
    return value


def valid_url(value, field):
    if not isinstance(value, str) or len(value) > 3000:
        raise APIError(400, f"{field} không hợp lệ.")
    if value:
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError()
        except ValueError:
            raise APIError(400, f"{field} phải là đường dẫn http hoặc https hợp lệ.")
    return value


def require_manager(user):
    if user["role"] not in MANAGERS:
        raise APIError(403, "Chức năng này chỉ dành cho quản lý.")


def validate_password(password):
    if not isinstance(password, str) or len(password) < 10 or len(password) > 256:
        raise APIError(400, "Mật khẩu phải từ 10 đến 256 ký tự.")
    try:
        password.encode("utf-8")
    except UnicodeError:
        raise APIError(400, "Mật khẩu chứa ký tự không hợp lệ.")
    return password


def hash_password(password):
    validate_password(password)
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PASSWORD_ITERATIONS).hex()
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}"


def password_matches(password, encoded):
    if not isinstance(password, str) or len(password) > 256:
        return False
    try:
        _, iterations, salt, expected = encoded.split("$")
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def username_value(data):
    value = text(data, "username", required=True, maxlen=60).lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._@+-]{2,59}", value):
        raise APIError(400, "Tên đăng nhập cần 3–60 ký tự, dùng chữ không dấu, số, dấu chấm, @, +, - hoặc _.")
    return value


def new_session(con, user_id):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    con.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
    con.execute("INSERT INTO sessions VALUES (?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf, time.time() + SESSION_SECONDS))
    return token, csrf


def setup_required():
    with connect() as con:
        return con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def setup(data):
    username = username_value(data)
    name = text(data, "name", required=True, maxlen=120)
    password_hash = hash_password(data.get("password"))
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise APIError(409, "Đã có tài khoản quản trị. Vui lòng đăng nhập.")
        cursor = con.execute("INSERT INTO users(username,name,role,password_hash,created_at) VALUES (?,?,?,?,?)", (username, name, "admin", password_hash, now()))
        user = public_user(con.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone())
        token, csrf = new_session(con, user["id"])
    return {"user": user, "csrfToken": csrf}, token


def login(data, ip):
    username = text(data, "username", maxlen=100).lower()
    password = data.get("password", "")
    # Two keys limit both password guessing against an account and high-volume requests per IP.
    keys = ["account:" + username, "ip:" + ip]
    stamp = time.time()
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        con.execute("DELETE FROM login_attempts WHERE window < ?", (stamp - 900,))
        for key in keys:
            row = con.execute("SELECT * FROM login_attempts WHERE key=?", (key,)).fetchone()
            if row and row["count"] >= (10 if key.startswith("account:") else 60):
                raise APIError(429, "Đăng nhập sai quá nhiều lần. Vui lòng thử lại sau 15 phút.")
        row = con.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
        if not row or not row["active"] or not password_matches(password, row["password_hash"]):
            # Consume the same password KDF cost for unknown usernames.
            if not row:
                hashlib.pbkdf2_hmac("sha256", str(password)[:256].encode(), b"no-such-user-salt", PASSWORD_ITERATIONS)
            for key in keys:
                con.execute("INSERT INTO login_attempts VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1", (key, stamp))
            con.commit()
            raise APIError(401, "Tên đăng nhập hoặc mật khẩu không đúng, hoặc tài khoản đã bị khóa.")
        con.execute("DELETE FROM login_attempts WHERE key=?", (keys[0],))
        token, csrf = new_session(con, row["id"])
        return {"user": public_user(row), "csrfToken": csrf}, token


def authenticate(token):
    if not token:
        raise APIError(401, "Vui lòng đăng nhập để tiếp tục.")
    digest = hashlib.sha256(token.encode()).hexdigest()
    with connect() as con:
        row = con.execute("SELECT u.*,s.csrf,s.expires FROM sessions s JOIN users u ON u.id=s.user_id WHERE token_hash=?", (digest,)).fetchone()
        if not row or not row["active"] or row["expires"] <= time.time():
            raise APIError(401, "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.")
        return public_user(row), row["csrf"]


def logout(token):
    with connect() as con:
        con.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))


def change_password(user, data):
    with connect() as con:
        row = con.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
        if not password_matches(data.get("currentPassword"), row[0]):
            raise APIError(400, "Mật khẩu hiện tại không đúng.")
        con.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(data.get("newPassword")), user["id"]))
        con.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    return {"ok": True, "message": "Đã đổi mật khẩu. Vui lòng đăng nhập lại."}


def user_id(con, value, field="Nhân viên", *, manager=False):
    if isinstance(value, bool):
        raise APIError(400, f"{field} không hợp lệ.")
    if isinstance(value, float) and not value.is_integer():
        raise APIError(400, f"{field} không hợp lệ.")
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise APIError(400, f"{field} không hợp lệ.")
    if not 1 <= value <= 2**63 - 1:
        raise APIError(400, f"{field} không hợp lệ.")
    row = con.execute("SELECT * FROM users WHERE id=?", (value,)).fetchone()
    if not row or not row["active"] or manager and row["role"] not in MANAGERS:
        raise APIError(400, f"{field} không tồn tại, bị khóa hoặc không đúng vai trò.")
    return value


def create_user(user, data):
    require_manager(user)
    role = data.get("role", "content")
    if not isinstance(role, str) or role not in ROLES:
        raise APIError(400, "Vai trò không hợp lệ.")
    if user["role"] != "admin" and role in MANAGERS:
        raise APIError(403, "Bạn chỉ được tạo tài khoản Content Marketing hoặc thực tập sinh.")
    name = text(data, "name", required=True, maxlen=120)
    username = username_value(data)
    password = hash_password(data.get("password"))
    capacity = number(data.get("capacity", 24 if role == "intern" else 40), "Năng lực tuần", 1, 168)
    with connect() as con:
        try:
            cursor = con.execute("INSERT INTO users(username,name,role,capacity,password_hash,created_at) VALUES (?,?,?,?,?,?)", (username, name, role, capacity, password, now()))
        except sqlite3.IntegrityError:
            raise APIError(409, "Tên đăng nhập đã được sử dụng.")
        return public_user(con.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone())


def patch_user(user, target_id, data):
    require_manager(user)
    allowed = {"name", "role", "active", "capacity", "password"}
    if set(data) - allowed:
        raise APIError(400, "Thông tin cập nhật nhân viên không hợp lệ.")
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM users WHERE id=?", (target_id,)).fetchone()
        if not row:
            raise APIError(404, "Không tìm thấy nhân viên.")
        if user["role"] != "admin" and row["role"] in MANAGERS:
            raise APIError(403, "Chỉ quản trị viên được thay đổi tài khoản quản lý.")
        role = data.get("role", row["role"])
        if not isinstance(role, str) or role not in ROLES:
            raise APIError(400, "Vai trò không hợp lệ.")
        if user["role"] != "admin" and role in MANAGERS:
            raise APIError(403, "Bạn không có quyền cấp vai trò này.")
        active = data.get("active", bool(row["active"]))
        if not isinstance(active, bool):
            raise APIError(400, "Trạng thái tài khoản không hợp lệ.")
        if row["role"] == "admin" and row["active"] and (role != "admin" or not active):
            if con.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0] <= 1:
                raise APIError(400, "Cần giữ ít nhất một quản trị viên đang hoạt động.")
        name = text(data, "name", required=True, maxlen=120, default=row["name"])
        capacity = number(data.get("capacity", row["capacity"]), "Năng lực tuần", 1, 168)
        password_hash = hash_password(data["password"]) if data.get("password") else row["password_hash"]
        con.execute("UPDATE users SET name=?,role=?,active=?,capacity=?,password_hash=? WHERE id=?", (name, role, int(active), capacity, password_hash, target_id))
        if "role" in data or "active" in data or data.get("password"):
            con.execute("DELETE FROM sessions WHERE user_id=?", (target_id,))
        return public_user(con.execute("SELECT * FROM users WHERE id=?", (target_id,)).fetchone())


def assigned(task, user):
    return task["ownerId"] == user["id"] or any(stage["ownerId"] == user["id"] for stage in task["stages"])


def can_view(task, user):
    return user["role"] in MANAGERS or assigned(task, user)


def load_task(con, task_id, user):
    row = con.execute("SELECT payload FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise APIError(404, "Không tìm thấy công việc.")
    task = json.loads(row[0])
    if not can_view(task, user):
        raise APIError(403, "Bạn không được truy cập công việc này.")
    return task


def record(task, user, action, changes=None):
    entry = {"at": now(), "actor": user["name"], "actorId": user["id"], "action": action}
    if changes:
        entry["changes"] = changes
    task["history"].insert(0, entry)


def describe_changes(con, old, task):
    """Keep exact before/after values plus a readable summary without credential data."""
    details, messages = [], []
    labels = {"title": "Tên công việc", "description": "Yêu cầu", "criteria": "Tiêu chí nghiệm thu",
              "channel": "Kênh", "pillar": "Pillar", "angle": "Angle", "series": "Series",
              "campaign": "Chiến dịch", "ownerId": "Người chịu trách nhiệm", "reviewerId": "Người duyệt",
              "due": "Hạn hoàn thành", "priority": "Ưu tiên", "estimatedHours": "Giờ dự kiến",
              "nextStep": "Bước tiếp theo", "blocker": "Vướng mắc", "evidence": "Minh chứng",
              "scriptUrl": "Link kịch bản", "publicationStatus": "Trạng thái đăng",
              "publishUrl": "Link bài đăng", "publishAt": "Thời gian đăng"}
    status_labels = {"todo": "Chưa làm", "doing": "Đang làm", "done": "Hoàn thành",
                     "unscheduled": "Chưa lên lịch", "scheduled": "Đã lên lịch", "published": "Đã đăng"}

    def person_name(value):
        row = con.execute("SELECT name FROM users WHERE id=?", (value,)).fetchone()
        return row[0] if row else str(value)

    def change(field, label, before, after, kind="text"):
        if before == after:
            return
        details.append({"field": field, "before": before, "after": after})
        if kind == "person":
            message = f"{label}: {person_name(before)} → {person_name(after)}"
        elif kind == "status":
            message = f"{label}: {status_labels.get(before, before)} → {status_labels.get(after, after)}"
        elif kind == "value":
            message = f"{label}: {before} → {after}"
        elif field.endswith("note") or field in {"nextStep", "blocker"}:
            message = f"{label}: {after[:180] if after else '(đã xóa)'}"
        else:
            message = f"Cập nhật {label.lower()}"
        messages.append(message)

    for field, label in labels.items():
        kind = "person" if field.endswith("Id") else "status" if field == "publicationStatus" else "value" if field in {"due", "estimatedHours", "priority", "publishAt"} else "text"
        change(field, label, old[field], task[field], kind)
    for previous, current in zip(old["stages"], task["stages"]):
        label = STAGE_LABELS[current["key"]]
        for field, field_label, kind in (("status", "trạng thái", "status"), ("ownerId", "người phụ trách", "person"), ("due", "hạn", "value"), ("note", "ghi chú", "text")):
            change(f"stages.{current['key']}.{field}", f"{label} — {field_label}", previous[field], current[field], kind)
    return details, messages


def write_task(con, task):
    con.execute("UPDATE tasks SET payload=? WHERE id=?", (json.dumps(task, ensure_ascii=False), task["id"]))


def validate_stages(con, stages, owner, due):
    if (not isinstance(stages, list) or len(stages) != 3
            or any(not isinstance(s, dict) or not isinstance(s.get("key"), str) for s in stages)
            or {s["key"] for s in stages} != set(STAGE_KEYS)):
        raise APIError(400, "Công việc cần đủ ba khâu: kịch bản, quay và dựng.")
    results = []
    for key in STAGE_KEYS:
        stage = next(s for s in stages if s["key"] == key)
        person = user_id(con, stage.get("ownerId", owner), "Người phụ trách khâu")
        stage_due = date_value(stage.get("due", due), "Hạn từng khâu")
        if stage_due > due:
            raise APIError(400, "Hạn từng khâu không được sau hạn cuối công việc.")
        status = stage.get("status", "todo")
        if not isinstance(status, str) or status not in {"todo", "doing", "done"}:
            raise APIError(400, "Trạng thái từng khâu không hợp lệ.")
        results.append({"key": key, "label": STAGE_LABELS[key], "ownerId": person,
                        "due": stage_due, "status": status, "note": text(stage, "note", maxlen=4000)})
    return results


def create_task(user, data):
    require_manager(user)
    with connect() as con:
        title = text(data, "title", required=True, maxlen=240)
        description = text(data, "description", required=True, maxlen=12000)
        criteria = text(data, "criteria", required=True, maxlen=8000)
        owner = user_id(con, data.get("ownerId"), "Người chịu trách nhiệm")
        reviewer = user_id(con, data.get("reviewerId", user["id"]), "Người duyệt", manager=True)
        due = date_value(data.get("due"), "Hạn hoàn thành")
        priority = data.get("priority", "normal")
        if not isinstance(priority, str) or priority not in {"low", "normal", "high", "urgent"}:
            raise APIError(400, "Mức ưu tiên không hợp lệ.")
        stages = validate_stages(con, data.get("stages", [{"key": key, "ownerId": owner, "due": due} for key in STAGE_KEYS]), owner, due)
        # Newly assigned work always begins unfinished; imports need review before acceptance.
        for stage in stages:
            stage["status"] = "todo"
        task = {"title": title, "description": description, "criteria": criteria,
                "ownerId": owner, "reviewerId": reviewer, "due": due, "originalDue": due,
                "priority": priority, "estimatedHours": number(data.get("estimatedHours", 4), "Giờ dự kiến", .5, 1000),
                "status": "pending", "stages": stages, "createdAt": now(), "acceptedAt": None,
                "publicationStatus": "unscheduled", "publishUrl": "", "publishAt": "", "history": [], "version": 1}
        for key in ("channel", "pillar", "angle", "series", "campaign", "nextStep", "blocker"):
            task[key] = text(data, key, maxlen=4000 if key in {"nextStep", "blocker"} else 240)
        for key in ("evidence", "scriptUrl"):
            task[key] = valid_url(text(data, key, maxlen=3000), key)
        cursor = con.execute("INSERT INTO tasks(payload) VALUES ('{}')")
        task["id"] = cursor.lastrowid
        record(task, user, "Tạo và giao công việc")
        write_task(con, task)
        return task


def version_check(data, task):
    if type(data.get("version")) is not int:
        raise APIError(400, "Thiếu phiên bản công việc. Hãy tải lại dữ liệu.")
    if data["version"] != task["version"]:
        raise APIError(409, "Công việc vừa được người khác cập nhật. Hãy tải lại trước khi lưu.")


def patch_task(user, task_id, data):
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        task = load_task(con, task_id, user)
        version_check(data, task)
        old = copy.deepcopy(task)
        manager = user["role"] in MANAGERS
        general = {"title", "description", "criteria", "channel", "pillar", "angle", "series", "campaign", "ownerId", "reviewerId", "due", "priority", "estimatedHours"}
        shared = {"nextStep", "blocker", "evidence", "scriptUrl", "stages", "version"}
        publication = {"publicationStatus", "publishUrl", "publishAt"}
        if set(data) - (general | shared | publication):
            raise APIError(400, "Không được thay đổi trạng thái, lịch sử hoặc trường hệ thống trực tiếp.")
        if not manager and (set(data) & general or not assigned(task, user)):
            raise APIError(403, "Bạn chỉ được cập nhật tiến độ công việc đã giao.")
        if task["status"] == "cancelled":
            raise APIError(400, "Công việc đã hủy không thể cập nhật.")
        if task["status"] == "done" and set(data) - ({"version"} | publication):
            raise APIError(400, "Công việc đã nghiệm thu chỉ được cập nhật thông tin đăng bài.")
        for key in ("title", "description", "criteria", "channel", "pillar", "angle", "series", "campaign", "nextStep", "blocker"):
            if key in data:
                task[key] = text(data, key, required=key in {"title", "description", "criteria"}, maxlen=12000 if key == "description" else 8000 if key == "criteria" else 4000 if key in {"nextStep", "blocker"} else 240)
        for key in ("ownerId", "reviewerId"):
            if key in data:
                task[key] = user_id(con, data[key], "Người duyệt" if key == "reviewerId" else "Người chịu trách nhiệm", manager=key == "reviewerId")
        if "due" in data:
            task["due"] = date_value(data["due"], "Hạn hoàn thành")
        if "priority" in data:
            if not isinstance(data["priority"], str) or data["priority"] not in {"low", "normal", "high", "urgent"}:
                raise APIError(400, "Mức ưu tiên không hợp lệ.")
            task["priority"] = data["priority"]
        if "estimatedHours" in data:
            task["estimatedHours"] = number(data["estimatedHours"], "Giờ dự kiến", .5, 1000)
        for key in ("evidence", "scriptUrl"):
            if key in data:
                task[key] = valid_url(text(data, key, maxlen=3000), key)
        if "stages" in data:
            stages = validate_stages(con, data["stages"], task["ownerId"], task["due"])
            if not manager:
                for old_stage, stage in zip(old["stages"], stages):
                    if stage["ownerId"] != old_stage["ownerId"] or stage["due"] != old_stage["due"]:
                        raise APIError(403, "Nhân viên không được đổi phân công hoặc thời hạn từng khâu.")
                    if old_stage["ownerId"] != user["id"] and stage != old_stage:
                        raise APIError(403, "Bạn chỉ được cập nhật khâu được giao cho mình.")
            task["stages"] = stages
        elif any(stage["due"] > task["due"] for stage in task["stages"]):
            raise APIError(400, "Hãy điều chỉnh hạn từng khâu trước khi rút ngắn hạn cuối.")
        if set(data) & publication:
            if not manager and user["id"] != old["ownerId"]:
                raise APIError(403, "Chỉ quản lý hoặc người chịu trách nhiệm được cập nhật đăng bài.")
            if task["status"] != "done":
                raise APIError(400, "Nội dung cần được nghiệm thu trước khi lên lịch hoặc đăng.")
            status = data.get("publicationStatus", task["publicationStatus"])
            if not isinstance(status, str) or status not in {"unscheduled", "scheduled", "published"}:
                raise APIError(400, "Trạng thái xuất bản không hợp lệ.")
            task["publicationStatus"] = status
            if "publishUrl" in data:
                task["publishUrl"] = valid_url(text(data, "publishUrl", maxlen=3000), "Link bài đăng")
            if "publishAt" in data:
                task["publishAt"] = text(data, "publishAt", maxlen=64)
            if status in {"scheduled", "published"}:
                try:
                    if not task["publishAt"] or "T" not in task["publishAt"]:
                        raise ValueError()
                    datetime.fromisoformat(task["publishAt"].replace("Z", "+00:00"))
                except ValueError:
                    raise APIError(400, "Vui lòng nhập ngày và giờ đăng hợp lệ.")
            if status == "published" and not task["publishUrl"]:
                raise APIError(400, "Nội dung đã đăng cần có đường dẫn bài đăng.")
        if task != old:
            details, messages = describe_changes(con, old, task)
            task["version"] += 1
            record(task, user, "; ".join(messages) or "Cập nhật công việc", details)
            write_task(con, task)
        return task


def task_action(user, task_id, data):
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        task = load_task(con, task_id, user)
        version_check(data, task)
        previous_status = task["status"]
        previous_version = task["version"]
        action = data.get("action")
        if not isinstance(action, str):
            raise APIError(400, "Thao tác công việc không hợp lệ.")
        note = text(data, "note", maxlen=4000)
        manager = user["role"] in MANAGERS
        if action in {"approve", "request_changes"}:
            require_manager(user)
            if user["role"] != "admin" and task["reviewerId"] != user["id"]:
                raise APIError(403, "Bạn không phải người duyệt được phân công.")
            if task["status"] != "review":
                raise APIError(400, "Công việc chưa ở trạng thái chờ duyệt.")
            if action == "approve":
                if not task["evidence"] or not all(s["status"] == "done" for s in task["stages"]):
                    raise APIError(400, "Cần đủ khâu hoàn thành và minh chứng trước khi nghiệm thu.")
                task["status"] = "done"
                task["acceptedAt"] = now()
                message = "Nghiệm thu sản phẩm"
            else:
                if not note:
                    raise APIError(400, "Vui lòng ghi rõ yêu cầu chỉnh sửa.")
                task["status"] = "revision"
                message = "Yêu cầu chỉnh sửa"
        elif action == "cancel":
            require_manager(user)
            if task["status"] in {"done", "cancelled"}:
                raise APIError(400, "Không thể hủy công việc đã nghiệm thu hoặc đã hủy.")
            if not note:
                raise APIError(400, "Vui lòng nhập lý do hủy.")
            task["status"] = "cancelled"
            message = "Hủy công việc"
        elif action in {"start", "submit"}:
            if not manager and not assigned(task, user):
                raise APIError(403, "Bạn không được giao công việc này.")
            if action == "start":
                if task["status"] not in {"pending", "revision"}:
                    raise APIError(400, "Công việc không ở trạng thái có thể bắt đầu.")
                task["status"] = "doing"
                message = "Nhận việc và bắt đầu thực hiện"
            else:
                if task["status"] not in {"doing", "revision"}:
                    raise APIError(400, "Cần bắt đầu thực hiện trước khi nộp duyệt.")
                if not all(s["status"] == "done" for s in task["stages"]):
                    raise APIError(400, "Hãy hoàn thành cả ba khâu trước khi nộp duyệt.")
                if not task["evidence"] or not task["criteria"]:
                    raise APIError(400, "Cần link sản phẩm bàn giao và tiêu chí nghiệm thu.")
                if task["blocker"]:
                    raise APIError(400, "Hãy giải quyết hoặc xóa vướng mắc trước khi nộp duyệt.")
                task["status"] = "review"
                message = "Nộp sản phẩm chờ duyệt"
        else:
            raise APIError(400, "Thao tác công việc không hợp lệ.")
        task["version"] += 1
        details = [{"field": "status", "before": previous_status, "after": task["status"]}]
        if action == "approve":
            details.extend([{"field": "reviewedVersion", "before": None, "after": previous_version},
                            {"field": "evidenceReviewed", "before": None, "after": task["evidence"]}])
            message += f" (phiên bản {previous_version})"
        record(task, user, message + (": " + note if note else ""), details)
        write_task(con, task)
        return task


def all_tasks(con):
    return [json.loads(row[0]) for row in con.execute("SELECT payload FROM tasks ORDER BY id DESC")]


def period_range(kind, period):
    if not isinstance(kind, str) or kind not in {"daily", "weekly"}:
        raise APIError(400, "Loại báo cáo phải là daily hoặc weekly.")
    current = date.fromisoformat(date_value(period, "Kỳ báo cáo"))
    if kind == "weekly":
        current -= timedelta(days=current.weekday())
    try:
        end = current + timedelta(days=6 if kind == "weekly" else 0)
    except OverflowError:
        raise APIError(400, "Kỳ báo cáo nằm ngoài phạm vi ngày hợp lệ.")
    return current.isoformat(), end.isoformat()


def report_summary(con, owner, kind, period):
    start, end = period_range(kind, period)
    own = {"id": owner}
    tasks = [task for task in all_tasks(con) if assigned(task, own) and start <= task["due"] <= end and task["status"] != "cancelled"]
    # Metrics are an as-of-now view of tasks due in the period, not an activity time-sheet.
    return {"kind": kind, "period": start, "end": end, "ownerId": owner,
            "total": len(tasks), "done": sum(t["status"] == "done" for t in tasks),
            "overdue": sum(t["due"] < today() and t["status"] not in {"done", "cancelled"} for t in tasks),
            "blocked": sum(bool(t["blocker"]) and t["status"] not in {"done", "cancelled"} for t in tasks),
            "tasks": tasks}


def get_summary(user, query):
    owner = query.get("ownerId", [str(user["id"])])[0]
    try:
        owner = int(owner)
    except (ValueError, TypeError):
        raise APIError(400, "Người báo cáo không hợp lệ.")
    if owner != user["id"]:
        require_manager(user)
    with connect() as con:
        if not con.execute("SELECT 1 FROM users WHERE id=?", (owner,)).fetchone():
            raise APIError(404, "Không tìm thấy nhân viên.")
        return report_summary(con, owner, query.get("kind", ["daily"])[0], query.get("period", [today()])[0])


def create_report(user, data):
    if "ownerId" in data and data["ownerId"] != user["id"]:
        raise APIError(403, "Bạn chỉ được nộp báo cáo của chính mình.")
    kind = data.get("kind", "daily")
    start, end = period_range(kind, data.get("period", today()))
    if start > today():
        raise APIError(400, "Chưa thể nộp báo cáo cho kỳ trong tương lai.")
    result = text(data, "result", required=True, maxlen=12000)
    next_plan = text(data, "nextPlan", required=True, maxlen=12000)
    blocker = text(data, "blocker", maxlen=8000)
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        snapshot = report_summary(con, user["id"], kind, start)
        report = {"ownerId": user["id"], "kind": kind, "period": start, "end": end, "result": result,
                  "blocker": blocker, "nextPlan": next_plan, "snapshot": snapshot,
                  "createdAt": now(), "reviewStatus": "submitted", "reviewNote": ""}
        try:
            cursor = con.execute("INSERT INTO reports(owner_id,kind,period,payload) VALUES (?,?,?,?)", (user["id"], kind, start, "{}"))
        except sqlite3.IntegrityError:
            raise APIError(409, "Bạn đã nộp báo cáo kỳ này. Bản đã chốt được giữ nguyên để đối chiếu.")
        report["id"] = cursor.lastrowid
        con.execute("UPDATE reports SET payload=? WHERE id=?", (json.dumps(report, ensure_ascii=False), report["id"]))
        return report


def review_report(user, report_id, data):
    require_manager(user)
    if set(data) - {"reviewNote", "reviewStatus"} or data.get("reviewStatus") != "reviewed":
        raise APIError(400, "Chỉ được ghi nhận xét và xác nhận đã kiểm tra báo cáo.")
    note = text(data, "reviewNote", required=True, maxlen=8000)
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT payload FROM reports WHERE id=?", (report_id,)).fetchone()
        if not row:
            raise APIError(404, "Không tìm thấy báo cáo.")
        report = json.loads(row[0])
        if report["ownerId"] == user["id"]:
            raise APIError(403, "Không được tự duyệt báo cáo của mình.")
        report.update(reviewStatus="reviewed", reviewNote=note, reviewedBy=user["id"], reviewedAt=now())
        con.execute("UPDATE reports SET payload=? WHERE id=?", (json.dumps(report, ensure_ascii=False), report_id))
        return report


def bootstrap(user, csrf):
    with connect() as con:
        users = [public_user(row) for row in con.execute("SELECT * FROM users ORDER BY name")]
        if user["role"] not in MANAGERS:
            # Directory contains only operational information. Login identifiers of colleagues stay private.
            users = [{k: v for k, v in u.items() if k != "username" or u["id"] == user["id"]} for u in users]
        tasks = [task for task in all_tasks(con) if can_view(task, user)]
        if user["role"] in MANAGERS:
            reports = [json.loads(row[0]) for row in con.execute("SELECT payload FROM reports ORDER BY id DESC")]
        else:
            reports = [json.loads(row[0]) for row in con.execute("SELECT payload FROM reports WHERE owner_id=? ORDER BY id DESC", (user["id"],))]
        return {"user": user, "csrfToken": csrf, "users": users, "tasks": tasks, "reports": reports, "today": today()}


def export(user):
    require_manager(user)
    data = bootstrap(user, "")
    data.pop("csrfToken", None)
    data.update(exportedAt=now(), schemaVersion=1)
    return data
