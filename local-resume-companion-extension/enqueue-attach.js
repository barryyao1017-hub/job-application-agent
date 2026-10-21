#!/usr/local/bin/node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
const targetUrl = process.argv[2];
if (!/^https?:\/\//.test(targetUrl || '')) throw new Error('Provide the exact application URL.');
const extensionDirectory = path.dirname(new URL(import.meta.url).pathname);
// One file per request, so concurrent workers never overwrite each other. The
// native host claims an entry by renaming it, and only for a page whose URL
// contains the queued one. RESUME_QUEUE_DIR exists for tests.
const queueDirectory = process.env.RESUME_QUEUE_DIR || path.join(extensionDirectory, 'attach-queue');
fs.mkdirSync(queueDirectory, { recursive: true, mode: 0o700 });
const name = `${Date.now()}-${process.pid}-${crypto.randomBytes(4).toString('hex')}`;
const temporary = path.join(queueDirectory, `.${name}.tmp`);
// Write then rename, so the host never reads a half-written entry.
fs.writeFileSync(temporary, targetUrl, { mode: 0o600 });
fs.renameSync(temporary, path.join(queueDirectory, `${name}.url`));
console.log('Resume attachment queued for the specified application page.');
