"""One-message native host. Queue metadata never contains résumé bytes."""
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / 'config.json'
QUEUE_PATH = ROOT / 'local-resume-companion-extension' / 'attach-target-url.txt'


def read_target(queue):
    raw = queue.read_text().strip()
    # Existing URL-only queues remain valid in automatic mode.
    if raw.startswith(('https://', 'http://')):
        return {'version': 2, 'requestId': hashlib.sha256(raw.encode()).hexdigest(), 'url': raw}
    target = json.loads(raw)
    if target.get('version') != 2 or not target.get('requestId') or not target.get('url', '').startswith(('https://', 'http://')):
        raise ValueError('Invalid attachment request')
    if 'selector' in target:
        if not isinstance(target['selector'], str) or not target['selector'].strip():
            raise ValueError('Invalid selector')
        if any(type(target.get(k)) is not int or target[k] < 0 for k in ('tabId', 'frameId')):
            raise ValueError('Explicit requests require tab and frame IDs')
    return target


def handle(message, config=CONFIG_PATH, queue=QUEUE_PATH):
    lock = Path(str(queue) + '.lock')
    try:
        lock.mkdir()
    except FileExistsError:
        return {'pending': True, 'error': 'Attachment queue busy'}
    try:
        if not queue.exists():
            return {'pending': True}
        target = read_target(queue)
        if message.get('type') == 'peek-attachment':
            return {'target': target}
        if message.get('type') != 'claim-attachment' or message.get('requestId') != target['requestId']:
            return {'error': 'Attachment request changed; inspect again'}
        if message.get('url') != target['url']:
            return {'error': 'Document URL does not match'}
        if 'selector' in target and any(message.get(k) != target[k] for k in ('tabId', 'frameId')):
            return {'error': 'Tab or frame does not match'}
        resume = Path(json.loads(config.read_text())['approved_resume_path']).expanduser()
        data = resume.read_bytes()
        if not data or len(data) > 700_000:
            return {'error': 'Approved résumé is empty or exceeds native message size limit'}
        reply = {'requestId': target['requestId'], 'fileName': resume.name,
                 'base64': base64.b64encode(data).decode('ascii')}
        queue.unlink()
        return reply
    except (OSError, ValueError, KeyError, TypeError):
        return {'error': 'Could not read the approved résumé or attachment request'}
    finally:
        lock.rmdir()


def main():
    header = sys.stdin.buffer.read(4)
    if len(header) != 4:
        return 1
    length = struct.unpack('=I', header)[0]
    if length > 1024 * 1024:
        return 1
    try:
        message = json.loads(sys.stdin.buffer.read(length))
        reply = handle(message)
    except (ValueError, TypeError):
        reply = {'error': 'Invalid native message'}
    data = json.dumps(reply).encode()
    sys.stdout.buffer.write(struct.pack('=I', len(data)) + data)
    sys.stdout.buffer.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main())
