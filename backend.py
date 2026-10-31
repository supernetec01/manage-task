"""Shared SQLite storage and authorization for the Content Marketing workspace."""
from __future__ import annotations

import base64
import binascii
import mimetypes
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
    with connect() as con:
        if "reviewer_id" not in {row[1] for row in con.execute("PRAGMA table_info(users)")}:
            con.execute("ALTER TABLE users ADD COLUMN reviewer_id INTEGER REFERENCES users(id)")
        con.execute("CREATE TABLE IF NOT EXISTS attachments (id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, media_type TEXT NOT NULL, size INTEGER NOT NULL, content BLOB NOT NULL, created_at TEXT NOT NULL, task_id INTEGER REFERENCES tasks(id))")
    try:
        (DATA_DIR / "supernet.db").chmod(0o600)
    except OSError:
        pass


def public_user(row):
    return {"id": row["id"], "name": row["name"], "username": row["username"],
            "role": row["role"], "active": bool(row["active"]), "capacity": row["capacity"], "defaultReviewerId": row["reviewer_id"]}


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
        reviewer = user_id(con, data["defaultReviewerId"], "Quản lý phụ trách", manager=True) if data.get("defaultReviewerId") else None
        try:
            cursor = con.execute("INSERT INTO users(username,name,role,capacity,password_hash,created_at,reviewer_id) VALUES (?,?,?,?,?,?,?)", (username, name, role, capacity, password, now(), reviewer))
        except sqlite3.IntegrityError:
            raise APIError(409, "Tên đăng nhập đã được sử dụng.")
        return public_user(con.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone())


def patch_user(user, target_id, data):
    require_manager(user)
    allowed = {"name", "role", "active", "capacity", "password", "defaultReviewerId"}
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
        reviewer = row["reviewer_id"]
        if "defaultReviewerId" in data:
            reviewer = user_id(con, data["defaultReviewerId"], "Quản lý phụ trách", manager=True) if data["defaultReviewerId"] else None
            if reviewer == target_id:
                raise APIError(400, "Không được chọn chính mình làm quản lý phụ trách.")
        con.execute("UPDATE users SET name=?,role=?,active=?,capacity=?,password_hash=?,reviewer_id=? WHERE id=?", (name, role, int(active), capacity, password_hash, reviewer, target_id))
        if "role" in data or "active" in data or data.get("password"):
            con.execute("DELETE FROM sessions WHERE user_id=?", (target_id,))
        return public_user(con.execute("SELECT * FROM users WHERE id=?", (target_id,)).fetchone())


def deadline_value(value, *, required=True):
    """Store all deadlines in Vietnam time; legacy date-only values mean end of day."""
    if value in (None, "") and not required:
        return ""
    if not isinstance(value, str) or len(value) > 40:
        raise APIError(400, "Vui lòng chọn ngày và giờ hoàn thành.")
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            value += "T23:59:59+07:00"
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if "T" not in value:
            raise ValueError()
        parsed = parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)
        return parsed.isoformat(timespec="seconds")
    except (ValueError, OverflowError):
        raise APIError(400, "Ngày giờ hoàn thành không hợp lệ.")


def is_overdue(task):
    return task["status"] not in {"draft", "done", "cancelled"} and bool(task["due"]) and task["due"] < now()


def normalize_task(task):
    """Add fields to old records without rewriting tasks or frozen report snapshots."""
    for key in ("due", "originalDue"):
        if task.get(key):
            task[key] = deadline_value(task[key])
    defaults = {"createdById": (task.get("history") or [{}])[-1].get("actorId", task["ownerId"]),
                "assignedById": None, "assignedAt": task.get("createdAt"), "receivedAt": None,
                "submittedAt": None, "approvedAt": task.get("acceptedAt"),
                "attachments": [], "links": [], "resultFiles": [], "resultLinks": [],
                "resultNote": "", "updates": [], "supportUserId": None, "clarification": "",
                "planProposal": None, "template": "video" if task.get("stages") else "none"}
    for key, value in defaults.items():
        task.setdefault(key, value)
    for stage in task.get("stages", []):
        if stage.get("due"):
            stage["due"] = deadline_value(stage["due"])
    return task


def assigned(task, user):
    return task["ownerId"] == user["id"] or any(stage["ownerId"] == user["id"] for stage in task["stages"])


def can_view(task, user):
    if task["status"] == "draft":
        return task["createdById"] == user["id"] or user["role"] == "admin"
    return user["role"] in MANAGERS or assigned(task, user)


def load_task(con, task_id, user):
    row = con.execute("SELECT payload FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise APIError(404, "Không tìm thấy nhiệm vụ.")
    task = normalize_task(json.loads(row[0]))
    if not can_view(task, user):
        raise APIError(403, "Bạn không được truy cập nhiệm vụ này.")
    return task


def default_reviewer(con, owner_id, creator):
    if creator["role"] in MANAGERS:
        return creator["id"]
    owner = con.execute("SELECT reviewer_id FROM users WHERE id=?", (owner_id,)).fetchone()
    if owner and owner[0]:
        row = con.execute("SELECT id FROM users WHERE id=? AND active=1 AND role IN ('admin','manager')", (owner[0],)).fetchone()
        if row and row[0] != owner_id:
            return row[0]
    row = con.execute("SELECT id FROM users WHERE active=1 AND role IN ('admin','manager') AND id<>? ORDER BY CASE role WHEN 'manager' THEN 0 ELSE 1 END,id LIMIT 1", (owner_id,)).fetchone()
    if not row:
        raise APIError(400, "Chưa có quản lý duyệt việc. Hãy liên hệ quản trị viên.")
    return row[0]


def record(task, user, action, changes=None):
    entry = {"at": now(), "actor": user["name"], "actorId": user["id"], "action": action}
    if changes:
        entry["changes"] = changes
    task["history"].insert(0, entry)


def describe_changes(con, old, task):
    details, messages = [], []
    labels = {"title": "Tên nhiệm vụ", "description": "Mô tả", "criteria": "Tiêu chí cũ",
              "channel": "Kênh", "pillar": "Pillar", "angle": "Angle", "series": "Series",
              "campaign": "Chiến dịch", "ownerId": "Người thực hiện", "reviewerId": "Người duyệt",
              "due": "Deadline", "priority": "Ưu tiên", "estimatedHours": "Giờ dự kiến",
              "nextStep": "Bước tiếp theo", "blocker": "Vướng mắc", "evidence": "Minh chứng",
              "scriptUrl": "Link kịch bản", "publicationStatus": "Trạng thái đăng",
              "publishUrl": "Link bài đăng", "publishAt": "Thời gian đăng",
              "attachments": "Tài liệu hỗ trợ", "links": "Liên kết hỗ trợ", "stages": "Các bước thực hiện"}
    status_labels = {"todo": "Chưa làm", "doing": "Đang làm", "done": "Hoàn thành"}
    for key, label in labels.items():
        if old.get(key) == task.get(key):
            continue
        details.append({"field": key, "before": old.get(key), "after": task.get(key)})
        if key == "stages":
            previous = {s["key"]: s for s in old["stages"]}
            for stage in task["stages"]:
                before = previous.get(stage["key"])
                if not before:
                    messages.append("Thêm bước: " + stage["label"])
                    continue
                for field in ("status", "note", "due", "ownerId"):
                    if before[field] != stage[field]:
                        details.append({"field": f"stages.{stage['key']}.{field}", "before": before[field], "after": stage[field]})
                        value = status_labels.get(stage[field], stage[field]) if field == "status" else stage[field]
                        messages.append(f"{stage['label']} — {field}: {str(value)[:180]}")
            if len(previous) > len(task["stages"]):
                messages.append("Điều chỉnh danh sách các bước")
        elif key in {"nextStep", "blocker"}:
            messages.append(f"{label}: {task[key][:180] or '(đã xóa)'}")
        elif key in {"due", "ownerId", "reviewerId"}:
            messages.append(f"{label}: {old.get(key)} → {task[key]}")
        else:
            messages.append("Cập nhật " + label.lower())
    return details, messages


def write_task(con, task):
    con.execute("UPDATE tasks SET payload=? WHERE id=?", (json.dumps(task, ensure_ascii=False), task["id"]))


def link_list(values):
    if not isinstance(values, list) or len(values) > 20:
        raise APIError(400, "Tối đa 20 liên kết, mỗi liên kết một dòng.")
    return list(dict.fromkeys(valid_url(text({"url": v}, "url", required=True, maxlen=3000), "Liên kết") for v in values))


def upload_file(user, data):
    name = text(data, "name", required=True, maxlen=240).replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()[:180]
    if not name:
        raise APIError(400, "Tên tệp không hợp lệ.")
    encoded = data.get("content")
    if not isinstance(encoded, str) or len(encoded) > 7_000_000:
        raise APIError(413, "Mỗi tệp tối đa 5 MB.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise APIError(400, "Dữ liệu tệp không hợp lệ.")
    if not content or len(content) > 5 * 1024 * 1024:
        raise APIError(413, "Tệp phải có nội dung và không quá 5 MB.")
    fid = secrets.token_hex(16)
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    with connect() as con:
        # Discard abandoned, unattached uploads after a day; attached files are preserved.
        con.execute("DELETE FROM attachments WHERE task_id IS NULL AND created_at < ?", ((datetime.now(TZ) - timedelta(days=1)).isoformat(timespec="seconds"),))
        if con.execute("SELECT COUNT(*) FROM attachments WHERE owner_id=? AND task_id IS NULL", (user["id"],)).fetchone()[0] >= 30:
            raise APIError(400, "Bạn có nhiều tệp chưa gắn vào nhiệm vụ. Hãy lưu nhiệm vụ trước khi tải thêm.")
        con.execute("INSERT INTO attachments VALUES (?,?,?,?,?,?,?,NULL)", (fid, user["id"], name, mime, len(content), content, now()))
    return {"id": fid, "name": name, "size": len(content), "mediaType": mime, "url": "/api/files/" + fid}


def file_metadata(row):
    return {"id": row["id"], "name": row["name"], "size": row["size"], "mediaType": row["media_type"], "url": "/api/files/" + row["id"]}


def attach_files(con, values, user, task_id):
    if not isinstance(values, list) or len(values) > 10:
        raise APIError(400, "Mỗi phần tài liệu tối đa 10 tệp.")
    result = []
    for value in values:
        fid = value.get("id") if isinstance(value, dict) else value
        if not isinstance(fid, str) or not re.fullmatch(r"[a-f0-9]{32}", fid):
            raise APIError(400, "Mã tệp không hợp lệ.")
        row = con.execute("SELECT id,owner_id,name,media_type,size,task_id FROM attachments WHERE id=?", (fid,)).fetchone()
        if not row or (row["task_id"] != task_id and (row["task_id"] is not None or row["owner_id"] != user["id"])):
            raise APIError(403, "Bạn không được sử dụng tệp này.")
        con.execute("UPDATE attachments SET task_id=? WHERE id=?", (task_id, fid))
        if not any(f["id"] == fid for f in result):
            result.append(file_metadata(row))
    return result


def download_file(user, fid):
    with connect() as con:
        row = con.execute("SELECT * FROM attachments WHERE id=?", (fid,)).fetchone()
        if not row:
            raise APIError(404, "Không tìm thấy tệp.")
        if row["task_id"] is None:
            if row["owner_id"] != user["id"]:
                raise APIError(403, "Bạn không được truy cập tệp này.")
        else:
            load_task(con, row["task_id"], user)
        return row["name"], row["content"]


def validate_stages(con, stages, owner, due):
    if not isinstance(stages, list) or len(stages) > 20:
        raise APIError(400, "Tối đa 20 bước thực hiện cho một nhiệm vụ.")
    results, seen = [], set()
    for stage in stages:
        if not isinstance(stage, dict) or not isinstance(stage.get("key"), str) or not re.fullmatch(r"[a-z0-9_-]{1,50}", stage["key"]) or stage["key"] in seen:
            raise APIError(400, "Mã các bước không hợp lệ hoặc bị trùng.")
        key = stage["key"]
        seen.add(key)
        label = text(stage, "label", required=True, maxlen=120, default=STAGE_LABELS.get(key, key))
        person = user_id(con, stage.get("ownerId", owner), "Người thực hiện bước")
        stage_due = deadline_value(stage.get("due", due), required=False)
        if due and stage_due and stage_due > due:
            raise APIError(400, "Hạn từng bước không được sau deadline nhiệm vụ.")
        status = stage.get("status", "todo")
        if not isinstance(status, str) or status not in {"todo", "doing", "done"}:
            raise APIError(400, "Trạng thái bước không hợp lệ.")
        results.append({"key": key, "label": label, "ownerId": person, "due": stage_due,
                        "status": status, "note": text(stage, "note", maxlen=4000)})
    return results


def template_stages(owner, due):
    return [{"key": key, "label": STAGE_LABELS[key], "ownerId": owner, "due": due, "status": "todo", "note": ""} for key in STAGE_KEYS]


def create_task(user, data):
    draft = data.get("draft", False)
    if not isinstance(draft, bool):
        raise APIError(400, "Trạng thái bản nháp không hợp lệ.")
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        owner = user_id(con, data.get("ownerId", user["id"]), "Người thực hiện")
        if user["role"] not in MANAGERS and owner != user["id"]:
            raise APIError(403, "Bạn chỉ được tự tạo nhiệm vụ cho bản thân.")
        reviewer = default_reviewer(con, owner, user)
        if "reviewerId" in data and user["role"] in MANAGERS:
            reviewer = user_id(con, data["reviewerId"], "Người duyệt", manager=True)
        elif "reviewerId" in data and str(data["reviewerId"]) != str(reviewer):
            raise APIError(403, "Người duyệt được lấy theo quản lý phụ trách của bạn.")
        due = deadline_value(data.get("due"), required=not draft)
        priority = data.get("priority", "normal")
        if not isinstance(priority, str) or priority not in {"low", "normal", "high", "urgent"}:
            raise APIError(400, "Mức ưu tiên không hợp lệ.")
        template = data.get("template", "none")
        if template not in ("none", "video"):
            raise APIError(400, "Mẫu nhiệm vụ không hợp lệ.")
        task = {"title": text(data, "title", required=True, maxlen=240),
                "description": text(data, "description", maxlen=12000), "criteria": text(data, "criteria", maxlen=8000),
                "ownerId": owner, "reviewerId": reviewer, "due": due, "originalDue": due,
                "priority": priority, "estimatedHours": None if data.get("estimatedHours") in (None, "") else number(data["estimatedHours"], "Giờ dự kiến", .5, 1000),
                "status": "draft" if draft else "pending", "createdAt": now(), "createdById": user["id"],
                "assignedById": None if draft else user["id"], "assignedAt": None if draft else now(),
                "receivedAt": None, "submittedAt": None, "approvedAt": None, "acceptedAt": None,
                "publicationStatus": "unscheduled", "publishUrl": "", "publishAt": "", "history": [], "version": 1,
                "template": template, "links": link_list(data.get("links", [])), "attachments": [],
                "resultFiles": [], "resultLinks": [], "resultNote": "", "updates": [], "supportUserId": None,
                "clarification": "", "planProposal": None}
        task["stages"] = validate_stages(con, data.get("stages", template_stages(owner, due) if template == "video" else []), owner, due)
        for stage in task["stages"]:
            if user["role"] not in MANAGERS and stage["ownerId"] != user["id"]:
                raise APIError(403, "Bạn chỉ được tự giao các bước cho bản thân.")
            stage["status"] = "todo"
        for key in ("channel", "pillar", "angle", "series", "campaign", "nextStep", "blocker"):
            task[key] = text(data, key, maxlen=4000 if key in {"nextStep", "blocker"} else 240)
        for key in ("evidence", "scriptUrl"):
            task[key] = valid_url(text(data, key, maxlen=3000), key)
        cursor = con.execute("INSERT INTO tasks(payload) VALUES ('{}')")
        task["id"] = cursor.lastrowid
        task["attachments"] = attach_files(con, data.get("attachments", []), user, task["id"])
        record(task, user, "Lưu nháp nhiệm vụ" if draft else "Giao nhiệm vụ")
        write_task(con, task)
        return task


def version_check(data, task):
    if type(data.get("version")) is not int:
        raise APIError(400, "Thiếu phiên bản nhiệm vụ. Hãy tải lại dữ liệu.")
    if data["version"] != task["version"]:
        raise APIError(409, "Nhiệm vụ vừa được người khác cập nhật. Hãy tải lại trước khi lưu.")


def patch_task(user, task_id, data):
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        task = load_task(con, task_id, user)
        version_check(data, task)
        old = copy.deepcopy(task)
        manager = user["role"] in MANAGERS
        draft_owner = task["status"] == "draft" and task["createdById"] == user["id"]
        general = {"title", "description", "criteria", "channel", "pillar", "angle", "series", "campaign", "ownerId", "reviewerId", "due", "priority", "estimatedHours", "attachments", "links"}
        shared = {"nextStep", "blocker", "evidence", "scriptUrl", "stages", "version"}
        publication = {"publicationStatus", "publishUrl", "publishAt"}
        if set(data) - (general | shared | publication):
            raise APIError(400, "Không được đổi trạng thái hoặc trường hệ thống trực tiếp.")
        if not manager and not draft_owner and set(data) & general:
            raise APIError(403, "Thay đổi yêu cầu hoặc deadline cần quản lý xác nhận.")
        if task["status"] == "cancelled":
            raise APIError(400, "Nhiệm vụ đã hủy không thể cập nhật.")
        if task["status"] == "done" and set(data) - ({"version"} | publication):
            raise APIError(400, "Nhiệm vụ đã nghiệm thu chỉ được cập nhật thông tin đăng bài.")
        for key in ("title", "description", "criteria", "channel", "pillar", "angle", "series", "campaign", "nextStep", "blocker"):
            if key in data:
                task[key] = text(data, key, required=key == "title", maxlen=12000 if key == "description" else 8000 if key == "criteria" else 4000 if key in {"nextStep", "blocker"} else 240)
        if "ownerId" in data:
            task["ownerId"] = user_id(con, data["ownerId"], "Người thực hiện")
            if not manager and task["ownerId"] != user["id"]:
                raise APIError(403, "Bạn chỉ được tự tạo nhiệm vụ cho bản thân.")
        if "reviewerId" in data:
            task["reviewerId"] = user_id(con, data["reviewerId"], "Người duyệt", manager=True)
            if not manager and task["reviewerId"] != default_reviewer(con, task["ownerId"], user):
                raise APIError(403, "Không được thay đổi người duyệt mặc định.")
        if "due" in data:
            task["due"] = deadline_value(data["due"], required=task["status"] != "draft")
        if "priority" in data:
            if not isinstance(data["priority"], str) or data["priority"] not in {"low", "normal", "high", "urgent"}:
                raise APIError(400, "Mức ưu tiên không hợp lệ.")
            task["priority"] = data["priority"]
        if "estimatedHours" in data:
            task["estimatedHours"] = None if data["estimatedHours"] in (None, "") else number(data["estimatedHours"], "Giờ dự kiến", .5, 1000)
        for key in ("evidence", "scriptUrl"):
            if key in data:
                task[key] = valid_url(text(data, key, maxlen=3000), key)
        if "links" in data:
            task["links"] = link_list(data["links"])
        if "attachments" in data:
            task["attachments"] = attach_files(con, data["attachments"], user, task_id)
        if "stages" in data:
            stages = validate_stages(con, data["stages"], task["ownerId"], task["due"])
            if not manager and not draft_owner:
                if [s["key"] for s in stages] != [s["key"] for s in old["stages"]]:
                    raise APIError(403, "Hãy đề xuất các bước mới để quản lý xác nhận.")
                for before, stage in zip(old["stages"], stages):
                    if stage["ownerId"] != before["ownerId"] or stage["due"] != before["due"] or stage["label"] != before["label"]:
                        raise APIError(403, "Nhân viên không được đổi phân công hoặc thời hạn.")
                    if before["ownerId"] != user["id"] and stage != before:
                        raise APIError(403, "Bạn chỉ được cập nhật bước được giao cho mình.")
            if draft_owner and not manager and any(s["ownerId"] != user["id"] for s in stages):
                raise APIError(403, "Bạn chỉ được tự giao các bước cho bản thân.")
            task["stages"] = stages
        elif any(s["due"] and task["due"] and s["due"] > task["due"] for s in task["stages"]):
            raise APIError(400, "Hãy điều chỉnh hạn từng bước trước khi rút ngắn deadline.")
        if set(data) & publication:
            if not manager and user["id"] != task["ownerId"]:
                raise APIError(403, "Chỉ quản lý hoặc người chịu trách nhiệm được cập nhật đăng bài.")
            if task["status"] != "done":
                raise APIError(400, "Cần nghiệm thu trước khi lên lịch đăng.")
            status = data.get("publicationStatus", task["publicationStatus"])
            if not isinstance(status, str) or status not in {"unscheduled", "scheduled", "published"}:
                raise APIError(400, "Trạng thái xuất bản không hợp lệ.")
            task["publicationStatus"] = status
            if "publishUrl" in data:
                task["publishUrl"] = valid_url(text(data, "publishUrl", maxlen=3000), "Link bài đăng")
            if "publishAt" in data:
                task["publishAt"] = deadline_value(data["publishAt"], required=status != "unscheduled")
            if status in {"scheduled", "published"} and not task["publishAt"]:
                raise APIError(400, "Vui lòng chọn ngày giờ đăng.")
            if status == "published" and not task["publishUrl"]:
                raise APIError(400, "Bài đã đăng cần có đường dẫn.")
        if task != old:
            details, messages = describe_changes(con, old, task)
            task["version"] += 1
            record(task, user, "; ".join(messages) or "Cập nhật nhiệm vụ", details)
            write_task(con, task)
        return task


def update_task(user, task_id, data):
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        task = load_task(con, task_id, user)
        version_check(data, task)
        if task["status"] in {"draft", "done", "cancelled"}:
            raise APIError(400, "Nhiệm vụ không ở trạng thái có thể cập nhật tiến độ.")
        kind = data.get("kind", "progress")
        if kind not in ("progress", "blocker", "clarify"):
            raise APIError(400, "Loại cập nhật không hợp lệ.")
        completed = text(data, "completed", maxlen=8000)
        next_step = text(data, "nextStep", maxlen=4000)
        note = text(data, "note", maxlen=4000)
        if kind == "progress" and not (completed or next_step):
            raise APIError(400, "Hãy ghi việc đã làm hoặc bước tiếp theo.")
        if kind != "progress" and not note:
            raise APIError(400, "Hãy ghi rõ câu hỏi hoặc vấn đề cần hỗ trợ.")
        files = attach_files(con, data.get("files", []), user, task_id)
        links = link_list(data.get("links", []))
        support = user_id(con, data["supportUserId"], "Người hỗ trợ") if data.get("supportUserId") else None
        if kind == "progress":
            if "nextStep" in data:
                task["nextStep"] = next_step
            if data.get("resolveBlocker") is True:
                task["blocker"] = ""
                task["clarification"] = ""
                task["supportUserId"] = None
        else:
            task["blocker"] = note
            task["supportUserId"] = support or task["reviewerId"]
            if kind == "clarify":
                task["clarification"] = note
        entry = {"at": now(), "actorId": user["id"], "actor": user["name"], "kind": kind,
                 "completed": completed, "nextStep": next_step, "note": note, "files": files, "links": links}
        task["updates"].insert(0, entry)
        task["version"] += 1
        record(task, user, {"progress": "Cập nhật tiến độ", "blocker": "Báo vướng mắc", "clarify": "Cần làm rõ"}[kind] + ": " + (completed or note or next_step)[:250])
        write_task(con, task)
        return task


def task_action(user, task_id, data):
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        task = load_task(con, task_id, user)
        version_check(data, task)
        previous = copy.deepcopy(task)
        action = data.get("action")
        if not isinstance(action, str):
            raise APIError(400, "Thao tác nhiệm vụ không hợp lệ.")
        note = text(data, "note", maxlen=8000)
        manager = user["role"] in MANAGERS
        if action == "assign":
            if task["status"] != "draft" or (not manager and task["createdById"] != user["id"]):
                raise APIError(403, "Bạn không được giao bản nháp này.")
            task["due"] = deadline_value(task["due"])
            user_id(con, task["ownerId"], "Người thực hiện")
            user_id(con, task["reviewerId"], "Người duyệt", manager=True)
            if not manager and task["ownerId"] != user["id"]:
                raise APIError(403, "Bạn chỉ được giao nhiệm vụ cho bản thân.")
            if not task["originalDue"]:
                task["originalDue"] = task["due"]
            task.update(status="pending", assignedAt=now(), assignedById=user["id"])
            message = "Giao nhiệm vụ từ bản nháp"
        elif action in {"approve", "request_changes"}:
            require_manager(user)
            if user["role"] != "admin" and task["reviewerId"] != user["id"]:
                raise APIError(403, "Bạn không phải người duyệt được phân công.")
            if task["status"] != "review":
                raise APIError(400, "Nhiệm vụ chưa ở trạng thái chờ duyệt.")
            if action == "approve":
                if not (task["evidence"] or task["resultNote"] or task["resultFiles"] or task["resultLinks"]) or not all(s["status"] == "done" for s in task["stages"]):
                    raise APIError(400, "Cần đủ các bước và có kết quả bàn giao trước khi duyệt.")
                task.update(status="done", acceptedAt=now(), approvedAt=now())
                message = "Nghiệm thu kết quả"
            else:
                if not note:
                    raise APIError(400, "Vui lòng ghi rõ yêu cầu chỉnh sửa.")
                task["status"] = "revision"
                message = "Yêu cầu chỉnh sửa"
        elif action == "cancel":
            require_manager(user)
            if task["status"] in {"done", "cancelled"} or not note:
                raise APIError(400, "Cần lý do hủy và nhiệm vụ chưa được nghiệm thu/hủy.")
            task["status"] = "cancelled"
            message = "Hủy nhiệm vụ"
        elif action in {"start", "submit"}:
            if action == "start":
                if task["status"] not in {"pending", "revision"}:
                    raise APIError(400, "Nhiệm vụ không ở trạng thái có thể nhận việc.")
                task["status"] = "doing"
                task["receivedAt"] = task["receivedAt"] or now()
                task["clarification"] = ""
                message = "Nhận việc"
            else:
                if task["status"] not in {"doing", "revision"}:
                    raise APIError(400, "Hãy nhận việc trước khi nộp kết quả.")
                if not all(s["status"] == "done" for s in task["stages"]):
                    raise APIError(400, "Hãy hoàn thành các bước đã áp dụng trước khi nộp kết quả.")
                if task["blocker"]:
                    raise APIError(400, "Hãy đánh dấu đã giải quyết vướng mắc trước khi nộp kết quả.")
                if "resultNote" in data:
                    task["resultNote"] = text(data, "resultNote", maxlen=12000)
                if "resultLinks" in data:
                    task["resultLinks"] = link_list(data["resultLinks"])
                if "resultFiles" in data:
                    task["resultFiles"] = attach_files(con, data["resultFiles"], user, task_id)
                if not (task["resultNote"] or task["resultLinks"] or task["resultFiles"] or task["evidence"]):
                    raise APIError(400, "Hãy nhập kết quả, thêm tệp hoặc đường dẫn bàn giao.")
                task.update(status="review", submittedAt=now())
                message = "Nộp kết quả chờ duyệt"
        elif action == "propose_plan":
            if task["status"] not in {"pending", "doing", "revision"}:
                raise APIError(400, "Chỉ đề xuất khi nhiệm vụ đang mở.")
            if not note:
                raise APIError(400, "Hãy nêu lý do hoặc nội dung đề xuất.")
            due = deadline_value(data.get("due", task["due"]))
            stages = validate_stages(con, data.get("stages", task["stages"]), task["ownerId"], due)
            if not manager and any(s["ownerId"] != user["id"] for s in stages if s["key"] not in {old["key"] for old in task["stages"]}):
                raise APIError(403, "Bước mới chỉ được đề xuất cho bản thân.")
            task["planProposal"] = {"by": user["id"], "at": now(), "note": note, "due": due, "stages": stages,
                                    "originalStages": copy.deepcopy(task["stages"]), "originalDue": task["due"],
                                    "estimatedHours": task["estimatedHours"] if data.get("estimatedHours") in (None, "") else number(data["estimatedHours"], "Giờ dự kiến", .5, 1000)}
            message = "Đề xuất kế hoạch / deadline: " + note
        elif action in {"accept_plan", "reject_plan"}:
            require_manager(user)
            if task["status"] not in {"pending", "doing", "revision"} or not task["planProposal"]:
                raise APIError(400, "Không có đề xuất đang chờ xác nhận.")
            proposal = task["planProposal"]
            if action == "accept_plan":
                if proposal.get("originalStages") != task["stages"] or proposal.get("originalDue") != task["due"]:
                    raise APIError(409, "Tiến độ hoặc deadline đã đổi sau đề xuất. Hãy yêu cầu nhân viên đề xuất lại.")
                task["stages"] = validate_stages(con, proposal["stages"], task["ownerId"], proposal["due"])
                task["due"] = deadline_value(proposal["due"])
                task["estimatedHours"] = proposal.get("estimatedHours", task["estimatedHours"])
                message = "Chấp thuận kế hoạch / deadline: " + proposal["note"]
            else:
                if not note:
                    raise APIError(400, "Hãy ghi lý do chưa chấp thuận.")
                message = "Chưa chấp thuận đề xuất"
            task["planProposal"] = None
        else:
            raise APIError(400, "Thao tác nhiệm vụ không hợp lệ.")
        task["version"] += 1
        details = []
        if action == "accept_plan":
            details, _ = describe_changes(con, previous, task)
        elif action == "propose_plan":
            details = [{"field": "planProposal", "before": previous["planProposal"], "after": task["planProposal"]}]
        elif action == "approve":
            details = [{"field": "reviewedVersion", "before": None, "after": previous["version"]},
                       {"field": "reviewedResult", "before": None, "after": {"note": task["resultNote"], "links": task["resultLinks"], "files": task["resultFiles"], "evidence": task["evidence"]}}]
        record(task, user, message + (": " + note if note and action != "propose_plan" else ""), details)
        write_task(con, task)
        return task


def all_tasks(con):
    return [normalize_task(json.loads(row[0])) for row in con.execute("SELECT payload FROM tasks ORDER BY id DESC")]


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
    tasks = [task for task in all_tasks(con) if assigned(task, own) and start <= task["due"][:10] <= end and task["status"] not in {"draft", "cancelled"}]
    activities = [task for task in all_tasks(con) if assigned(task, own) and task["status"] not in {"draft", "cancelled"} and any(h.get("actorId") == owner and start <= h["at"][:10] <= end for h in task["history"])]
    # Keep due-in-period and actual activity separate, never infer work from mere assignment.
    return {"kind": kind, "period": start, "end": end, "ownerId": owner,
            "total": len(tasks), "done": sum(t["status"] == "done" for t in tasks),
            "overdue": sum(is_overdue(t) for t in tasks),
            "blocked": sum(bool(t["blocker"]) and t["status"] not in {"done", "cancelled"} for t in tasks),
            "tasks": tasks, "activityTasks": activities, "activityCount": len(activities)}


def get_summary(user, query):
    owner = query.get("ownerId", [str(user["id"])])[0]
    try:
        owner = int(owner)
    except (ValueError, TypeError):
        raise APIError(400, "Người báo cáo không hợp lệ.")
    if not 1 <= owner <= 2**63 - 1:
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
    data.update(exportedAt=now(), schemaVersion=2)
    return data
