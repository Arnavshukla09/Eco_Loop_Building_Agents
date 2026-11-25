import { test, expect } from '@playwright/test';

const authorization = { Authorization: 'Bearer e2e-only-token-not-for-deployment' };

async function openDashboard(page) {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Eco-Loop Building Agent', exact: true })).toBeVisible();
  await expect(page.getByText('Live', { exact: true })).toBeVisible();
}

async function enterToken(page) {
  await page.getByRole('button', { name: 'Auth', exact: true }).click();
  await page.getByLabel('API token').fill('e2e-only-token-not-for-deployment');
}

test.beforeEach(async ({ request }) => {
  const response = await request.post('/api/simulation/reset', { headers: authorization });
  expect(response.ok()).toBeTruthy();
});

test('production dashboard streams telemetry through a heartbeat without browser errors', async ({ page, request }, testInfo) => {
  const errors = [];
  const failedResponses = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('response', response => { if (response.status() >= 400) failedResponses.push(`${response.status()} ${response.url()}`); });
  await openDashboard(page);
  await expect(page.getByRole('heading', { name: 'Zone Overview' })).toBeVisible();
  await expect(page.getByText('ASHRAE 55', { exact: true })).toHaveCount(0);
  await expect(page.getByText('5 Zones Monitored')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Control status' })).toContainText('rule_based');
  await expect(page.getByRole('heading', { name: 'AI Agent Decision', exact: true })).toBeVisible();
  const first = await (await request.get('/api/status')).json();
  await expect.poll(async () => (await (await request.get('/api/status')).json()).building.timestep).toBeGreaterThan(first.building.timestep);
  // The client pings at 20 seconds; the plain-text pong must not reach JSON.parse.
  await page.waitForTimeout(21000);
  await expect(page.getByText('Dashboard Error', { exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
  expect(failedResponses).toEqual([]);
  await page.screenshot({ path: `test-results/dashboard-desktop-${testInfo.project.name}.png`, fullPage: true });
});

test('protected controls reject an absent key, apply a scoped hold, and release it', async ({ page, request }) => {
  await openDashboard(page);
  await page.getByRole('button', { name: 'Apply Setpoint Override' }).click();
  await expect(page.getByRole('alert')).toContainText('Forbidden');
  await enterToken(page);
  await page.getByLabel('API token').fill('incorrect-token');
  await page.getByRole('button', { name: 'Apply Setpoint Override' }).click();
  await expect(page.getByRole('alert')).toContainText('Forbidden');
  await page.getByLabel('API token').fill('e2e-only-token-not-for-deployment');
  await page.getByLabel('Target Zone').selectOption('Core');
  await page.getByLabel('Hold duration', { exact: true }).fill('1440');
  await page.getByRole('button', { name: 'Apply Setpoint Override' }).click();
  await expect(page.getByRole('status')).toContainText('Manual hold active');
  await expect(page.getByRole('status')).toContainText('Core: Cool');
  await expect(page.getByRole('region', { name: 'Control status' })).toContainText('Core: held at');
  const control = await (await request.get('/api/control')).json();
  expect(Object.keys(control.overrides)).toEqual(['Core']);
  expect(await page.evaluate(() => localStorage.getItem('eco_api_key'))).toBeNull();
  await page.getByRole('button', { name: 'Release all holds' }).click();
  await expect(page.getByRole('region', { name: 'Control status' })).toContainText('No manual holds');
  await page.reload();
  await expect(page.getByRole('button', { name: 'Key Set' })).toBeVisible();
});

test('a lost websocket reconnects and resumes live telemetry', async ({ page }) => {
  await page.addInitScript(() => {
    const NativeWebSocket = window.WebSocket;
    window.WebSocket = class extends NativeWebSocket {
      constructor(...args) {
        super(...args);
        window.__telemetrySocket = this;
      }
    };
  });
  await openDashboard(page);
  await page.evaluate(() => window.__telemetrySocket.close());
  await expect(page.getByText('Disconnected from building server:', { exact: true })).toBeVisible();
  await expect(page.getByText('Live', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Apply Setpoint Override' })).toBeEnabled();
});

test('hold release handles a network failure and succeeds when retried', async ({ page, request }) => {
  const response = await request.post('/api/setpoint', { headers: authorization, data: { zone: 'Core', cooling: 24, heating: 20, duration_minutes: 1440 } });
  expect(response.ok()).toBeTruthy();
  await openDashboard(page);
  await enterToken(page);
  await page.route('**/api/override/release', route => route.abort('connectionfailed'));
  await page.getByRole('button', { name: 'Release all holds' }).click();
  const control = page.getByRole('region', { name: 'Control status' });
  await expect(control.getByRole('alert')).toContainText('Unable to reach the building server');
  await page.unroute('**/api/override/release');
  await page.getByRole('button', { name: 'Release all holds' }).click();
  await expect(control).toContainText('No manual holds');
  await expect(control.getByRole('alert')).toHaveCount(0);
});

test('thermostat adjustments maintain the safety deadband and render structured validation errors', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await openDashboard(page);
  await page.getByLabel('Heating Setpoint', { exact: true }).fill('22');
  await page.getByLabel('Cooling Setpoint', { exact: true }).fill('20');
  const heating = Number(await page.getByLabel('Heating Setpoint', { exact: true }).inputValue());
  const cooling = Number(await page.getByLabel('Cooling Setpoint', { exact: true }).inputValue());
  expect(cooling - heating).toBeGreaterThanOrEqual(1.5);
  await page.route('**/api/setpoint', route => route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: [{ loc: ['body', 'zone'], msg: 'Unknown zone' }] }) }));
  await page.getByRole('button', { name: 'Apply Setpoint Override' }).click();
  await expect(page.getByRole('alert')).toContainText('Unknown zone');
  await expect(page.getByText('Dashboard Error', { exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('reset archives a run, replays saved readings, and exports measured CSV data', async ({ page, request }) => {
  await openDashboard(page);
  await enterToken(page);
  const before = await (await request.get('/api/control')).json();
  await expect.poll(async () => (await (await request.get(`/api/simulation/runs/${before.run_id}/history`)).json()).entries.length).toBeGreaterThan(1);
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Reset', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('reset to initial state');
  const after = await (await request.get('/api/control')).json();
  expect(after.run_id).not.toBe(before.run_id);
  await page.getByRole('button', { name: 'Refresh runs' }).click();
  const runs = page.getByRole('region', { name: 'Saved simulation runs' });
  await expect(runs).toContainText('Archived');
  await runs.getByRole('button', { name: before.run_id, exact: true }).click();
  await expect(runs.getByLabel('Replay position')).toBeVisible();
  await runs.getByRole('button', { name: 'Play replay' }).click();
  await expect.poll(async () => Number(await runs.getByLabel('Replay position').inputValue())).toBeGreaterThan(0);
  const downloadPromise = page.waitForEvent('download');
  await runs.getByRole('link', { name: 'Download CSV' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('simulation-history.csv');
  await download.saveAs('test-results/simulation-history.csv');
  const csv = await (await request.get(`/api/simulation/runs/${before.run_id}/export`)).text();
  expect(csv).toContain('baseline_power_kw');
  expect(csv.trim().split('\n').length).toBeGreaterThan(2);
});

test('run history HTTP failures are visible and recover on refresh', async ({ page }) => {
  await page.route('**/api/simulation/runs', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Unavailable"}' }));
  await openDashboard(page);
  const runs = page.getByRole('region', { name: 'Saved simulation runs' });
  await expect(runs.getByRole('alert')).toContainText('Unable to load saved runs');
  await page.unroute('**/api/simulation/runs');
  await runs.getByRole('button', { name: 'Refresh runs' }).click();
  await expect(runs.getByRole('alert')).toHaveCount(0);
});

test('mobile viewport keeps the dashboard and controls usable', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openDashboard(page);
  await expect(page.getByRole('button', { name: 'Apply Setpoint Override' })).toBeEnabled();
  const width = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, viewport: window.innerWidth }));
  expect(width.scroll).toBeLessThanOrEqual(width.viewport);
  await page.screenshot({ path: `test-results/dashboard-mobile-${testInfo.project.name}.png`, fullPage: true });
});
