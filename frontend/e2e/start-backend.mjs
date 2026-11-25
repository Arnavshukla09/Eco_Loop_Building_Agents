import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../../', import.meta.url));
const output = path.join(root, 'output', 'e2e');
mkdirSync(output, { recursive: true });
const runDirectory = mkdtempSync(path.join(output, 'run-'));
const python = process.env.E2E_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const child = spawn(python, ['-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', '8011'], {
  cwd: root,
  stdio: 'inherit',
  env: {
    ...process.env,
    ENVIRONMENT: 'production',
    REQUIRE_API_KEY: 'true',
    API_KEY: 'e2e-only-token-not-for-deployment',
    SIMULATION_MODE: 'true',
    CONTROL_PROVIDER: 'rule_based',
    OLLAMA_HOST: 'http://127.0.0.1:9',
    DATABASE_URL: `sqlite+aiosqlite:///${path.join(runDirectory, 'test.db').replaceAll('\\', '/')}`,
    SPEEDUP_FACTOR: '240',
    AGENT_INTERVAL_SECONDS: '1',
    WS_BROADCAST_INTERVAL: '0.5',
    CORS_ORIGINS: '["http://127.0.0.1:8011"]',
  },
});
child.on('error', error => { console.error(error); process.exit(1); });
child.on('exit', code => process.exit(code || 0));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill('SIGTERM'));
