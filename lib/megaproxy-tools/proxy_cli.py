"""Shared configuration startup and safe error reporting."""
import sys

from config_sync import config_lock, sync_config
from proxy_config import directory, load_config


def command_config(folder, no_sync=False):
    with config_lock(folder):
        config = load_config(folder)
        return config if no_sync else sync_config(folder, config)


def initialize(no_sync=False):
    folder = directory()
    with config_lock(folder):
        if (folder / 'config.json').exists() or (folder / 'proxy-list.txt').exists():
            config = load_config(folder)
            if not no_sync:
                sync_config(folder, config)
            print(f'Configuration: {folder / "config.json"}')
        else:
            print(f'Configuration directory: {folder}; use proxy487ctl import FILE')


def run(main):
    try:
        sys.exit(main())
    except (OSError, ValueError, RecursionError) as error:
        # Do not echo URLs or arbitrary OS errors: they can contain credentials.
        print(str(error) if isinstance(error, ValueError) and not isinstance(error, UnicodeError)
              else 'Cannot read configuration or execute command', file=sys.stderr)
        sys.exit(1)
