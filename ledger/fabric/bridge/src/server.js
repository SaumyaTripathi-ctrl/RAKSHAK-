// HTTP <-> Fabric bridge used by backend/rakshak/ledger/client.py (FabricLedger).
// The server only needs a `contract` with submitTransaction/evaluateTransaction, so it is unit-testable
// without a Fabric network. EXPERIMENTAL: not exercised against a live network in CI.
import http from 'node:http';

const decoder = new TextDecoder();
const asText = (bytes) => decoder.decode(bytes);

function send(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(payload) });
  res.end(payload);
}

async function readJson(req, limit = 256 * 1024) {
  let size = 0;
  const chunks = [];
  for await (const chunk of req) {
    size += chunk.length;
    if (size > limit) throw Object.assign(new Error('body too large'), { status: 413 });
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw Object.assign(new Error('invalid JSON'), { status: 400 });
  }
}

export function createServer(contract, { token } = {}) {
  return http.createServer(async (req, res) => {
    try {
      if (token && req.headers.authorization !== `Bearer ${token}`) return send(res, 401, { error: 'unauthorized' });
      const url = new URL(req.url, 'http://bridge');
      const path = url.pathname;

      if (req.method === 'GET' && path === '/health') {
        const health = JSON.parse(asText(await contract.evaluateTransaction('Health')));
        return send(res, 200, health);
      }
      if (req.method === 'POST' && path === '/entries') {
        const body = await readJson(req);
        if (typeof body.kind !== 'string' || typeof body.payload !== 'object' || body.payload === null) {
          return send(res, 400, { error: 'kind (string) and payload (object) are required' });
        }
        const txId = asText(await contract.submitTransaction('Submit', body.kind, JSON.stringify(body.payload)));
        return send(res, 200, { txId });
      }
      if (req.method === 'GET' && path === '/entries') {
        const limit = Math.min(Math.max(parseInt(url.searchParams.get('limit') ?? '50', 10) || 50, 1), 500);
        const offset = Math.max(parseInt(url.searchParams.get('offset') ?? '0', 10) || 0, 0);
        const raw = asText(await contract.evaluateTransaction('ListEntries', String(limit), String(offset)));
        return send(res, 200, { entries: JSON.parse(raw) });
      }
      const m = path.match(/^\/entries\/([A-Za-z0-9]+)$/);
      if (req.method === 'GET' && m) {
        const raw = asText(await contract.evaluateTransaction('GetEntry', m[1]));
        return raw ? send(res, 200, JSON.parse(raw)) : send(res, 404, { error: 'not found' });
      }
      return send(res, 404, { error: 'not found' });
    } catch (err) {
      const status = err.status ?? 502;
      return send(res, status, { error: String(err.message ?? err) });
    }
  });
}
