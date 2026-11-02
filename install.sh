#!/bin/sh
set -eu
cd "$(dirname "$0")"
command -v python3 >/dev/null
prefix=${PREFIX:-"$HOME/.local"}
mkdir -p "$prefix/bin"
for name in proxy487 noproxy487; do
    install -m 755 "bin/$name" "$prefix/bin/$name"
done
printf 'Installed to %s/bin; add this directory to PATH.\n' "$prefix"
