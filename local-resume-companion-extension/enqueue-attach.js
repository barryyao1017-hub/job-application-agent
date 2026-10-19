#!/usr/local/bin/node
import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const [targetUrl, ...args] = process.argv.slice(2);
const options = {};
for (let i = 0; i < args.length; i += 2) {
  if (!['--tab-id', '--frame-id', '--selector', '--shadow-hosts'].includes(args[i]) || args[i + 1] === undefined || options[args[i]] !== undefined) {
    throw new Error('Use URL [--tab-id ID --frame-id ID --selector CSS [--shadow-hosts JSON_ARRAY]].');
  }
  options[args[i]] = args[i + 1];
}
if (!/^https?:\/\//.test(targetUrl || '')) throw new Error('Provide the exact application document URL.');
new URL(targetUrl);
const target = { version: 2, requestId: randomUUID(), url: targetUrl };
if (Object.keys(options).length) {
  for (const key of ['--tab-id', '--frame-id', '--selector']) {
    if (!options[key]) throw new Error('Explicit targeting requires tab ID, frame ID, and selector together.');
  }
  for (const key of ['--tab-id', '--frame-id']) {
    if (!/^\d+$/.test(options[key]) || !Number.isSafeInteger(Number(options[key]))) throw new Error('Tab and frame IDs must be nonnegative integers.');
  }
  Object.assign(target, { tabId: Number(options['--tab-id']), frameId: Number(options['--frame-id']), selector: options['--selector'] });
  if (options['--shadow-hosts']) {
    target.shadowHosts = JSON.parse(options['--shadow-hosts']);
    if (!Array.isArray(target.shadowHosts) || !target.shadowHosts.every(s => typeof s === 'string' && s.trim())) throw new Error('Shadow hosts must be a JSON array of CSS selectors.');
  }
}
const directory = path.dirname(fileURLToPath(import.meta.url));
const queue = path.join(directory, 'attach-target-url.txt');
const lock = queue + '.lock';
fs.mkdirSync(lock); // Shared with native host: never overwrite an in-flight claim.
try {
  const temp = queue + '.' + target.requestId;
  fs.writeFileSync(temp, JSON.stringify(target), { mode: 0o600 });
  fs.renameSync(temp, queue);
} finally {
  fs.rmdirSync(lock);
}
console.log(JSON.stringify({ requestId: target.requestId, mode: target.selector ? 'explicit' : 'automatic', status: 'queued' }));
