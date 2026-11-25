import test from 'node:test';
import assert from 'node:assert/strict';
import { apiError } from '../src/utils/api.js';

test('API validation errors become readable text instead of React children', () => {
  assert.equal(apiError({ detail: [{ loc: ['body', 'zone'], msg: 'Unknown zone' }] }, 'Failed'), 'Unknown zone');
  assert.equal(apiError({ detail: 'Forbidden' }, 'Failed'), 'Forbidden');
  assert.equal(apiError({ detail: { unexpected: true } }, 'Failed'), 'Failed');
});
