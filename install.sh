#!/bin/sh
set -eu
install_from_git=${INSTALL_FROM_GIT:-0}
case "$#:$*" in
    0:) ;;
    1:--git) install_from_git=1 ;;
    *) printf 'Usage: install.sh [--git]\n' >&2; exit 2 ;;
esac
case "$install_from_git" in
    0|1) ;;
    *) printf 'INSTALL_FROM_GIT must be 0 or 1\n' >&2; exit 2 ;;
esac
command -v python3 >/dev/null
python3 -c 'import sys; sys.exit("Python 3.10+ is required") if sys.version_info < (3, 10) else None'
prefix=${PREFIX:-"$HOME/.local"}
case "$prefix" in
    /*) ;;
    *) prefix="$PWD/$prefix" ;;
esac
installer=${BASH_SOURCE:-$0}
source_dir=$(dirname "$installer")
local_source=0
if [ -f "$installer" ] && [ -f "$source_dir/bin/proxy487" ] && [ -f "$source_dir/lib/megaproxy-tools/megaproxy_tools/config.py" ]; then
    source_dir=$(cd "$source_dir" && pwd -P)
    local_source=1
fi
if [ "$install_from_git" = 1 ]; then
    command -v git >/dev/null
    if [ "$local_source" = 1 ]; then
        [ "$(git -C "$source_dir" rev-parse --show-toplevel)" = "$source_dir" ] || {
            printf 'Git installation requires a repository checkout\n' >&2; exit 1;
        }
    else
        source_dir="$prefix/src/MegaProxyTools"
        repository=https://github.com/andre487/MegaProxyTools.git
        ref=${MEGAPROXY_TOOLS_REF:-main}
        case "$ref" in -*) printf 'Invalid Git ref\n' >&2; exit 2 ;; esac
        if [ -e "$source_dir" ]; then
            [ "$(git -C "$source_dir" rev-parse --show-toplevel)" = "$(cd "$source_dir" && pwd -P)" ] &&
            [ "$(git -C "$source_dir" config --get remote.origin.url)" = "$repository" ] || {
                printf 'Source directory is not a MegaProxyTools checkout\n' >&2; exit 1;
            }
            [ -z "$(git -C "$source_dir" status --porcelain)" ] || {
                printf 'Source checkout has local changes; update it manually\n' >&2; exit 1;
            }
        else
            mkdir -p "$prefix/src"
            git clone -- "$repository" "$source_dir"
        fi
        git -C "$source_dir" fetch origin "$ref"
        git -C "$source_dir" checkout "$ref" --
        git -C "$source_dir" merge --ff-only FETCH_HEAD
        source_dir=$(cd "$source_dir" && pwd -P)
    fi
elif [ "$local_source" = 0 ]; then
    command -v curl >/dev/null
    command -v tar >/dev/null
    temporary=$(mktemp -d)
    trap 'rm -rf "$temporary"' EXIT
    trap 'exit 1' HUP INT TERM
    ref=${MEGAPROXY_TOOLS_REF:-main}
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
        "https://codeload.github.com/andre487/MegaProxyTools/tar.gz/$ref" -o "$temporary/source.tar.gz"
    tar -xzf "$temporary/source.tar.gz" -C "$temporary" --strip-components=1
    source_dir=$temporary
fi
cd "$source_dir"
source_dir=$(pwd -P)
for name in proxy487 noproxy487 proxy487ctl; do
    [ -f "bin/$name" ] || { printf 'Incomplete source checkout\n' >&2; exit 1; }
done
mkdir -p "$prefix/bin"
prefix=$(cd "$prefix" && pwd -P)
[ "$source_dir/bin" != "$(cd "$prefix/bin" && pwd -P)" ] || { printf 'Installation bin must differ from the source bin\n' >&2; exit 1; }
if [ "$install_from_git" = 0 ]; then
    mkdir -p "$prefix/lib/megaproxy-tools/config-schema" "$prefix/lib/megaproxy-tools/megaproxy_tools"
    for name in __init__.py config.py sync.py cli.py; do
        install -m 644 "lib/megaproxy-tools/megaproxy_tools/$name" "$prefix/lib/megaproxy-tools/megaproxy_tools/$name"
    done
    for name in megaproxy-v8.schema.json android-v8.schema.json LICENSE schema-lock.json; do
        install -m 644 "lib/megaproxy-tools/config-schema/$name" "$prefix/lib/megaproxy-tools/config-schema/$name"
    done
fi
for name in proxy487 noproxy487 proxy487ctl; do
    target="$prefix/bin/$name"
    if [ -L "$target" ]; then rm "$target"; fi
    if [ "$install_from_git" = 1 ]; then
        rm -f "$target"
        ln -s "$source_dir/bin/$name" "$target"
    else
        install -m 755 "bin/$name" "$target"
    fi
done
printf 'Installed to %s/bin; add this directory to PATH.\n' "$prefix"
