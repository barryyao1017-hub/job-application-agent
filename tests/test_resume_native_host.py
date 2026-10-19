import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('resume_host', ROOT / 'local-resume-companion-extension/native-host/resume_native_host.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class ResumeHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.resume = self.root / 'approved.docx'
        self.resume.write_bytes(b'approved resume fixture')
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({'approved_resume_path': str(self.resume)}))
        self.queue = self.root / 'queue'
        self.target = dict(version=2, requestId='one', url='https://example.com/apply', tabId=7, frameId=0, selector='#resume')
        self.queue.write_text(json.dumps(self.target))

    def call(self, **message):
        return host.handle(message, self.config, self.queue)

    def claim(self, **changes):
        message = dict(type='claim-attachment', requestId='one', url=self.target['url'], tabId=7, frameId=0)
        message.update(changes)
        return self.call(**message)

    def test_peek_returns_target_without_file_bytes(self):
        result = self.call(type='peek-attachment')
        self.assertEqual(result, {'target': self.target})
        self.assertTrue(self.queue.exists())

    def test_claim_is_exact_and_one_use(self):
        for changes in ({'tabId': 8}, {'frameId': 1}, {'url': self.target['url'] + '/other'}, {'requestId': 'old'}):
            self.assertIn('error', self.claim(**changes))
            self.assertTrue(self.queue.exists())
        result = self.claim()
        self.assertEqual(result['fileName'], 'approved.docx')
        self.assertEqual(host.base64.b64decode(result['base64']), self.resume.read_bytes())
        self.assertFalse(self.queue.exists())
        self.assertNotIn('base64', self.claim())

    def test_unreadable_file_keeps_request_for_retry(self):
        self.resume.unlink()
        self.assertIn('error', self.claim())
        self.assertTrue(self.queue.exists())

    def test_legacy_url_queue(self):
        self.queue.write_text(self.target['url'])
        target = self.call(type='peek-attachment')['target']
        self.assertNotIn('selector', target)
        self.assertIn('base64', self.claim(requestId=target['requestId']))

    def test_busy_queue_does_not_disclose_file(self):
        Path(str(self.queue) + '.lock').mkdir()
        self.assertNotIn('base64', self.claim())
        self.assertTrue(self.queue.exists())

    def test_malformed_request_does_not_consume(self):
        self.queue.write_text('{bad json')
        self.assertIn('error', self.claim())
        self.assertTrue(self.queue.exists())


if __name__ == '__main__':
    unittest.main()
