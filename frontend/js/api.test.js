import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('./api.js', import.meta.url), 'utf8');
async function transport(base) {
  const configured = source.replace("import {API_BASE_URL} from './config.js';",
    `const API_BASE_URL = ${JSON.stringify(base)};`);
  return import(`data:text/javascript;base64,${Buffer.from(configured).toString('base64')}`);
}

test('Local API links retain the same origin', async () => {
  const {apiUrl} = await transport('');
  assert.equal(apiUrl('status'), '/api/status');
});

test('Deployed API and download links use Render directly', async () => {
  const {apiUrl, api} = await transport('https://example.onrender.com/');
  assert.equal(apiUrl('history/demo/export?format=csv'),
    'https://example.onrender.com/api/history/demo/export?format=csv');
  assert.equal(apiUrl('notebooks/demo/attachments/file'),
    'https://example.onrender.com/api/notebooks/demo/attachments/file');
  const original = globalThis.fetch;
  let captured;
  globalThis.fetch = async (url, options) => {
    captured = {url, options};
    return {ok: true, json: async () => ({saved: true})};
  };
  try {
    assert.deepEqual(await api('analyze', {mode: 'text', text: '82:100'}), {saved: true});
    assert.equal(captured.url, 'https://example.onrender.com/api/analyze');
    assert.equal(captured.options.method, 'POST');
    assert.equal(captured.options.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(captured.options.body), {mode: 'text', text: '82:100'});
  } finally { globalThis.fetch = original; }
});
