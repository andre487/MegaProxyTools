#!/bin/sh
set -eu
command -v python3 >/dev/null
python3 -c 'import sys; sys.exit("Python 3.9+ is required") if sys.version_info < (3, 9) else None'
installer=${BASH_SOURCE:-$0}
source_dir=$(dirname "$installer")
if [ -f "$installer" ] && [ -f "$source_dir/bin/proxy487" ] && [ -f "$source_dir/lib/megaproxy-tools/proxy_config.py" ]; then
    cd "$source_dir"
else
    command -v curl >/dev/null
    command -v tar >/dev/null
    temporary=$(mktemp -d)
    trap 'rm -rf "$temporary"' EXIT
    trap 'exit 1' HUP INT TERM
    ref=${MEGAPROXY_TOOLS_REF:-main}
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
        "https://codeload.github.com/andre487/MegaProxyTools/tar.gz/$ref" -o "$temporary/source.tar.gz"
    tar -xzf "$temporary/source.tar.gz" -C "$temporary" --strip-components=1
    cd "$temporary"
fi
prefix=${PREFIX:-"$HOME/.local"}
mkdir -p "$prefix/bin" "$prefix/lib/megaproxy-tools/config-schema"
for name in proxy_config.py config_sync.py proxy_cli.py; do
    install -m 644 "lib/megaproxy-tools/$name" "$prefix/lib/megaproxy-tools/$name"
done
for name in megaproxy-v8.schema.json android-v8.schema.json LICENSE schema-lock.json; do
    install -m 644 "lib/megaproxy-tools/config-schema/$name" "$prefix/lib/megaproxy-tools/config-schema/$name"
done
for name in proxy487 noproxy487 proxy487ctl; do
    install -m 755 "bin/$name" "$prefix/bin/$name"
done
printf 'Installed to %s/bin; add this directory to PATH.\n' "$prefix"
