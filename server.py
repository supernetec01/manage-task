"""Run the shared Super Net Content Marketing workspace (Python 3.10+)."""
from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import os
import re
import socket
import sqlite3
import sys
from http import cookies
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import backend

ROOT = Path(__file__).resolve().parent
PUBLIC_FILES = {"/", "/index.html", "/app.js", "/style.css"}
BODY_LIMIT = 512 * 1024
COOKIE_NAME = "supernet_session"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.response_cookie = None
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        # Avoid logging query strings that may accidentally contain personal data.
        if fmt.startswith('"%s"'):
            sys.stderr.write(f"{self.address_string()} - {self.command} {urlsplit(self.path).path}\n")
        else:
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if self.response_cookie:
            self.send_header("Set-Cookie", self.response_cookie)
            self.response_cookie = None
        super().end_headers()

    def send_head(self):
        path = unquote(urlsplit(self.path).path)
        if path not in PUBLIC_FILES:
            self.send_error(404)
            return None
        return super().send_head()

    def send_json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def token(self):
        try:
            jar = cookies.SimpleCookie()
            jar.load(self.headers.get("Cookie", ""))
            item = jar.get(COOKIE_NAME)
            return item.value if item else ""
        except cookies.CookieError:
            return ""

    def cookie(self, token, clear=False):
        secure = "; Secure" if os.environ.get("SUPERNET_SECURE_COOKIE") == "1" else ""
        self.response_cookie = f"{COOKIE_NAME}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={0 if clear else backend.SESSION_SECONDS}{secure}"

    def validate_origin(self):
        # Same-site checks cover login/setup too; authenticated requests additionally need CSRF.
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise backend.APIError(403, "Không cho phép yêu cầu từ website khác.")
        origin = self.headers.get("Origin")
        if origin:
            try:
                parsed = urlsplit(origin)
                host = self.headers.get("Host", "")
                if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != host.lower() or parsed.path or parsed.query or parsed.fragment:
                    raise ValueError()
            except ValueError:
                raise backend.APIError(403, "Nguồn yêu cầu không hợp lệ.")

    def parse_body(self):
        if self.headers.get("Transfer-Encoding"):
            raise backend.APIError(400, "Không hỗ trợ kiểu truyền dữ liệu này.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise backend.APIError(400, "Độ dài yêu cầu không hợp lệ.")
        if not 0 < length <= BODY_LIMIT:
            raise backend.APIError(413 if length > BODY_LIMIT else 400, "Dữ liệu yêu cầu trống hoặc quá lớn.")
        if self.headers.get_content_type() != "application/json":
            raise backend.APIError(415, "Vui lòng gửi dữ liệu JSON.")
        try:
            data = json.loads(self.rfile.read(length), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (ValueError, UnicodeError):
            raise backend.APIError(400, "Nội dung JSON không hợp lệ.")
        if not isinstance(data, dict):
            raise backend.APIError(400, "Dữ liệu yêu cầu phải là đối tượng JSON.")
        return data

    def api(self, method):
        try:
            parsed = urlsplit(self.path)
            path = parsed.path.rstrip("/")
            if method == "GET" and path == "/api/status":
                self.send_json({"setupRequired": backend.setup_required()})
                return
            if method != "GET":
                self.validate_origin()
                data = self.parse_body()
            else:
                data = None
            if method == "POST" and path == "/api/setup":
                if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                    raise backend.APIError(403, "Hãy mở localhost trên chính máy chủ để tạo tài khoản quản trị đầu tiên.")
                # A hostile DNS rebinding page must not use the loopback-only setup route.
                hostname = urlsplit("http://" + self.headers.get("Host", "")).hostname
                if hostname not in {"localhost", "127.0.0.1", "::1"}:
                    raise backend.APIError(403, "Tạo quản trị viên tại localhost hoặc 127.0.0.1 trên máy chủ.")
                result, token = backend.setup(data)
                self.cookie(token)
                self.send_json(result, 201)
                return
            if method == "POST" and path == "/api/login":
                result, token = backend.login(data, self.client_address[0])
                self.cookie(token)
                self.send_json(result)
                return
            token = self.token()
            user, csrf = backend.authenticate(token)
            if method != "GET" and not hmac.compare_digest(self.headers.get("X-CSRF-Token", "").encode("utf-8"), csrf.encode("utf-8")):
                raise backend.APIError(403, "Phiên xác thực không hợp lệ. Hãy tải lại trang.")
            if method == "GET" and path == "/api/session":
                result = {"user": user, "csrfToken": csrf}
            elif method == "GET" and path == "/api/bootstrap":
                result = backend.bootstrap(user, csrf)
            elif method == "POST" and path == "/api/logout":
                backend.logout(token)
                self.cookie("", clear=True)
                result = {"ok": True}
            elif method == "POST" and path == "/api/password":
                result = backend.change_password(user, data)
                self.cookie("", clear=True)
            elif method == "POST" and path == "/api/users":
                self.send_json(backend.create_user(user, data), 201)
                return
            elif method == "PATCH" and re.fullmatch(r"/api/users/\d{1,18}", path):
                result = backend.patch_user(user, int(path.rsplit("/", 1)[1]), data)
            elif method == "POST" and path == "/api/tasks":
                self.send_json(backend.create_task(user, data), 201)
                return
            elif method == "PATCH" and re.fullmatch(r"/api/tasks/\d{1,18}", path):
                result = backend.patch_task(user, int(path.rsplit("/", 1)[1]), data)
            elif method == "POST" and re.fullmatch(r"/api/tasks/\d{1,18}/action", path):
                result = backend.task_action(user, int(path.split("/")[-2]), data)
            elif method == "GET" and path == "/api/report-summary":
                result = backend.get_summary(user, parse_qs(parsed.query))
            elif method == "POST" and path == "/api/reports":
                self.send_json(backend.create_report(user, data), 201)
                return
            elif method == "PATCH" and re.fullmatch(r"/api/reports/\d{1,18}", path):
                result = backend.review_report(user, int(path.rsplit("/", 1)[1]), data)
            elif method == "GET" and path == "/api/export":
                result = backend.export(user)
            else:
                raise backend.APIError(404, "Không tìm thấy chức năng này.")
            self.send_json(result)
        except backend.APIError as error:
            self.send_json({"error": error.message}, error.status)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except sqlite3.Error:
            self.send_json({"error": "Không thể truy cập cơ sở dữ liệu. Vui lòng thử lại hoặc liên hệ quản trị viên."}, 500)
        except Exception:
            # Request data and credentials must never be included in logs/errors.
            self.send_json({"error": "Có lỗi xử lý trên máy chủ. Vui lòng liên hệ quản trị viên."}, 500)

    def do_GET(self):
        if urlsplit(self.path).path.startswith("/api/"):
            self.api("GET")
        else:
            super().do_GET()

    def do_HEAD(self):
        if urlsplit(self.path).path.startswith("/api/"):
            self.send_error(405)
        else:
            super().do_HEAD()

    def do_POST(self):
        self.api("POST")

    def do_PATCH(self):
        self.api("PATCH")

    def do_OPTIONS(self):
        self.send_error(405)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def get_request(self):
        client, address = super().get_request()
        client.settimeout(20)
        return client, address


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=5001, type=int)
    args = parser.parse_args()
    try:
        backend.initialize()
    except (OSError, sqlite3.Error):
        print("Không thể khởi tạo cơ sở dữ liệu. Kiểm tra quyền ghi thư mục data hoặc SUPERNET_DATA_DIR và dung lượng ổ đĩa.", file=sys.stderr)
        return 1
    try:
        server = Server((args.host, args.port), Handler)
    except OSError as error:
        print(f"Không thể mở cổng {args.port}: {error}. Có thể cổng đang được chương trình khác sử dụng.", file=sys.stderr)
        return 1
    print(f"Super Net đang chạy tại cổng {args.port}. Mở http://localhost:{args.port} trên máy chủ.", flush=True)
    if backend.setup_required():
        print("Lần đầu: tạo tài khoản quản trị trong trình duyệt trên chính máy chủ; chưa có tài khoản mặc định.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
