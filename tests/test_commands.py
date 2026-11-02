import hashlib
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
        self.config = self.home / '.config' / 'megaproxy-tools'
        self.config.mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.home), NO_PROXY='internal.example')
        self.env.pop('no_proxy', None)
        self.env.pop('XDG_CONFIG_HOME', None)
        self.env.pop('XDG_STATE_HOME', None)

    def run_command(self, name, *args):
        return subprocess.run([sys.executable, str(BIN / name), *args], env=self.env,
                              text=True, capture_output=True)

    def configure(self, text):
        (self.config / 'config.json').unlink(missing_ok=True)
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

    def test_default_env(self):
        self.configure('https://host.example:443')
        defaults = self.config / 'default.env'
        defaults.write_text('# comment\n\nGODEBUG=http2client=0\nEMPTY=\nLITERAL=$(no-execution)=value\nhttp_proxy=http://wrong:80\n')
        env = self.probe('proxy487')
        self.assertEqual(env['GODEBUG'], 'http2client=0')
        self.assertEqual(env['EMPTY'], '')
        self.assertEqual(env['LITERAL'], '$(no-execution)=value')
        self.assertEqual(env['http_proxy'], 'https://host.example:443')
        self.env['GODEBUG'] = 'existing'
        self.assertEqual(self.probe('proxy487')['GODEBUG'], 'existing')
        self.assertNotIn('LITERAL', self.probe('noproxy487'))
        defaults.write_text('BAD-NAME=secret\n')
        result = self.run_command('proxy487', 'true')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('line 1', result.stderr)
        self.assertNotIn('secret', result.stderr)

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
        self.config.rmdir()
        self.assertEqual(self.run_command('proxy487', '--init').returncode, 0)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o700)
        self.configure('https://host.example:443\n')
        self.assertEqual(self.run_command('proxy487', '--init').returncode, 0)
        target = self.config / 'config.json'
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        before = target.read_bytes()
        self.run_command('proxy487', '--init')
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual((self.config / 'proxy-list.txt').read_text(), 'https://host.example:443\n')

    def test_xdg_and_legacy_selection(self):
        self.configure('https://new.example:443')
        legacy = self.home / '.proxy487'
        legacy.mkdir()
        (legacy / 'proxy-list.txt').write_text('https://legacy.example:443')
        (legacy / 'default.env').write_text('LEGACY_ONLY=yes')
        self.assertEqual(self.probe('proxy487')['https_proxy'], 'https://new.example:443')
        self.assertNotIn('LEGACY_ONLY', self.probe('proxy487'))
        for value in ('', 'relative/path'):
            self.env['XDG_CONFIG_HOME'] = value
            self.assertEqual(self.probe('proxy487')['https_proxy'], 'https://new.example:443')
        custom = self.home / 'custom-config'
        self.env['XDG_CONFIG_HOME'] = str(custom)
        self.assertEqual(self.probe('proxy487')['https_proxy'], 'https://legacy.example:443')
        self.run_command('proxy487', '--init')
        self.assertFalse(custom.exists())
        legacy.rename(self.home / 'legacy-backup')
        self.assertEqual(self.run_command('proxy487', '--init').returncode, 0)
        target = custom / 'megaproxy-tools'
        self.assertEqual(target.stat().st_mode & 0o777, 0o700)
        self.assertFalse((target / 'config.json').exists())
        self.assertNotEqual(self.run_command('proxy487', 'true').returncode, 0)

    def test_control_list_choose_and_init(self):
        self.assertEqual(self.run_command('proxy487ctl', 'init').returncode, 0)
        self.configure('https://user:secret@first.example:443\nsocks5://second.example:1080\n')
        result = self.run_command('proxy487ctl', 'list')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('* 1 HTTPS://first.example:443', result.stdout)
        self.assertNotIn('user', result.stdout)
        self.assertNotIn('secret', result.stdout)
        for value in ('2', 'second.example'):
            result = self.run_command('proxy487ctl', 'choose', value)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.probe('proxy487')['https_proxy'], 'socks5h://second.example:1080')
        chosen = self.config / 'config.json'
        self.assertEqual(chosen.stat().st_mode & 0o777, 0o600)
        for value in ('0', '3', 'unknown', 'https://user:secret@host:443'):
            result = self.run_command('proxy487ctl', 'choose', value)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('secret', result.stderr)
            self.assertEqual(json.loads(chosen.read_text())['activeProfileId'], json.loads(chosen.read_text())['profiles'][1]['id'])
        result = subprocess.run([sys.executable, str(BIN / 'proxy487ctl'), 'choose'],
                                input='1\n', env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(chosen.read_text())['activeProfileId'], json.loads(chosen.read_text())['profiles'][0]['id'])
        self.configure('https://first.example:443\nhttps://first.example:8443')
        self.assertEqual(self.run_command('proxy487ctl', 'choose', '2').returncode, 0)
        self.assertNotEqual(self.run_command('proxy487ctl', 'choose', 'first.example').returncode, 0)
        self.assertEqual(json.loads(chosen.read_text())['activeProfileId'], json.loads(chosen.read_text())['profiles'][1]['id'])
        for args in (('unknown',), ('list', 'extra'), ('choose', '1', 'extra')):
            self.assertNotEqual(self.run_command('proxy487ctl', *args).returncode, 0)

    def import_text(self, data):
        text = data if isinstance(data, str) else json.dumps(data)
        return subprocess.run([sys.executable, str(BIN / 'proxy487ctl'), 'import', '-'],
                              input=text, env=self.env, text=True, capture_output=True)

    def portable(self, *profiles, active=None):
        return {'schema': 'net.megaproxy487.config', 'version': 8,
                'profiles': list(profiles), 'activeProfileId': active}

    def profile(self, identifier, **proxy):
        return {'id': identifier, 'proxy': dict(type='HTTPS', host='proxy.example', port=443, **proxy)}

    def test_import_formats_and_percent_encoding(self):
        formats = [
            'https://u%2Bser:p%40ss%3Aword@proxy.example?title=Test&cc=gb',
            '# superproxy:proxylist:v1\nhttps://u%2Bser:p%40ss%3Aword@proxy.example?title=Test&cc=gb',
            {'data': [{'type': 'ssl', 'hostname': 'proxy.example', 'port': '443',
                       'username': 'u+ser', 'password': 'p@ss:word', 'title': 'Test', 'cc': 'GB'}]},
            [{'proxyType': 'https', 'address': 'proxy.example', 'port': 443,
              'username': 'u+ser', 'password': 'p@ss:word', 'name': 'Test', 'countryCode': 'GB'}],
            {'profiles': [{'name': 'Test', 'countryCode': 'GB', 'proxy': {'type': 'HTTPS',
                          'host': 'proxy.example', 'port': 443, 'username': 'u+ser', 'password': 'p@ss:word'}}]},
            {'schemaVersion': 2, '+Test': {'profileType': 'FixedProfile', 'name': 'Test',
                'fallbackProxy': {'scheme': 'https', 'host': 'proxy.example', 'port': 443},
                'auth': {'all': {'username': 'u+ser', 'password': 'p@ss:word'}}}},
        ]
        for data in formats:
            with self.subTest(data=data):
                (self.config / 'config.json').unlink(missing_ok=True)
                result = self.import_text(data)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('p@ss', result.stdout + result.stderr)
                config = json.loads((self.config / 'config.json').read_text())
                self.assertEqual(len(config['profiles']), 1)
                profile = config['profiles'][0]
                self.assertEqual(profile['name'], 'Test')
                self.assertEqual(profile['proxy']['password'], 'p@ss:word')
                self.assertEqual(self.probe('proxy487')['https_proxy'], 'https://u%2Bser:p%40ss%3Aword@proxy.example:443')
        # Imports without stable IDs create new profiles rather than overwriting unrelated ones.
        self.assertEqual(self.import_text(formats[0]).returncode, 0)
        self.assertEqual(len(json.loads((self.config / 'config.json').read_text())['profiles']), 2)

    def test_portable_merge_selection_order_and_secrets(self):
        a = self.profile('a', username='u', password='secret')
        b = self.profile('b', username='u', password='other')
        self.assertEqual(self.import_text(self.portable(a, b, active='b')).returncode, 0)
        incoming = self.portable(self.profile('b', username='u'), self.profile('c'), active='c')
        incoming['routing'] = {'bypassLocalNetworks': False}
        result = self.import_text(incoming)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.config / 'config.json'
        config = json.loads(path.read_text())
        self.assertEqual([p['id'] for p in config['profiles']], ['a', 'b', 'c'])
        self.assertEqual(config['activeProfileId'], 'b')
        self.assertEqual(config['profiles'][1]['proxy']['password'], 'other')
        self.assertFalse(config['routing']['bypassLocalNetworks'])
        self.assertEqual(self.import_text(incoming).returncode, 0)
        self.assertEqual(len(json.loads(path.read_text())['profiles']), 3)
        self.assertEqual(self.import_text(self.portable(self.profile('b', username='u', password=''))).returncode, 0)
        self.assertEqual(json.loads(path.read_text())['profiles'][1]['proxy']['password'], '')
        for key, value in (('host', 'different.example'), ('port', 8443), ('username', 'other'), ('type', 'SOCKS5')):
            self.assertEqual(self.import_text(self.portable(a)).returncode, 0)
            changed = self.profile('a', username='u')
            changed['proxy'][key] = value
            self.assertEqual(self.import_text(self.portable(changed)).returncode, 0)
            self.assertNotIn('password', json.loads(path.read_text())['profiles'][0]['proxy'])
        self.env.pop('NO_PROXY', None)
        # Restore a usable selected HTTPS profile, without resetting root routing preferences.
        self.assertEqual(self.import_text(self.portable(b)).returncode, 0)
        self.assertEqual(self.probe('proxy487')['no_proxy'], '')

    def test_import_preserves_implicit_first_selection(self):
        self.assertEqual(self.import_text(self.portable(self.profile('a'))).returncode, 0)
        self.assertEqual(self.import_text(self.portable(self.profile('b'), active='b')).returncode, 0)
        config = json.loads((self.config / 'config.json').read_text())
        self.assertEqual(config['activeProfileId'], 'a')

    def test_invalid_import_preserves_config_and_hides_secrets(self):
        valid = self.portable(self.profile('a', username='u', password='secret'))
        self.assertEqual(self.import_text(valid).returncode, 0)
        path = self.config / 'config.json'
        original = path.read_bytes()
        invalid = [
            '{"password":"secret",', 'https://u:secret@host:bad',
            'https://u:secret@host?title=%XX', 'secret' * (1024 * 1024 // 6 + 1),
            self.portable(self.profile('a'), self.profile('a')),
            self.portable(self.profile('a'), active='missing'),
            self.portable(self.profile('a', password='secret\n')),
            self.portable({'id': 'a', 'proxy': {'type': 'HTTPS', 'host': 'host', 'port': True}}),
            self.portable({'id': 'a', 'proxy': {'type': 'HTTPS_JUMP', 'host': 'host', 'port': 443}}),
            {'schema': 'other', 'version': 8, 'profiles': [self.profile('a')]},
            {'schema': 'dev.megaproxy.config', 'version': 1, 'profiles': [{'proxy': {'type': []}}]},
            self.portable({'id': 'a', 'proxy': {'type': 'MASQUE', 'host': 'host', 'port': 443}}),
        ]
        for data in invalid:
            with self.subTest(data=str(data)[:80]):
                result = self.import_text(data)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('secret', result.stdout + result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(path.read_bytes(), original)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_unsupported_profiles_and_platform_settings_warn(self):
        data = self.portable(self.profile('a'), {'id': 'masque', 'proxy': {
            'type': 'MASQUE', 'host': 'host', 'port': 443}}, {'id': 'insecure', 'proxy': {
            'type': 'HTTPS', 'host': 'host', 'port': 443, 'allowInvalidProxyCertificate': True}})
        data['tls'] = {'fingerprint': 'CUSTOM', 'customJa3': 'example'}
        data['browser'] = {'theme': 'dark'}
        data['profiles'][0]['dns'] = {'provider': 'CLOUDFLARE'}
        result = self.import_text(data)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Skipped 2', result.stderr)
        self.assertIn('discarded', result.stderr)
        config = json.loads((self.config / 'config.json').read_text())
        self.assertEqual(len(config['profiles']), 1)
        self.assertNotIn('tls', config)
        self.assertNotIn('dns', config['profiles'][0])
        result = self.import_text('http://u:secret@host:80\nhttps://u:secret@host:443')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Skipped 1', result.stderr)

    def test_file_import_legacy_versions_and_ipv6_socks(self):
        file = self.home / 'input.json'
        for version in range(1, 9):
            data = self.portable(self.profile('legacy'))
            data['schema'] = 'dev.megaproxy.config'
            data['version'] = version
            if version < 7:
                del data['profiles'][0]['id']
                del data['profiles'][0]['proxy']['port']
            file.write_text(json.dumps(data))
            result = self.run_command('proxy487ctl', 'import', str(file))
            self.assertEqual(result.returncode, 0, result.stderr)
        result = self.import_text('socks5://u%3Aname:p%2Bss@[2001:db8::1]?title=IPv6')
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads((self.config / 'config.json').read_text())
        identifier = config['profiles'][-1]['id']
        self.assertEqual(self.run_command('proxy487ctl', 'choose', identifier).returncode, 0)
        self.assertEqual(self.probe('proxy487')['https_proxy'], 'socks5h://u%3Aname:p%2Bss@[2001:db8::1]:1080')

    def test_pinned_schema_integrity_and_optional_fields(self):
        folder = BIN.parent / 'lib/megaproxy-tools/config-schema'
        lock = json.loads((folder / 'schema-lock.json').read_text())
        self.assertEqual(len(lock['commit']), 40)
        for name, digest in lock['files'].items():
            self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), digest)
        for field, value in (('routing', {'bypassLocalNetworks': 'false'}),
                             ('tls', {'fingerprint': 'invalid'}),
                             ('subscription', {'url': 'http://example.com'}),
                             ('browser', {'theme': 42})):
            data = self.portable(self.profile('a'))
            data[field] = value
            result = self.import_text(data)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.config / 'config.json').exists())

    def test_usage_missing_config_exit_and_arguments(self):
        for name in ('proxy487', 'noproxy487', 'proxy487ctl'):
            self.assertEqual(self.run_command(name).returncode, 2)
            self.assertEqual(self.run_command(name, '--help').returncode, 0)
        self.assertNotEqual(self.run_command('proxy487', 'true').returncode, 0)
        self.configure('https://localhost:8080')
        result = self.run_command('proxy487', '--', sys.executable, '-c',
                                  'import sys; assert sys.argv[1] == "a b"; sys.exit(23)', 'a b')
        self.assertEqual(result.returncode, 23)
        self.assertNotEqual(self.run_command('proxy487', '/nonexistent/command').returncode, 0)


if __name__ == '__main__':
    unittest.main()
