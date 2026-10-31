"""Integration checks against an isolated server and temporary SQLite database."""
import copy
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

def local_today():
    return datetime.now(timezone(timedelta(hours=7))).date()

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "test-password-only-42"


class Client:
    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = None

    def request(self, method, path, payload=None, csrf=True, origin=None):
        headers = {}
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        if self.csrf and csrf:
            headers['X-CSRF-Token'] = self.csrf
        if origin:
            headers['Origin'] = origin
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)
        try:
            res = self.opener.open(req, timeout=10)
        except urllib.error.HTTPError as exc:
            res = exc
        raw = res.read()
        content_type = res.headers.get('Content-Type', '')
        data = json.loads(raw) if 'application/json' in content_type and raw else raw.decode(errors='replace')
        return res.status, data

    def login(self, username, password=PASSWORD):
        status, data = self.request('POST', '/api/login', {'username': username, 'password': password})
        if status != 200:
            raise AssertionError(('login', status, data))
        status, session = self.request('GET', '/api/session')
        if status != 200:
            raise AssertionError(('session', status, session))
        self.csrf = session['csrfToken']
        return session


class WorkspaceAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='supernet-tests-')
        cls.log = open(Path(cls.temp.name) / 'server.log', 'w+')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        cls.base = f'http://127.0.0.1:{cls.port}'
        cls.start_server()
        cls.admin = Client(cls.base)
        code, status = cls.admin.request('GET', '/api/status')
        assert code == 200 and status['setupRequired'], status
        code, result = cls.admin.request('POST', '/api/setup', {
            'name': 'Test Administrator', 'username': 'test-admin', 'password': PASSWORD,
        })
        assert code in (200, 201), (code, result)
        cls.admin.login('test-admin')
        cls.serial = 0

    @classmethod
    def start_server(cls):
        env = os.environ.copy()
        env['SUPERNET_DATA_DIR'] = str(Path(cls.temp.name) / 'data')
        cls.proc = subprocess.Popen([
            sys.executable, str(ROOT / 'server.py'), '--host', '127.0.0.1', '--port', str(cls.port),
        ], cwd=ROOT, env=env, stdout=cls.log, stderr=subprocess.STDOUT)
        until = time.monotonic() + 15
        while time.monotonic() < until:
            try:
                with urllib.request.urlopen(cls.base + '/api/status', timeout=1) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError):
                time.sleep(.05)
            if cls.proc.poll() is not None:
                break
        cls.log.flush()
        cls.log.seek(0)
        raise RuntimeError('Server failed to start: ' + cls.log.read())

    @classmethod
    def stop_server(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
            cls.proc.wait(timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.stop_server()
        cls.log.close()
        cls.temp.cleanup()

    def user(self, role='content'):
        type(self).serial += 1
        username = f'test-user-{self.serial}'
        code, data = self.admin.request('POST', '/api/users', {
            'name': username, 'username': username, 'password': PASSWORD,
            'role': role, 'capacity': 24 if role == 'intern' else 40,
        })
        self.assertIn(code, (200, 201), data)
        user = data.get('user', data)
        client = Client(self.base)
        session = client.login(username)
        self.assertEqual(session['user']['id'], user['id'])
        return user, client

    def task(self, owner, editor=None):
        data = {
            'title': 'Test content delivery', 'description': 'Produce a product video',
            'criteria': 'Correct product information and approved script',
            'channel': 'SafeStraps', 'pillar': 'PRODUCT', 'angle': 'Tutorial',
            'ownerId': owner['id'], 'reviewerId': self.admin.request('GET', '/api/session')[1]['user']['id'],
            'due': local_today().isoformat(), 'priority': 'normal', 'estimatedHours': 4,
            'nextStep': 'Write script',
            'stages': [{'key': key, 'label': label, 'ownerId': (editor or owner)['id'],
                        'due': local_today().isoformat(), 'status': 'todo', 'note': ''}
                       for key, label in [('script', 'Kịch bản'), ('shoot', 'Quay'), ('edit', 'Dựng')]],
        }
        code, created = self.admin.request('POST', '/api/tasks', data)
        self.assertIn(code, (200, 201), created)
        return created.get('task', created)

    def get_task(self, client, task_id):
        code, data = client.request('GET', '/api/bootstrap')
        self.assertEqual(code, 200, data)
        return next((t for t in data['tasks'] if t['id'] == task_id), None)

    def test_auth_and_public_file_boundary(self):
        anon = Client(self.base)
        self.assertEqual(anon.request('GET', '/api/bootstrap')[0], 401)
        self.assertEqual(anon.request('GET', '/.git/config')[0], 404)
        self.assertEqual(anon.request('GET', '/data/supernet.db')[0], 404)
        self.assertEqual(anon.request('GET', '/backend.py')[0], 404)
        code, body = anon.request('GET', '/')
        self.assertEqual(code, 200)
        self.assertIn('html', body.lower())
        self.assertEqual(anon.request('POST', '/api/login', {'username': 'test-admin', 'password': 'wrong'})[0], 401)
        code, _ = anon.request('POST', '/api/setup', {'name': 'Other', 'username': 'other', 'password': PASSWORD})
        self.assertIn(code, (403, 409))

    def test_csrf_and_cross_origin_rejected(self):
        code, _ = self.admin.request('POST', '/api/users', {'name': 'No CSRF'}, csrf=False)
        self.assertEqual(code, 403)
        anon = Client(self.base)
        code, _ = anon.request('POST', '/api/login', {'username': 'test-admin', 'password': PASSWORD}, origin='https://attacker.invalid')
        self.assertEqual(code, 403)

    def test_employee_task_visibility_and_permissions(self):
        owner, own = self.user()
        outsider, other = self.user('intern')
        task = self.task(owner)
        self.assertIsNotNone(self.get_task(own, task['id']))
        self.assertIsNone(self.get_task(other, task['id']))
        code, _ = other.request('PATCH', f"/api/tasks/{task['id']}", {'version': task['version'], 'nextStep': 'unauthorized'})
        self.assertIn(code, (403, 404))
        code, _ = own.request('POST', '/api/tasks', {'title': 'Self assign'})
        self.assertEqual(code, 403)
        code, _ = own.request('PATCH', f"/api/tasks/{task['id']}", {'version': task['version'], 'ownerId': outsider['id']})
        self.assertEqual(code, 403)

    def test_stage_assignee_cannot_change_someone_elses_stage(self):
        owner, own = self.user()
        editor, edit = self.user()
        task = self.task(owner, editor)
        self.assertIsNotNone(self.get_task(edit, task['id']))
        stages = copy.deepcopy(task['stages'])
        stages[0]['status'] = 'done'
        code, _ = own.request('PATCH', f"/api/tasks/{task['id']}", {'version': task['version'], 'stages': stages})
        self.assertEqual(code, 403)

    def test_workflow_requires_evidence_and_manager_approval(self):
        owner, own = self.user()
        task = self.task(owner)
        url = f"/api/tasks/{task['id']}"
        code, _ = own.request('POST', url + '/action', {'action': 'start', 'version': task['version']})
        self.assertEqual(code, 200)
        task = self.get_task(own, task['id'])
        code, _ = own.request('POST', url + '/action', {'action': 'submit', 'version': task['version']})
        self.assertIn(code, (400, 409, 422))
        stages = copy.deepcopy(task['stages'])
        for stage in stages:
            stage['status'] = 'done'
        code, data = own.request('PATCH', url, {'version': task['version'], 'stages': stages, 'evidence': 'https://example.com/video'})
        self.assertEqual(code, 200, data)
        task = self.get_task(own, task['id'])
        code, data = own.request('POST', url + '/action', {'action': 'submit', 'version': task['version']})
        self.assertEqual(code, 200, data)
        task = self.get_task(own, task['id'])
        self.assertEqual(task['status'], 'review')
        self.assertEqual(own.request('POST', url + '/action', {'action': 'approve', 'version': task['version']})[0], 403)
        code, data = self.admin.request('POST', url + '/action', {'action': 'approve', 'version': task['version']})
        self.assertEqual(code, 200, data)
        current = self.get_task(own, task['id'])
        self.assertEqual(current['status'], 'done')
        self.assertEqual(current['publicationStatus'], 'unscheduled')
        self.assertEqual(own.request('PATCH', url, {
            'version': current['version'], 'publicationStatus': 'published',
        })[0], 400)
        code, data = own.request('PATCH', url, {
            'version': current['version'], 'publicationStatus': 'published',
            'publishUrl': 'https://example.com/published-video',
            'publishAt': local_today().isoformat() + 'T15:00:00+07:00',
        })
        self.assertEqual(code, 200, data)
        self.assertEqual(self.get_task(own, task['id'])['publicationStatus'], 'published')

    def test_optimistic_concurrency_and_link_validation(self):
        owner, own = self.user()
        task = self.task(owner)
        url = f"/api/tasks/{task['id']}"
        code, _ = own.request('PATCH', url, {'version': task['version'], 'nextStep': 'New step'})
        self.assertEqual(code, 200)
        self.assertEqual(own.request('PATCH', url, {'version': task['version'], 'nextStep': 'Stale update'})[0], 409)
        current = self.get_task(own, task['id'])
        code, _ = own.request('PATCH', url, {'version': current['version'], 'evidence': 'javascript:alert(1)'})
        self.assertIn(code, (400, 422))

    def test_manager_cannot_escalate_privileges(self):
        manager, mgr = self.user('manager')
        code, _ = mgr.request('PATCH', f"/api/users/{manager['id']}", {'role': 'admin'})
        self.assertEqual(code, 403)
        code, _ = mgr.request('POST', '/api/users', {'name': 'Forbidden manager', 'username': 'forbidden-manager', 'password': PASSWORD, 'role': 'admin', 'capacity': 40})
        self.assertEqual(code, 403)

    def test_daily_weekly_reports_preserve_snapshot_and_isolate_owners(self):
        owner, own = self.user()
        outsider, other = self.user()
        task = self.task(owner)
        monday = local_today() - timedelta(days=local_today().weekday())
        for kind, period in [('daily', local_today().isoformat()), ('weekly', monday.isoformat())]:
            code, summary = own.request('GET', f'/api/report-summary?kind={kind}&period={period}')
            self.assertEqual(code, 200, summary)
            self.assertTrue(any(t['id'] == task['id'] for t in summary['tasks']))
            code, report = own.request('POST', '/api/reports', {'kind': kind, 'period': period, 'result': 'Bàn giao bản nháp', 'blocker': '', 'nextPlan': 'Hoàn thiện bản dựng'})
            self.assertIn(code, (200, 201), report)
            report = report.get('report', report)
            original_snapshot = copy.deepcopy(report['snapshot'])
            self.assertEqual(own.request('POST', '/api/reports', {
                'kind': kind, 'period': period, 'result': 'Duplicate', 'nextPlan': 'Duplicate',
            })[0], 409)
            current = self.get_task(own, task['id'])
            self.assertEqual(own.request('PATCH', f"/api/tasks/{task['id']}", {'version': current['version'], 'nextStep': kind + ' after snapshot'})[0], 200)
            data = own.request('GET', '/api/bootstrap')[1]
            saved = next(r for r in data['reports'] if r['id'] == report['id'])
            self.assertEqual(saved['snapshot'], original_snapshot)
            others = other.request('GET', '/api/bootstrap')[1]['reports']
            self.assertFalse(any(r['id'] == report['id'] for r in others))
            self.assertEqual(other.request('PATCH', f"/api/reports/{report['id']}", {'reviewStatus': 'reviewed', 'reviewNote': 'unauthorized'})[0], 403)
            self.assertEqual(self.admin.request('PATCH', f"/api/reports/{report['id']}", {'reviewStatus': 'reviewed', 'reviewNote': 'Đã xem'})[0], 200)

    def test_password_change_and_deactivation_invalidate_sessions(self):
        owner, own = self.user()
        second = Client(self.base)
        second.login(owner['username'])
        code, result = own.request('POST', '/api/password', {
            'currentPassword': PASSWORD, 'newPassword': PASSWORD + '-new',
        })
        self.assertEqual(code, 200, result)
        self.assertEqual(own.request('GET', '/api/bootstrap')[0], 401)
        self.assertEqual(second.request('GET', '/api/bootstrap')[0], 401)
        own.login(owner['username'], PASSWORD + '-new')
        self.assertEqual(self.admin.request('PATCH', f"/api/users/{owner['id']}", {'active': False})[0], 200)
        self.assertEqual(own.request('GET', '/api/bootstrap')[0], 401)
        self.assertEqual(own.request('POST', '/api/login', {'username': owner['username'], 'password': PASSWORD + '-new'})[0], 401)

    def test_last_admin_and_report_owner_are_protected(self):
        admin_id = self.admin.request('GET', '/api/session')[1]['user']['id']
        self.assertEqual(self.admin.request('PATCH', f'/api/users/{admin_id}', {'active': False})[0], 400)
        owner, own = self.user()
        other, _ = self.user()
        self.assertEqual(own.request('POST', '/api/reports', {
            'kind': 'daily', 'period': local_today().isoformat(), 'ownerId': other['id'],
            'result': 'Spoofed', 'nextPlan': 'Spoofed',
        })[0], 403)
        self.assertEqual(own.request('GET', f"/api/report-summary?ownerId={other['id']}")[0], 403)

    def test_malformed_nested_values_return_client_errors(self):
        owner, own = self.user()
        task = self.task(owner)
        url = f"/api/tasks/{task['id']}"
        for payload in [
            {'version': task['version'], 'priority': []},
            {'version': task['version'], 'stages': [{'key': []}, {}, {}]},
            {'version': task['version'], 'ownerId': 10**100},
            {'version': task['version'], 'publicationStatus': {}},
        ]:
            code, data = self.admin.request('PATCH', url, payload)
            self.assertEqual(code, 400, data)
        self.assertEqual(own.request('POST', url + '/action', {
            'version': task['version'], 'action': [],
        })[0], 400)
        self.assertEqual(own.request('POST', '/api/reports', {
            'kind': [], 'period': local_today().isoformat(), 'result': 'Test', 'nextPlan': 'Test',
        })[0], 400)
        self.assertEqual(self.admin.request('POST', '/api/users', {
            'name': 'Invalid role', 'username': 'invalid-role', 'password': PASSWORD, 'role': [],
        })[0], 400)
        self.assertEqual(own.request('GET', '/api/report-summary?kind=weekly&period=9999-12-31')[0], 400)
        self.assertEqual(self.admin.request('PATCH', url, {
            'version': task['version'], 'title': '\ud800',
        })[0], 400)

    def test_task_audit_records_specific_changes_and_previous_values(self):
        owner, own = self.user()
        task = self.task(owner)
        stages = copy.deepcopy(task['stages'])
        stages[0]['status'] = 'done'
        stages[0]['note'] = 'Kịch bản đã được rà soát thông tin sản phẩm'
        code, updated = own.request('PATCH', f"/api/tasks/{task['id']}", {
            'version': task['version'], 'stages': stages, 'nextStep': 'Chuẩn bị cảnh quay',
            'evidence': 'https://example.com/script-v1',
        })
        self.assertEqual(code, 200, updated)
        event = updated['history'][0]
        self.assertEqual(event['actorId'], owner['id'])
        self.assertIn('Kịch bản', event['action'])
        self.assertIn('Hoàn thành', event['action'])
        self.assertIn(stages[0]['note'], event['action'])
        changes = {change['field']: change for change in event['changes']}
        self.assertEqual(changes['stages.script.status']['before'], 'todo')
        self.assertEqual(changes['stages.script.status']['after'], 'done')
        self.assertEqual(changes['nextStep']['after'], 'Chuẩn bị cảnh quay')
        self.assertEqual(changes['evidence']['after'], 'https://example.com/script-v1')
        new_due = (local_today() + timedelta(days=1)).isoformat()
        code, revised = self.admin.request('PATCH', f"/api/tasks/{task['id']}", {
            'version': updated['version'], 'due': new_due,
        })
        self.assertEqual(code, 200, revised)
        self.assertEqual(revised['originalDue'], task['originalDue'])
        changes = {change['field']: change for change in revised['history'][0]['changes']}
        self.assertEqual(changes['due']['before'], task['due'])
        self.assertEqual(changes['due']['after'], new_due)

    def test_z_database_survives_server_restart(self):
        code, before = self.admin.request('GET', '/api/bootstrap')
        self.assertEqual(code, 200)
        self.stop_server()
        self.start_server()
        client = Client(self.base)
        client.login('test-admin')
        after = client.request('GET', '/api/bootstrap')[1]
        self.assertEqual({t['id'] for t in before['tasks']}, {t['id'] for t in after['tasks']})
        self.assertEqual({u['id'] for u in before['users']}, {u['id'] for u in after['users']})
        self.assertEqual({r['id'] for r in before['reports']}, {r['id'] for r in after['reports']})


if __name__ == '__main__':
    unittest.main()
