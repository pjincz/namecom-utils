import io
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch
from urllib.error import HTTPError


HOOK = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'certbot-namecom-hook'))


class HookTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = Path(self.directory.name) / 'namecom.ini'
        self.config.write_text('[aaa.com]\nusername=a\ntoken=a%key\n'
                               '[sub.aaa.com]\nusername=b\ntoken=bkey\n')

    def invoke(self, args, env, responses):
        replies = [r if isinstance(r, Exception) else io.StringIO(json.dumps(r))
                   for r in responses]
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, env, clear=True), \
                patch('urllib.request.urlopen', side_effect=replies) as api, \
                patch('time.sleep') as sleep, redirect_stdout(out), redirect_stderr(err):
            code = HOOK['main'](['--config', str(self.config)] + args)
        return code, out.getvalue(), err.getvalue(), api, sleep

    def test_auth_is_silent(self):
        env = {'CERTBOT_IDENTIFIER': 'AAA.COM.', 'CERTBOT_VALIDATION': 'challenge-1'}
        code, out, err, api, sleep = self.invoke(['auth'], env, [{'id': 123}])
        self.assertEqual((code, out, err), (0, '', ''))
        request = api.call_args.args[0]
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(json.loads(request.data), {'host': '_acme-challenge',
                         'type': 'TXT', 'answer': 'challenge-1', 'ttl': 300})
        sleep.assert_called_once_with(25)

    def test_cleanup_all_matching_txt_across_pages(self):
        env = {'CERTBOT_DOMAIN': 'aaa.com'}
        def record(i, host='_acme-challenge', kind='TXT'):
            return dict(id=i, host=host, type=kind)
        replies = [
            {'records': [record(1), record(2, '_acme-challenge.other'),
                         record(3, kind='CNAME')], 'nextPage': 2},
            {'records': [record(4), dict(id=5, fqdn='_ACME-CHALLENGE.AAA.COM.', type='TXT')]},
            {}, HTTPError('url', 404, 'Missing', {}, None), {},
        ]
        code, out, err, api, sleep = self.invoke(['cleanup'], env, replies)
        self.assertEqual((code, out, err), (0, '', ''))
        calls = [call.args[0] for call in api.call_args_list]
        self.assertEqual([r.get_method() for r in calls], ['GET', 'GET', 'DELETE', 'DELETE', 'DELETE'])
        self.assertIn('page=2', calls[1].full_url)
        self.assertEqual([r.full_url.rsplit('/', 1)[-1] for r in calls[2:]], ['1', '4', '5'])
        sleep.assert_not_called()
        code, out, err, api, _ = self.invoke(['cleanup'], env, [{}])
        self.assertEqual((code, out, err), (0, '', ''))
        api.assert_called_once()

    def test_wildcard_legacy_variables_and_longest_zone(self):
        env = {'CERTBOT_DOMAIN': '*.SUB.AAA.COM.', 'CERTBOT_VALIDATION': 'challenge-2'}
        code, out, err, api, sleep = self.invoke(['auth', '--wait', '0'], env, [{'id': 456}])
        self.assertEqual(code, 0)
        self.assertEqual((out, err), ('', ''))
        self.assertIn('/sub.aaa.com/records', api.call_args.args[0].full_url)
        self.assertEqual(api.call_args.args[0].get_header('Authorization'), 'Basic Yjpia2V5')
        sleep.assert_not_called()
        _, _, _, _, sleep = self.invoke(['auth', '--wait', '60'], env, [{'id': 457}])
        sleep.assert_called_once_with(60)

    def test_cleanup_errors(self):
        code, out, err, api, _ = self.invoke(['cleanup'], {}, [])
        self.assertEqual((code, out), (1, ''))
        api.assert_not_called()
        for reply in [{'records': None}, {'records': [{'id': None, 'host': '_acme-challenge', 'type': 'TXT'}]}, TimeoutError()]:
            code, out, err, api, _ = self.invoke(['cleanup'], {'CERTBOT_DOMAIN': 'aaa.com'}, [reply])
            self.assertEqual((code, out), (1, ''))
            self.assertTrue(err)
            api.assert_called_once()
        code, out, err, api, _ = self.invoke(['cleanup'], {'CERTBOT_DOMAIN': 'aaa.com'}, [
            {'records': [{'id': 1, 'host': '_acme-challenge', 'type': 'TXT'}]},
            HTTPError('url', 403, 'Forbidden', {}, None)])
        self.assertEqual((code, out), (1, ''))
        self.assertEqual(api.call_count, 2)

    def test_failures_do_not_retry_or_wait(self):
        env = {'CERTBOT_IDENTIFIER': 'aaa.com', 'CERTBOT_VALIDATION': 'value'}
        for reply in [TimeoutError(), HTTPError('url', 403, 'Forbidden', {}, None), {}]:
            code, out, err, api, sleep = self.invoke(['auth'], env, [reply])
            self.assertEqual((code, out), (1, ''))
            self.assertTrue(err.startswith('certbot-namecom-hook:'))
            api.assert_called_once()
            sleep.assert_not_called()
        for env in [{}, {'CERTBOT_DOMAIN': 'aaa.com'},
                    {'CERTBOT_DOMAIN': 'notaaa.com', 'CERTBOT_VALIDATION': 'value'}]:
            code, out, err, api, sleep = self.invoke(['auth'], env, [])
            self.assertEqual((code, out), (1, ''))
            api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
