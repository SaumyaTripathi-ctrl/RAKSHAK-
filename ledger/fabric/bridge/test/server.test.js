import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createServer } from '../src/server.js';

const enc = (s) => new TextEncoder().encode(s);

function fakeContract() {
  const calls = [];
  return {
    calls,
    async submitTransaction(name, ...args) {
      calls.push(['submit', name, ...args]);
      return enc('tx123');
    },
    async evaluateTransaction(name, ...args) {
      calls.push(['eval', name, ...args]);
      if (name === 'Health') return enc('{"ok":true,"entries":2,"problem":""}');
      if (name === 'ListEntries') return enc('[{"txId":"b","kind":"BATCH","payload":{},"ts":2}]');
      if (name === 'GetEntry') return args[0] === 'tx123' ? enc('{"txId":"tx123","kind":"BATCH","payload":{},"ts":1}') : enc('');
      throw new Error('unexpected ' + name);
    },
  };
}

async function withServer(contract, opts, fn) {
  const server = createServer(contract, opts);
  await new Promise((r) => server.listen(0, r));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    await fn(base);
  } finally {
    await new Promise((r) => server.close(r));
  }
}

test('submit, get, list, health', async () => {
  const c = fakeContract();
  await withServer(c, {}, async (base) => {
    let r = await fetch(`${base}/entries`, {
      method: 'POST',
      body: JSON.stringify({ kind: 'BATCH', payload: { merkle_root: 'ab' } }),
    });
    assert.equal(r.status, 200);
    assert.deepEqual(await r.json(), { txId: 'tx123' });
    assert.deepEqual(c.calls[0], ['submit', 'Submit', 'BATCH', '{"merkle_root":"ab"}']);

    r = await fetch(`${base}/entries/tx123`);
    assert.equal((await r.json()).txId, 'tx123');
    assert.equal((await fetch(`${base}/entries/nope`)).status, 404);

    r = await fetch(`${base}/entries?limit=5&offset=1`);
    assert.equal((await r.json()).entries.length, 1);
    assert.deepEqual(c.calls.at(-1), ['eval', 'ListEntries', '5', '1']);

    assert.deepEqual(await (await fetch(`${base}/health`)).json(), { ok: true, entries: 2, problem: '' });
  });
});

test('validation and errors', async () => {
  const c = fakeContract();
  await withServer(c, {}, async (base) => {
    assert.equal((await fetch(`${base}/entries`, { method: 'POST', body: '{"kind":"BATCH"}' })).status, 400);
    assert.equal((await fetch(`${base}/entries`, { method: 'POST', body: 'nope' })).status, 400);
    assert.equal((await fetch(`${base}/entries/bad%20id`)).status, 404);
  });
  const failing = {
    submitTransaction: async () => {
      throw new Error('endorsement failed');
    },
    evaluateTransaction: async () => enc(''),
  };
  await withServer(failing, {}, async (base) => {
    const r = await fetch(`${base}/entries`, { method: 'POST', body: JSON.stringify({ kind: 'BATCH', payload: {} }) });
    assert.equal(r.status, 502);
    assert.match((await r.json()).error, /endorsement failed/);
  });
});

test('bearer token is enforced when configured', async () => {
  await withServer(fakeContract(), { token: 's3cret' }, async (base) => {
    assert.equal((await fetch(`${base}/health`)).status, 401);
    const r = await fetch(`${base}/health`, { headers: { authorization: 'Bearer s3cret' } });
    assert.equal(r.status, 200);
  });
});
