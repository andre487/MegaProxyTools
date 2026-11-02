import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BIN = Path(__file__).resolve().parents[1] / 'bin'
KEYS = ('http_proxy', 'https_proxy', 'all_proxy', 'ws_proxy', 'wss_proxy')


class Commands(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.home / '.proxy487'
        self.config.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), NO_PROXY='internal.example')
        self.env.pop('no_proxy', None)

    def run_command(self, name, *args):
        return subprocess.run([sys.executable, str(BIN / name), *args], env=self.env,
                              text=True, capture_output=True)

    def configure(self, text):
        (self.config / 'proxy-list.txt').write_text(text)

    def probe(self, name):
        result = self.run_command(name, sys.executable, '-c', 'import os,json; print(json.dumps(dict(os.environ)))')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_selection_environment_and_metadata(self):
        self.configure('# comment\n\nhttps://first.example:443\nhttps://user:p%40ss@second.example:443?name=second#label\n')
        (self.config / 'chosen').write_text('second.example\n')
        env = self.probe('proxy487')
        for key in KEYS:
            self.assertEqual(env[key], 'https://user:p%40ss@second.example:443')
            self.assertEqual(env[key.upper()], env[key])
        self.assertEqual(env['no_proxy'], 'internal.example')

    def test_clear_all_variants(self):
        for key in (*KEYS, 'no_proxy'):
            self.env[key] = self.env[key.upper()] = 'sentinel'
        env = self.probe('noproxy487')
        self.assertFalse(any(k.lower() in (*KEYS, 'no_proxy') for k in env))

    def test_errors_and_no_secret_disclosure(self):
        for text in ('', '# comment\n', 'https://user:secret@host:bad', 'file:///secret'):
            with self.subTest(text=text):
                self.configure(text)
                result = self.run_command('proxy487', 'true')
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('secret', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
        self.configure('https://host.example:443')
        (self.config / 'chosen').write_text('absent.example')
        self.assertNotEqual(self.run_command('proxy487', 'true').returncode, 0)

    def test_init_is_private_and_preserves_config(self):
        self.assertEqual(self.run_command('proxy487', '--init').returncode, 0)
        target = self.config / 'proxy-list.txt'
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.configure('https://host.example:443\n')
        self.run_command('proxy487', '--init')
        self.assertEqual(target.read_text(), 'https://host.example:443\n')

    def test_usage_missing_config_exit_and_arguments(self):
        for name in ('proxy487', 'noproxy487'):
            self.assertEqual(self.run_command(name).returncode, 2)
            self.assertEqual(self.run_command(name, '--help').returncode, 0)
        self.assertNotEqual(self.run_command('proxy487', 'true').returncode, 0)
        self.configure('http://localhost:8080')
        result = self.run_command('proxy487', '--', sys.executable, '-c',
                                  'import sys; assert sys.argv[1] == "a b"; sys.exit(23)', 'a b')
        self.assertEqual(result.returncode, 23)
        self.assertNotEqual(self.run_command('proxy487', '/nonexistent/command').returncode, 0)


if __name__ == '__main__':
    unittest.main()
