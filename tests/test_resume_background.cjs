const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('local-resume-companion-extension/background.js', 'utf8');

function fixture(reply, connectionError) {
  let listener;
  const stored = {};
  const runtime = {
    onMessage: { addListener(fn) { listener = fn; } },
    sendNativeMessage(host, message, callback) {
      runtime.lastError = connectionError ? { message: connectionError } : undefined;
      callback(reply);
      runtime.lastError = undefined;
    },
  };
  vm.runInNewContext(source, { chrome: {
    runtime,
    storage: { session: { async set(values) { Object.assign(stored, values); }, remove() {} } },
    tabs: { onRemoved: { addListener() {} } },
  } });
  return {
    stored,
    request() {
      return new Promise(resolve => listener({ type: 'resume-target' }, {
        tab: { id: 7 }, frameId: 0, documentId: 'document', url: 'https://example.com/apply',
      }, resolve));
    },
  };
}

test('native connection failure is visible before any target is returned', async () => {
  const f = fixture(undefined, 'Native messaging host not found');
  const reply = await f.request();
  assert.equal(reply.error, 'Native messaging host not found');
  assert.equal(f.stored['7:0'].status, 'blocked');
  assert.equal(f.stored['7:0'].error, reply.error);
});

test('native queue errors are visible rather than silently idle', async () => {
  const f = fixture({ error: 'Could not read the approved résumé or attachment request' });
  const reply = await f.request();
  assert.equal(f.stored['7:0'].status, 'blocked');
  assert.equal(f.stored['7:0'].error, reply.error);
});

test('an empty queue is not reported as a connection failure', async () => {
  const f = fixture({ pending: true });
  const reply = await f.request();
  assert.equal(reply.pending, true);
  assert.equal(f.stored['7:0'].status, 'idle');
});
