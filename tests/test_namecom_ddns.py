import io
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

DDNS = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'namecom-ddns'))


class DDNSTests(unittest.TestCase):
    def invoke(self, replies, ips, once=True, extra=()):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.ini'
            config.write_text('[aaa.com]\nusername=user\ntoken=key\n')
            responses = [r if isinstance(r, Exception) else io.StringIO(json.dumps(r)) for r in replies]
            curl_results = [subprocess.CompletedProcess([], 0, ip, '') for ip in ips]
            out, err = io.StringIO(), io.StringIO()
            with patch('urllib.request.urlopen', side_effect=responses) as api, \
                    patch('subprocess.run', side_effect=curl_results) as curl, \
                    patch('time.sleep', side_effect=[None] * (len(ips)-1) + [KeyboardInterrupt()]) as sleep, \
                    redirect_stdout(out), redirect_stderr(err):
                args = ['--config', str(config), 'x.aaa.com'] + (['--once'] if once else [])
                code = DDNS['main'](args + list(extra))
            return code, out.getvalue(), err.getvalue(), api, curl, sleep

    @staticmethod
    def record(i=1, value='1.2.3.4'):
        return dict(id=i, host='x', type='A', answer=value, ttl=600)

    def test_create_and_update(self):
        for initial, method, ttl in [({}, 'POST', 300), ({'records': [self.record()]}, 'PUT', 600)]:
            code, out, err, api, curl, sleep = self.invoke([initial, {}], ['5.6.7.8'])
            self.assertEqual((code, out), (0, ''))
            request = api.call_args.args[0]
            self.assertEqual(request.get_method(), method)
            self.assertEqual(json.loads(request.data), dict(host='x', type='A', answer='5.6.7.8', ttl=ttl))
            self.assertIn('-4', curl.call_args.args[0])
            self.assertIn('https://api.ip.sb/ip', curl.call_args.args[0])
            sleep.assert_not_called()

    def test_duplicates_removed_even_if_first_matches(self):
        record = self.record()
        code, _, _, api, _, _ = self.invoke([
            {'records': [record, self.record(2)]}, {}, {'records': [record]},
        ], ['1.2.3.4'])
        self.assertEqual(code, 0)
        self.assertEqual([c.args[0].get_method() for c in api.call_args_list], ['GET', 'DELETE', 'GET'])

    def test_loop_caches_success_and_sleeps(self):
        code, _, _, api, curl, sleep = self.invoke([
            {'records': [self.record()]}, {'records': [self.record()]}, {},
        ], ['1.2.3.4', '5.6.7.8', '5.6.7.8'], once=False)
        self.assertEqual(code, 130)
        self.assertEqual(api.call_count, 3)
        self.assertEqual(curl.call_count, 3)
        self.assertEqual([c.args for c in sleep.call_args_list], [(60,), (60,), (60,)])

    def test_failed_update_requeries_next_iteration(self):
        code, _, err, api, _, _ = self.invoke([
            {}, TimeoutError(), {}, {},
        ], ['1.2.3.4', '1.2.3.4'], once=False)
        self.assertEqual(code, 130)
        self.assertIn('namecom-ddns:', err)
        self.assertEqual([c.args[0].get_method() for c in api.call_args_list], ['GET', 'POST', 'GET', 'POST'])

    def test_reflection_services(self):
        for option in ('-R', '--reflect'):
            for service, body, url in [
                ('ifconfig.co', '5.6.7.8\n', 'https://ifconfig.co/ip'),
                ('ipify.org', '5.6.7.8', 'https://api.ipify.org'),
                ('ip.sb', '5.6.7.8\n', 'https://api.ip.sb/ip'),
                ('cip.cc', 'IP\t: 5.6.7.8\n地址\t: test\nURL\t: http://www.cip.cc/5.6.7.8\n', 'https://www.cip.cc'),
            ]:
                code, _, _, api, curl, _ = self.invoke([{}, {}], [body], extra=[option, service])
                self.assertEqual(code, 0)
                self.assertEqual(curl.call_args.args[0][-1], url)
                if service == 'ip.sb':
                    args = curl.call_args.args[0]
                    self.assertEqual(args[args.index('--user-agent') + 1], 'namecom-ddns')
                self.assertEqual(json.loads(api.call_args.args[0].data)['answer'], '5.6.7.8')

    def test_invalid_cip_response_does_not_write(self):
        for body in ['URL: http://www.cip.cc/1.2.3.4', 'IP : ::1', '<html>1.2.3.4</html>']:
            code, _, err, api, _, _ = self.invoke([{}], [body], extra=['-R', 'cip.cc'])
            self.assertEqual(code, 1)
            self.assertIn('cip.cc did not return a valid IPv4', err)
            api.assert_called_once()

    def test_interface_filters_and_preserves_order(self):
        addresses = [
            dict(family='inet', local='169.254.1.2', scope='link'),
            dict(family='inet', local='169.254.2.3', scope='global'),
            dict(family='inet', local='10.0.0.1', tentative=True),
            dict(family='inet', local='10.0.0.2', temporary=True),
            dict(family='inet', local='10.0.0.3', deprecated=True),
            dict(family='inet', local='10.0.0.4', dadfailed=True),
            dict(family='inet', local='10.0.0.5', preferred_life_time=0),
            dict(family='inet6', local='2001:db8::1'),
            dict(family='inet', local='192.168.1.9', secondary=True),
            dict(family='inet', local='192.168.1.8'),
        ]
        for option in ('-I', '--interface'):
            code, _, _, api, command, _ = self.invoke([{}, {}],
                [json.dumps([{'addr_info': addresses}])], extra=[option, 'eth0'])
            self.assertEqual(code, 0)
            command.assert_called_once()
            self.assertEqual(command.call_args.args[0], ['ip', '-j', '-4', 'address', 'show', 'dev', 'eth0'])
            self.assertEqual(json.loads(api.call_args.args[0].data)['answer'], '192.168.1.9')

    def test_interface_missing_addresses_or_invalid_data(self):
        for body in ('[]', '[{"addr_info": []}]', 'invalid', '{}'):
            code, _, err, api, _, _ = self.invoke([{}], [body], extra=['-I', 'eth0'])
            self.assertEqual(code, 1)
            self.assertIn('interface eth0', err)
            api.assert_called_once()
        for failure in (FileNotFoundError(), subprocess.TimeoutExpired('ip', 10)):
            with patch('subprocess.run', side_effect=failure):
                with self.assertRaises(DDNS['Error']):
                    DDNS['get_interface_ip']('eth0')

    def test_sources_are_mutually_exclusive(self):
        with redirect_stderr(io.StringIO()), patch('subprocess.run') as command:
            with self.assertRaises(SystemExit) as error:
                DDNS['main'](['x.aaa.com', '-I', 'eth0', '-R', 'ifconfig.co'])
            self.assertEqual(error.exception.code, 2)
            command.assert_not_called()

    def test_ipv6_reflection_creates_aaaa(self):
        for service, url, body in [
            ('ifconfig.co', 'https://ifconfig.co/ip', '2001:db8::9'),
            ('ipify.org', 'https://api6.ipify.org', '2001:db8::9'),
            ('ip.sb', 'https://api.ip.sb/ip', '2001:db8::9'),
            ('cip.cc', 'https://www.cip.cc', 'IP : 2001:db8::9'),
        ]:
            code, _, _, api, command, _ = self.invoke([{}, {}], [body],
                extra=['-6', '-R', service])
            self.assertEqual(code, 0)
            self.assertIn('-6', command.call_args.args[0])
            self.assertEqual(command.call_args.args[0][-1], url)
            self.assertEqual(json.loads(api.call_args.args[0].data),
                             dict(host='x', type='AAAA', answer='2001:db8::9', ttl=300))

    def test_ipv6_interface_filters_and_keeps_ula(self):
        addresses = [dict(family='inet6', local='fe80::1', scope='link')]
        for flag in ('temporary', 'tentative', 'deprecated', 'dadfailed'):
            addresses.append(dict(family='inet6', local='2001:db8::1', **{flag: True}))
        addresses += [dict(family='inet', local='192.168.1.1'),
                      dict(family='inet6', local='fd00::1', mngtmpaddr=True),
                      dict(family='inet6', local='2001:db8::2')]
        code, _, _, api, command, _ = self.invoke([{}, {}],
            [json.dumps([{'addr_info': addresses}])], extra=['--ipv6', '-I', 'eth0'])
        self.assertEqual(code, 0)
        self.assertIn('-6', command.call_args.args[0])
        self.assertEqual(json.loads(api.call_args.args[0].data)['answer'], 'fd00::1')

    def test_ipv6_equivalent_notations_skip_update(self):
        record = dict(id=1, host='x', type='AAAA', answer='2001:0DB8:0:0:0:0:0:1', ttl=600)
        code, _, err, api, _, _ = self.invoke([{'records': [record, self.record()]}],
                                             ['2001:db8::1'], extra=['-6'])
        self.assertEqual(code, 0)
        self.assertIn('Record matches, skipped: AAAA', err)
        api.assert_called_once()

    def test_ipv6_duplicates_and_update_preserve_a(self):
        first = dict(id=1, host='x', type='AAAA', answer='2001:db8::1', ttl=600)
        second = dict(first, id=2)
        code, _, _, api, _, _ = self.invoke([
            {'records': [self.record(3), first, second]}, {},
            {'records': [self.record(3), first]}, {},
        ], ['2001:db8::9'], extra=['-6'])
        self.assertEqual(code, 0)
        calls = [c.args[0] for c in api.call_args_list]
        self.assertEqual([c.get_method() for c in calls], ['GET', 'DELETE', 'GET', 'PUT'])
        self.assertTrue(calls[1].full_url.endswith('/2'))
        self.assertTrue(calls[-1].full_url.endswith('/1'))
        self.assertEqual(json.loads(calls[-1].data)['ttl'], 600)

    def test_ipv6_rejects_ipv4_and_scoped_output(self):
        for body in ('1.2.3.4', 'fe80::1%eth0'):
            code, _, err, api, _, _ = self.invoke([{}], [body], extra=['-6'])
            self.assertEqual(code, 1)
            self.assertIn('valid IPv6', err)
            api.assert_called_once()
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                DDNS['main'](['x.aaa.com', '-4', '-6'])
            self.assertEqual(error.exception.code, 2)

    def test_invalid_reflection_does_not_write(self):
        for ip in ['::1', '<html>error</html>', '']:
            code, out, err, api, _, _ = self.invoke([{}], [ip])
            self.assertEqual((code, out), (1, ''))
            self.assertIn('valid IPv4', err)
            api.assert_called_once()


if __name__ == '__main__':
    unittest.main()
