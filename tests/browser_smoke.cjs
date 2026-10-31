/* Optional end-to-end smoke check. Uses an isolated temporary database.
 * Run: node tests/browser_smoke.cjs
 * Requires Playwright and Chromium. No credentials or user data are persisted.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
let playwright;
try { playwright = require('playwright'); }
catch { playwright = require('/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'); }
const PASSWORD = 'browser-test-only-42';
const ROOT = path.resolve(__dirname, '..');
const taskTitle = 'Video hướng dẫn SafeStraps · Kiểm thử nội bộ';
const localToday = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function freePort() {
  const server = net.createServer();
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

async function main() {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'supernet-browser-'));
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const python = process.env.PYTHON_TEST_EXECUTABLE || (process.platform === 'win32' ? 'python' : 'python3');
  const server = spawn(python, ['server.py', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: ROOT, env: { ...process.env, SUPERNET_DATA_DIR: path.join(temp, 'data') }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let serverOutput = '';
  server.stdout.on('data', b => { serverOutput += b.toString(); });
  server.stderr.on('data', b => { serverOutput += b.toString(); });
  let browser;
  const errors = [];
  let step = 'server startup';
  try {
    let ready = false;
    for (let i = 0; i < 100; i++) {
      try { const response = await fetch(base + '/api/status'); if (response.ok) { ready = true; break; } } catch {}
      if (server.exitCode !== null) break;
      await delay(100);
    }
    assert(ready, 'Temporary server failed to start: ' + serverOutput);
    const executablePath = process.env.CHROMIUM_EXECUTABLE || (process.platform === 'linux' ? '/usr/bin/chromium' : undefined);
    browser = await playwright.chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}), args: ['--no-sandbox'] });
    async function pageFor() {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(e.message));
      await page.goto(base);
      return page;
    }
    const admin = await pageFor();
    async function nav(page, id) {
      await page.locator(`[data-nav="${id}"]`).click();
      await page.locator('#app').waitFor();
    }
    async function modalClosed(page) { await page.locator('#overlay').waitFor({ state: 'hidden' }); }
    async function openTask(page) {
      await nav(page, 'tasks');
      await page.locator(`[data-task]`).filter({ hasText: taskTitle }).first().click();
      await page.locator('#task-update').waitFor();
    }
    async function refresh(page) {
      const response = page.waitForResponse(r => r.url().endsWith('/api/bootstrap') && r.status() === 200);
      await page.locator('#refresh').click();
      await response;
    }
    async function login(page, username) {
      await page.locator('#auth-form [name=username]').fill(username);
      await page.locator('#auth-form [name=password]').fill(PASSWORD);
      await page.locator('#auth-form button[type=submit]').click();
      await page.locator('[data-nav=overview]').waitFor();
    }
    step = 'first administrator setup';
    await admin.locator('#auth-form [name=name]').fill('Thanh Nguyễn');
    await admin.locator('#auth-form [name=username]').fill('test-admin');
    await admin.locator('#auth-form [name=password]').fill(PASSWORD);
    await admin.locator('#auth-form [name=confirm]').fill(PASSWORD);
    await admin.locator('#auth-form button[type=submit]').click();
    await admin.locator('[data-nav=team]').waitFor();

    step = 'create employee and intern through UI';
    await nav(admin, 'team');
    for (const [name, username, role, capacity] of [
      ['Thùy Dung', 'test-content', 'content', '40'], ['Như Ý', 'test-intern', 'intern', '24'],
    ]) {
      await admin.locator('#add-user').click();
      const form = admin.locator('#user-form');
      await form.locator('[name=name]').fill(name);
      await form.locator('[name=username]').fill(username);
      await form.locator('[name=password]').fill(PASSWORD);
      await form.locator('[name=role]').selectOption(role);
      await form.locator('[name=capacity]').fill(capacity);
      await form.locator('button.primary').click();
      await modalClosed(admin);
      await admin.locator('.member h3', { hasText: name }).waitFor();
    }
    const directory = await (await admin.context().request.get(base + '/api/bootstrap')).json();
    const employeeId = directory.users.find(u => u.username === 'test-content').id;
    const internId = directory.users.find(u => u.username === 'test-intern').id;

    step = 'create content with three individual stage assignments';
    await nav(admin, 'tasks');
    await admin.locator('[data-create]').first().click();
    const create = admin.locator('#create-form');
    await create.locator('[name=title]').fill(taskTitle);
    await create.locator('[name=channel]').fill('Safestraps Official');
    await create.locator('[name=pillar]').selectOption('PRODUCT');
    await create.locator('[name=angle]').fill('USP / Hướng dẫn sử dụng');
    await create.locator('[name=series]').fill('Hướng dẫn · Tập 01');
    await create.locator('[name=ownerId]').selectOption(String(employeeId));
    await create.locator('[name=due]').fill(localToday());
    await create.locator('[name=description]').fill('Video hướng dẫn thu kéo dây, có cảnh cận sản phẩm và thao tác thực tế.');
    await create.locator('[name=criteria]').fill('Thông tin chính xác, đủ cảnh, phụ đề rõ và có link bàn giao.');
    await create.locator('[name=nextStep]').fill('Chốt kịch bản cùng trưởng nhóm.');
    for (const key of ['script', 'shoot', 'edit']) {
      await create.locator(`[name=stage_${key}_owner]`).selectOption(String(key === 'edit' ? internId : employeeId));
      await create.locator(`[name=stage_${key}_due]`).fill(localToday());
    }
    await create.locator('button.primary').click();
    await modalClosed(admin);
    await admin.getByText(taskTitle, { exact: true }).waitFor();

    step = 'employee login and own-stage update';
    const employee = await pageFor();
    await login(employee, 'test-content');
    assert.equal(await employee.locator('[data-nav=team]').count(), 0, 'Employee must not see account management');
    await openTask(employee);
    await employee.locator('[data-action=start]').click();
    await modalClosed(employee);
    await openTask(employee);
    assert(await employee.locator('[name=stage_edit_status]').isDisabled(), 'Intern stage must be read-only for employee');
    await employee.locator('[name=stage_script_status]').selectOption('done');
    await employee.locator('[name=stage_script_note]').fill('Kịch bản đã hoàn thiện theo brief.');
    await employee.locator('[name=stage_shoot_status]').selectOption('done');
    await employee.locator('[name=stage_shoot_note]').fill('Footage đủ cảnh cận và thao tác.');
    await employee.locator('[name=scriptUrl]').fill('https://example.com/script');
    await employee.locator('[name=evidence]').fill('https://example.com/delivery');
    await employee.locator('[name=nextStep]').fill('Chờ Như Ý bàn giao bản dựng.');
    await employee.locator('#task-update button[type=submit]').click();
    await modalClosed(employee);

    step = 'intern updates assigned edit stage';
    const intern = await pageFor();
    await login(intern, 'test-intern');
    await openTask(intern);
    assert(await intern.locator('[name=stage_script_status]').isDisabled(), 'Script stage must be read-only for intern');
    await intern.locator('[name=stage_edit_status]').selectOption('done');
    await intern.locator('[name=stage_edit_note]').fill('Đã dựng, bổ sung phụ đề và ảnh bìa.');
    await intern.locator('#task-update button[type=submit]').click();
    await modalClosed(intern);

    step = 'employee submits, manager approves and publishes';
    await refresh(employee);
    await openTask(employee);
    await employee.locator('[data-action=submit]').click();
    await modalClosed(employee);
    await refresh(admin);
    await nav(admin, 'reviews');
    await admin.locator('[data-task]').filter({ hasText: taskTitle }).click();
    await admin.locator('[data-action=approve]').click();
    await modalClosed(admin);
    await openTask(admin);
    await admin.locator('#publish-form [name=publicationStatus]').selectOption('published');
    await admin.locator('#publish-form [name=publishAt]').fill(localToday() + 'T15:00');
    await admin.locator('#publish-form [name=publishUrl]').fill('https://example.com/published-video');
    await admin.locator('#publish-form button.primary').click();
    await modalClosed(admin);
    assert((await admin.locator('[data-task]').first().innerText()).includes('Đã đăng'), 'Publication status should persist');

    step = 'employee daily and weekly reports';
    await refresh(employee);
    await nav(employee, 'reports');
    await employee.locator('#report-summary .stat').first().waitFor();
    await employee.locator('#report-form [name=result]').fill('Đã hoàn thành kịch bản và quay video theo kế hoạch.');
    await employee.locator('#report-form [name=nextPlan]').fill('Chuẩn bị ý tưởng cho tập tiếp theo.');
    await employee.locator('#report-form button.primary').click();
    await employee.locator('.report-card').waitFor();
    assert.equal(await employee.locator('#report-form').count(), 0, 'Submitted daily report should be immutable');
    await employee.locator('#report-kind').selectOption('weekly');
    await employee.locator('#report-summary .stat').first().waitFor();
    await employee.locator('#report-form [name=result]').fill('Tuần này đã phối hợp hoàn thiện nội dung, nghiệm thu và xuất bản.');
    await employee.locator('#report-form [name=nextPlan]').fill('Lên kế hoạch nội dung tuần tiếp theo và thống nhất lịch quay.');
    await employee.locator('#report-form button.primary').click();
    await employee.locator('.report-card').waitFor();
    await employee.locator('[data-snapshot]').click();
    assert((await employee.locator('#overlay').innerText()).includes(taskTitle), 'Report snapshot should contain related content');
    await employee.locator('#overlay [data-close]').click();

    step = 'manager reviews daily report';
    await refresh(admin);
    await nav(admin, 'reports');
    await admin.locator('#report-kind').selectOption('daily');
    await admin.locator('#report-owner').selectOption(String(employeeId));
    await admin.locator('[data-review-report]').click();
    await admin.locator('#review-report-form [name=reviewNote]').fill('Đã kiểm tra đầu ra. Thống nhất lịch quay tập tiếp theo.');
    await admin.locator('#review-report-form button.primary').click();
    await modalClosed(admin);
    assert((await admin.locator('.report-card').innerText()).includes('Đã kiểm tra'), 'Manager review should appear');
    await refresh(employee);
    await employee.locator('#report-kind').selectOption('daily');
    assert((await employee.locator('.report-card').innerText()).includes('Thống nhất lịch quay'), 'Employee should see manager feedback');

    step = 'logout and login persistence';
    await admin.locator('#logout').click();
    await admin.locator('#auth-form').waitFor();
    await login(admin, 'test-admin');
    await nav(admin, 'overview');
    await admin.locator('#toast').waitFor({ state: 'hidden' });
    await admin.screenshot({ path: '/tmp/supernet-v2-desktop.png', fullPage: true });

    step = 'mobile navigation and modal width';
    await admin.setViewportSize({ width: 390, height: 844 });
    for (const id of ['mine', 'tasks', 'calendar', 'reviews', 'team', 'reports', 'overview']) {
      await nav(admin, id);
      const overflow = await admin.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      assert.equal(overflow, false, `Mobile page overflow: ${id}`);
    }
    await admin.screenshot({ path: '/tmp/supernet-v2-mobile.png', fullPage: true });
    await nav(admin, 'tasks');
    await admin.locator('[data-create]').first().click();
    assert.equal(await admin.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'Mobile modal page overflow');
    const modalOverflow = await admin.locator('.modal').evaluate(el => el.scrollWidth > el.clientWidth + 1);
    assert.equal(modalOverflow, false, 'Mobile modal contents overflow');
    await admin.keyboard.press('Escape');
    assert.equal(errors.length, 0, 'Unexpected browser errors: ' + errors.join('; '));
    console.log('PASS: UI setup, user roles, three-stage content assignment, separate employee/intern sessions, submission/approval/publication, daily and weekly reports/snapshots, manager feedback, logout/login and mobile layouts.');
    console.log('Screenshots: /tmp/supernet-v2-desktop.png, /tmp/supernet-v2-mobile.png');
  } catch (error) {
    throw new Error(`Browser smoke failed at ${step}: ${error.message}`);
  } finally {
    if (browser) await browser.close();
    server.kill();
    if (server.exitCode === null) await Promise.race([once(server, 'exit'), delay(5000)]);
    fs.rmSync(temp, { recursive: true, force: true });
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
