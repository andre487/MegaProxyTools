"""Shared configuration startup and safe error reporting."""

import sys

from . import config as configuration
from . import sync


def command_config(folder, no_sync=False):
    with sync.config_lock(folder):
        config = configuration.load_config(folder)
        return config if no_sync else sync.sync_config(folder, config)


def initialize(no_sync=False):
    folder = configuration.directory()

    with sync.config_lock(folder):
        if (folder / "config.json").exists():
            config = configuration.load_config(folder)

            if not no_sync:
                sync.sync_config(folder, config)

            print(f"Configuration: {folder / 'config.json'}")
        else:
            print(f"Configuration directory: {folder}; use proxy487ctl import FILE")


def run(main):
    try:
        sys.exit(main())
    except (OSError, ValueError, RecursionError) as error:
        # Do not echo URLs or arbitrary OS errors: they can contain credentials.
        print(
            str(error)
            if isinstance(error, ValueError) and not isinstance(error, UnicodeError)
            else "Cannot read configuration or execute command",
            file=sys.stderr,
        )
        sys.exit(1)
