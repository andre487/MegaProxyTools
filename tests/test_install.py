import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Installation(unittest.TestCase):
    def test_checkout_and_piped_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            archive = folder / 'source.tar.gz'
            with tarfile.open(archive, 'w:gz') as stream:
                for name in ('install.sh', 'bin', 'lib'):
                    stream.add(ROOT / name, arcname='MegaProxyTools-example/' + name,
                               filter=lambda info: None if '__pycache__' in info.name else info)
            fake_bin = folder / 'fake-bin'
            fake_bin.mkdir()
            curl = fake_bin / 'curl'
            curl.write_text(f'#!{sys.executable}\n' + '''import os
import shutil
import sys
from pathlib import Path
if os.environ.get('FAIL_DOWNLOAD'):
    sys.exit(22)
Path(os.environ['CURL_LOG']).write_text('\\n'.join(sys.argv[1:]))
shutil.copyfile(os.environ['TEST_ARCHIVE'], sys.argv[sys.argv.index('-o') + 1])
''')
            curl.chmod(0o755)
            env = dict(os.environ, HOME=str(folder), TMPDIR=str(folder),
                       PATH=str(fake_bin) + os.pathsep + os.environ['PATH'],
                       TEST_ARCHIVE=str(archive), CURL_LOG=str(folder / 'curl.log'))
            for mode in ('checkout', 'pipe', 'download-fails', 'bad-archive'):
                prefix = folder / mode
                run_env = dict(env, PREFIX=str(prefix), MEGAPROXY_TOOLS_REF='work/proxy-tools')
                if mode == 'checkout':
                    result = subprocess.run(['sh', str(ROOT / 'install.sh')], cwd=folder,
                                            env=run_env, text=True, capture_output=True)
                    self.assertFalse((folder / 'curl.log').exists())
                else:
                    if mode == 'download-fails':
                        run_env['FAIL_DOWNLOAD'] = '1'
                    if mode == 'bad-archive':
                        broken = folder / 'broken.tar.gz'
                        broken.write_text('not an archive')
                        run_env['TEST_ARCHIVE'] = str(broken)
                    result = subprocess.run(['bash'], input=(ROOT / 'install.sh').read_text(),
                                            cwd=folder, env=run_env, text=True, capture_output=True)
                if mode in ('download-fails', 'bad-archive'):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(prefix.exists())
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    for command in ('noproxy487', 'proxy487ctl'):
                        check = subprocess.run([str(prefix / 'bin' / command), '--help'],
                                               env=run_env, text=True, capture_output=True)
                        self.assertEqual(check.returncode, 0, check.stderr)
                    self.assertTrue((prefix / 'lib/megaproxy-tools/config_sync.py').exists())
                    independent_env = dict(run_env, XDG_CONFIG_HOME=str(prefix / 'independent-config'))
                    runner, controller = prefix / 'bin/proxy487', prefix / 'bin/proxy487ctl'
                    hidden_runner = runner.with_name('proxy487-hidden')
                    runner.rename(hidden_runner)
                    try:
                        check = subprocess.run([str(controller), '--no-config-sync', 'import', '-'],
                                               input='https://proxy.example:443', env=independent_env,
                                               text=True, capture_output=True)
                        self.assertEqual(check.returncode, 0, check.stderr)
                        check = subprocess.run([str(controller), '--no-config-sync', 'list'],
                                               env=independent_env, text=True, capture_output=True)
                        self.assertEqual(check.returncode, 0, check.stderr)
                        self.assertIn('proxy.example', check.stdout)
                    finally:
                        hidden_runner.rename(runner)
                    hidden_controller = controller.with_name('proxy487ctl-hidden')
                    controller.rename(hidden_controller)
                    try:
                        check = subprocess.run([str(runner), '--no-config-sync', sys.executable, '-c',
                            'import os; assert os.environ["https_proxy"] == "https://proxy.example:443"'],
                            env=independent_env, text=True, capture_output=True)
                        self.assertEqual(check.returncode, 0, check.stderr)
                    finally:
                        hidden_controller.rename(controller)
                if mode == 'pipe':
                    config = folder / '.config/megaproxy-tools/config.json'
                    config.parent.mkdir(parents=True)
                    config.write_text('existing private configuration')
                    (prefix / 'bin/proxy487').write_text('outdated installed command')
                    update = subprocess.run(['bash'], input=(ROOT / 'install.sh').read_text(),
                                            cwd=folder, env=run_env, text=True, capture_output=True)
                    self.assertEqual(update.returncode, 0, update.stderr)
                    self.assertEqual((prefix / 'bin/proxy487').read_bytes(), (ROOT / 'bin/proxy487').read_bytes())
                    self.assertEqual(config.read_text(), 'existing private configuration')
                    self.assertIn('https://codeload.github.com/andre487/MegaProxyTools/tar.gz/work/proxy-tools',
                                  (folder / 'curl.log').read_text())
                self.assertFalse(list(folder.glob('tmp.*')))


if __name__ == '__main__':
    unittest.main()
