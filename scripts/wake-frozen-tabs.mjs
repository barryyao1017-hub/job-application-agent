#!/usr/bin/env node
// Find tabs in the agent's Chrome that Chrome has frozen and wake them.
//
// agent-vault's Playwright connect_over_cdp attaches to every page, and a frozen background tab
// never answers, so login and register time out (2026-10-25, JOB-51). This reads each page's
// visibility state with a short timeout; a page that does not answer is activated (brought to the front of
// its window, which unfreezes it without a reload, so a parked form keeps its answers) and
// probed again. The tabs that were visible before are then brought back to the front, so a
// running worker's tab is not left in the background. It never reloads or closes a tab.
// Prints one JSON object: {"pages", "frozen": [...], "woken": [...], "still_frozen": [...]}; each entry is {id, host}.
//
// Usage: node scripts/wake-frozen-tabs.mjs [--port 9222] [--timeout-ms 2000]

const args = process.argv.slice(2);
const option = (name, fallback) => {
  const index = args.indexOf(name);
  return index >= 0 ? Number(args[index + 1]) : fallback;
};
const port = option('--port', 9222);
const timeoutMs = option('--timeout-ms', 2000);
const base = `http://localhost:${port}`;

// Resolves to the page's document.visibilityState, or null when it does not answer in time.
function responds(page) {
  return new Promise((resolve) => {
    let socket;
    const done = (answer) => {
      clearTimeout(timer);
      try { socket?.close(); } catch {}
      resolve(answer);
    };
    const timer = setTimeout(() => done(null), timeoutMs);
    try {
      socket = new WebSocket(page.webSocketDebuggerUrl);
    } catch {
      done(null);
      return;
    }
    socket.onopen = () => socket.send(JSON.stringify({
      id: 1, method: 'Runtime.evaluate', params: { expression: 'document.visibilityState', returnByValue: true },
    }));
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.id === 1) done(message.result?.result?.value ?? 'unknown');
    };
    socket.onerror = () => done(null);
  });
}

const host = (url) => {
  try { return new URL(url).host || url; } catch { return url; }
};

const pages = (await (await fetch(`${base}/json/list`)).json())
  .filter((target) => target.type === 'page' && target.webSocketDebuggerUrl);
const describe = (page) => ({ id: page.id, host: host(page.url) });

const answers = await Promise.all(pages.map(responds));
const frozen = pages.filter((_, index) => answers[index] === null);
const visible = pages.filter((_, index) => answers[index] === 'visible');
const woken = [];
const stillFrozen = [];
for (const page of frozen) {
  await fetch(`${base}/json/activate/${page.id}`);
  ((await responds(page)) === null ? stillFrozen : woken).push(describe(page));
}
if (frozen.length) {
  for (const page of visible) await fetch(`${base}/json/activate/${page.id}`);
}
console.log(JSON.stringify({
  pages: pages.length,
  frozen: frozen.map(describe),
  woken,
  still_frozen: stillFrozen,
}));
