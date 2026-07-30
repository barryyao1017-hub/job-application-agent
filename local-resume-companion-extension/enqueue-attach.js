#!/usr/local/bin/node
import fs from 'node:fs';
import path from 'node:path';
const targetUrl = process.argv[2];
if (!/^https?:\/\//.test(targetUrl || '')) throw new Error('Provide the exact application URL.');
const extensionDirectory = path.dirname(new URL(import.meta.url).pathname);
fs.writeFileSync(path.join(extensionDirectory, 'attach-target-url.txt'), targetUrl, { mode: 0o600 });
console.log('Resume attachment queued for the specified application page.');
