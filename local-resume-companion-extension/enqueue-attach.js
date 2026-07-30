#!/usr/local/bin/node
import fs from 'node:fs';
const targetUrl = process.argv[2];
if (!/^https?:\/\//.test(targetUrl || '')) throw new Error('Provide the exact application URL.');
fs.writeFileSync('/Users/jiayiyao/Documents/Codex/2026-07-29/realtime-voice-chat-2/outputs/local-resume-companion-extension/attach-target-url.txt', targetUrl, { mode: 0o600 });
console.log('Resume attachment queued for the specified application page.');
