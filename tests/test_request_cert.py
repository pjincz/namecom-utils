import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest


class RequestCertTests(unittest.TestCase):
    def test_arguments_output_and_failures(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            scripts = root / "scripts with 'quote"
            scripts.mkdir()
            script = scripts / 'request-cert'
            shutil.copy2(Path(__file__).resolve().parents[1] / 'request-cert', script)
            hook = scripts / 'certbot-namecom-hook'
            hook.write_text('#!/bin/sh\nexit 0\n')
            hook.chmod(0o755)
            mockbin = root / 'bin'
            mockbin.mkdir()
            certbot = mockbin / 'certbot'
            certbot.write_text('''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
pathlib.Path(os.environ['CALL_LOG']).write_text(json.dumps(sys.argv[1:]))
for flag in ('--manual-auth-hook', '--manual-cleanup-hook'):
    command = sys.argv[sys.argv.index(flag)+1]
    # Reproduce Certbot 2.9's validation before shell execution.
    executable = command.split(None, 1)[0]
    if not os.path.isfile(executable) or not os.access(executable, os.X_OK):
        sys.exit('Hook validation failed: ' + executable)
    subprocess.run(sys.argv[sys.argv.index(flag)+1], shell=True, check=True)
sys.exit(int(os.environ.get('MOCK_EXIT', '0')))
''')
            install = mockbin / 'install'
            install.write_text('''#!/usr/bin/env python3
import os, pathlib, sys
if os.environ.get('FAIL_KEY') and sys.argv[-2].endswith('privkey.pem'):
    sys.exit(1)
p = pathlib.Path(sys.argv[-1])
p.write_text(sys.argv[-2])
p.chmod(int(sys.argv[2], 8))
''')
            for executable in (certbot, install):
                executable.chmod(0o755)
            log = root / 'call.json'
            env = dict(os.environ, PATH=str(mockbin)+os.pathsep+os.environ['PATH'], CALL_LOG=str(log))
            output = root / 'output space'
            config_path = "config with 'quote.ini"
            args = [str(script), 'example.com', '*.example.com', '-o', str(output), '--config', config_path]
            result = subprocess.run(args, env=env, cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            call = json.loads(log.read_text())
            for flag, action in [('--manual-auth-hook', 'auth'), ('--manual-cleanup-hook', 'cleanup')]:
                self.assertEqual(shlex.split(call[call.index(flag)+1]),
                                 ['/usr/bin/env', str(hook), action, '--config', str(root/config_path)])
            self.assertEqual([call[i+1] for i, arg in enumerate(call) if arg == '-d'], ['example.com', '*.example.com'])
            self.assertEqual(call[call.index('--cert-name')+1], 'example.com')
            certbot_dir = Path(os.environ['HOME']) / '.letsencrypt'
            for flag in ('--config-dir', '--work-dir', '--logs-dir'):
                self.assertEqual(call[call.index(flag)+1], str(certbot_dir))
            for filename in ('fullchain.pem', 'privkey.pem'):
                self.assertEqual((output/filename).read_text(),
                                 str(certbot_dir/'live'/'example.com'/filename))
            self.assertEqual(sorted(p.name for p in output.iterdir()), ['fullchain.pem', 'privkey.pem'])
            self.assertEqual((output/'privkey.pem').stat().st_mode & 0o777, 0o600)
            for failure in ({'MOCK_EXIT': '7'}, {'FAIL_KEY': '1'}):
                (output/'fullchain.pem').write_text('old cert')
                (output/'privkey.pem').write_text('old key')
                result = subprocess.run(args, env=dict(env, **failure), cwd=root, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((output/'fullchain.pem').read_text(), 'old cert')
                self.assertEqual((output/'privkey.pem').read_text(), 'old key')
            result = subprocess.run([str(script), '*.example.com'], env=env, cwd=root, capture_output=True)
            self.assertEqual(result.returncode, 0)
            call = json.loads(log.read_text())
            self.assertEqual(shlex.split(call[call.index('--manual-auth-hook')+1])[-1], '/etc/namecom.ini')
            self.assertTrue((root/'fullchain.pem').is_file())
            self.assertTrue((root/'privkey.pem').is_file())
            for invalid in ([], ['example.com', '-o'], ['example.com', '--config'], ['../bad']):
                log.unlink(missing_ok=True)
                result = subprocess.run([str(script)]+invalid, env=env, cwd=root, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(log.exists())


if __name__ == '__main__':
    unittest.main()
