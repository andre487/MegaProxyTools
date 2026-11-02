"""MegaProxy v8 storage, import and merge; Python standard library only."""
import ipaddress
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit, urlunsplit
from uuid import uuid4

SCHEMA_ID = 'net.megaproxy487.config'
LIMIT = 1024 * 1024
SCHEMA = json.loads((Path(__file__).parent / 'config-schema/megaproxy-v8.schema.json').read_text())


def warn(message):
    print(f'Warning: {message}', file=sys.stderr)


def validate(value, rule=SCHEMA):
    """Evaluate the validation keywords used by our pinned schema, not arbitrary schemas."""
    if '$ref' in rule:
        validate(value, SCHEMA['$defs'][rule['$ref'].split('/')[-1]])
    if 'anyOf' in rule:
        for option in rule['anyOf']:
            try:
                validate(value, option)
                break
            except ValueError:
                pass
        else:
            raise ValueError('Invalid configuration field')
    for option in rule.get('allOf', []):
        validate(value, option)
    if 'if' in rule:
        try:
            validate(value, rule['if'])
        except ValueError:
            validate(value, rule.get('else', {}))
        else:
            validate(value, rule.get('then', {}))
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool, 'null': type(None)}
    if 'type' in rule and (not isinstance(value, types[rule['type']]) or
                           rule['type'] == 'integer' and isinstance(value, bool)):
        raise ValueError('Invalid configuration field type')
    if 'const' in rule and (type(value) is not type(rule['const']) or value != rule['const']):
        raise ValueError('Invalid configuration constant')
    if 'enum' in rule and value not in rule['enum']:
        raise ValueError('Invalid configuration field value')
    if isinstance(value, dict):
        if any(key not in value for key in rule.get('required', [])):
            raise ValueError('Missing required configuration field')
        for key, child in rule.get('properties', {}).items():
            if key in value:
                validate(value[key], child)
    if isinstance(value, list):
        if not rule.get('minItems', 0) <= len(value) <= rule.get('maxItems', float('inf')):
            raise ValueError('Invalid configuration array length')
        if rule.get('uniqueItems') and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise ValueError('Duplicate configuration array entries')
        for child in value:
            validate(child, rule.get('items', {}))
    if isinstance(value, str):
        if not rule.get('minLength', 0) <= len(value) <= rule.get('maxLength', float('inf')):
            raise ValueError('Invalid configuration string length')
        if 'pattern' in rule and not re.search(rule['pattern'], value):
            raise ValueError('Invalid configuration string')
    if type(value) is int and not rule.get('minimum', -float('inf')) <= value <= rule.get('maximum', float('inf')):
        raise ValueError('Invalid configuration number')


def directory():
    base = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    if not base.is_absolute():
        base = Path.home() / '.config'
    target = base / 'megaproxy-tools'
    legacy = Path.home() / '.proxy487'
    return legacy if not target.exists() and legacy.is_dir() else target


def read_text(path):
    with path.open('rb') as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('Configuration exceeds 1 MiB')
    try:
        return data.decode('utf-8-sig')
    except UnicodeError:
        raise ValueError('Configuration must be UTF-8') from None


def atomic_write(path, document):
    data = json.dumps(document, ensure_ascii=False, indent=2) + '\n'
    if len(data.encode('utf-8')) > LIMIT:
        raise ValueError('Configuration exceeds 1 MiB')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def empty_config():
    # An empty installation has no config.json until a nonempty import is available.
    return {'schema': SCHEMA_ID, 'version': 8, 'profiles': [], 'activeProfileId': None}


def normalized_host(value):
    value = value.strip('[]').rstrip('.').lower()
    if not value or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError('Invalid proxy hostname')
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        if any(c in value for c in ':@?#\\/[]%'):
            raise ValueError('Invalid proxy hostname')
        try:
            return value.encode('idna').decode('ascii')
        except UnicodeError:
            raise ValueError('Invalid proxy hostname') from None


def profile_url(profile):
    proxy = profile['proxy']
    scheme = {'HTTPS': 'https', 'SOCKS5': 'socks5h'}.get(proxy['type'])
    if scheme is None:
        raise ValueError('Unsupported proxy transport')
    if proxy['type'] == 'SOCKS5' and bool(proxy.get('username')) != bool(proxy.get('password')):
        raise ValueError('SOCKS5 requires both username and password, or neither')
    host = proxy['host']
    host = f'[{host}]' if ':' in host else host
    auth = ''
    if proxy.get('username') or proxy.get('password'):
        auth = quote(proxy.get('username', ''), safe='') + ':' + quote(proxy.get('password', ''), safe='') + '@'
    return f'{scheme}://{auth}{host}:{proxy["port"]}'


def subscription(value):
    if value is None:
        return None
    validate(value, SCHEMA['$defs']['configSubscription'])
    result = {key: value[key] for key in ('url', 'fallbackUrls', 'username', 'password', 'intervalMinutes', 'enabled') if key in value}
    sources = []
    for raw in [value['url'], *value.get('fallbackUrls', [])]:
        try:
            url = urlsplit(raw)
            if (url.scheme != 'https' or not url.hostname or url.username is not None or
                    '#' in raw or any(ord(c) <= 32 or ord(c) == 127 for c in raw) or
                    '\\' in raw or re.search(r'%(?![a-fA-F0-9]{2})', raw)):
                raise ValueError
            host = normalized_host(url.hostname)
            host = f'[{host}]' if ':' in host else host
            port = url.port
            if port is not None and not 1 <= port <= 65535:
                raise ValueError
            netloc = host if port in (None, 443) else f'{host}:{port}'
            normalized = urlunsplit(('https', netloc, url.path or '/', url.query, ''))
        except ValueError:
            raise ValueError('Subscription requires final HTTPS URLs without credentials or fragments') from None
        if normalized in sources:
            raise ValueError('Duplicate subscription URLs')
        sources.append(normalized)
    for key in ('username', 'password'):
        if any(ord(c) < 32 or ord(c) == 127 for c in value.get(key, '')) or (key == 'username' and ':' in value.get(key, '')):
            raise ValueError('Invalid subscription credentials')
    result['url'] = sources[0]
    if 'fallbackUrls' in value:
        result['fallbackUrls'] = sources[1:]
    return result


def project(root):
    validate(root)
    ids = [p['id'] for p in root['profiles']]
    if any(not i.strip() for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Profile IDs must be nonempty and unique')
    active = root.get('activeProfileId')
    if active is not None and active not in ids:
        raise ValueError('Selected profile ID is absent from configuration')
    result = empty_config()
    ignored = bool(set(root) - {'schema', 'version', 'profiles', 'activeProfileId', 'passwordsIncluded', 'privateKeysIncluded', 'routing', 'subscription'})
    if 'subscription' in root:
        result['subscription'] = subscription(root['subscription'])
        if isinstance(root['subscription'], dict):
            ignored |= bool(set(root['subscription']) - set(result['subscription']))
    if 'routing' in root:
        ignored |= bool(set(root['routing']) - {'bypassLocalNetworks'})
        if 'bypassLocalNetworks' in root['routing']:
            result['routing'] = {'bypassLocalNetworks': root['routing']['bypassLocalNetworks']}
    skipped = 0
    for profile in root['profiles']:
        proxy = profile['proxy']
        if proxy['type'] not in ('HTTPS', 'SOCKS5') or proxy.get('allowInvalidProxyCertificate'):
            skipped += 1
            continue
        p = {key: value for key, value in profile.items() if key in ('id', 'name', 'color', 'countryCode')}
        p['proxy'] = {key: value for key, value in proxy.items() if key in ('type', 'host', 'port', 'username', 'password')}
        p['proxy']['host'] = normalized_host(proxy['host'])
        user, password = proxy.get('username', ''), proxy.get('password', '')
        if any(ord(c) < 32 or ord(c) == 127 for c in user + password):
            raise ValueError('Control characters in proxy credentials')
        if proxy['type'] == 'SOCKS5' and (len(user.encode('utf-8')) > 255 or len(password.encode('utf-8')) > 255):
            raise ValueError('SOCKS5 credentials exceed 255 UTF-8 bytes')
        ignored |= bool(set(profile) - {'id', 'name', 'color', 'countryCode', 'proxy'})
        ignored |= bool(set(proxy) - {'type', 'host', 'port', 'username', 'password'})
        result['profiles'].append(p)
    if skipped:
        warn(f'Skipped {skipped} unsupported profiles (transport or certificate policy)')
    if ignored:
        warn('Unsupported platform settings and unknown fields were discarded')
    if not result['profiles']:
        raise ValueError('No compatible profiles; configuration was not changed')
    result['activeProfileId'] = active if active in {p['id'] for p in result['profiles']} else None
    return result


def legacy_entries(data):
    if isinstance(data, dict) and 'schemaVersion' in data:
        if type(data['schemaVersion']) is not int or data['schemaVersion'] not in (1, 2):
            raise ValueError('Unsupported ZeroOmega version')
        entries = []
        if sum(key.startswith('+') for key in data) > 1000:
            raise ValueError('Too many ZeroOmega profiles')
        for key, entry in data.items():
            if not key.startswith('+'):
                continue
            if not isinstance(entry, dict):
                raise ValueError('Invalid ZeroOmega profile')
            if entry.get('profileType') != 'FixedProfile':
                warn('Skipped ZeroOmega routing or non-fixed profile')
                continue
            endpoints = [(k, entry[k]) for k in ('proxyForHttp', 'proxyForHttps', 'proxyForFtp', 'fallbackProxy') if entry.get(k)]
            if not endpoints or not all(isinstance(p, dict) for _, p in endpoints):
                raise ValueError('Invalid ZeroOmega endpoints')
            first = endpoints[0][1]
            auth = entry.get('auth', {})
            if not isinstance(auth, dict):
                raise ValueError('Invalid ZeroOmega authentication')
            credentials = auth.get(endpoints[0][0], auth.get('all', {}))
            if any(any(p.get(k) != first.get(k) for k in ('scheme', 'host', 'port')) or
                   auth.get(k, auth.get('all', {})) != credentials for k, p in endpoints):
                warn('Skipped ZeroOmega profile with different per-protocol proxies or credentials')
                continue
            if not isinstance(credentials, dict):
                raise ValueError('Invalid ZeroOmega credentials')
            entries.append({**first, 'type': first.get('scheme'), 'name': entry.get('name', key[1:]),
                            'username': credentials.get('username', ''), 'password': credentials.get('password', '')})
            if entry.get('bypassList'):
                warn('ZeroOmega bypass rules were discarded')
        return entries
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get('profiles', data.get('data'))
    raise ValueError('Unsupported import format')


def parse_import(text):
    text = text.lstrip('\ufeff').strip()
    if not text:
        raise ValueError('Empty import')
    if text[0] in '{[':
        try:
            data = json.loads(text)
        except (ValueError, RecursionError):
            raise ValueError('Invalid JSON configuration') from None
        if isinstance(data, dict) and 'schema' in data:
            if data['schema'] not in (SCHEMA_ID, 'dev.megaproxy.config') or type(data.get('version')) is not int or not 1 <= data['version'] <= 8:
                raise ValueError('Unsupported MegaProxy schema or version')
            if data['version'] < 8:
                entries = data.get('profiles')
                if not isinstance(entries, list) or not entries or len(entries) > 1000:
                    raise ValueError('Invalid profile list')
                for index, entry in enumerate(entries):
                    if not isinstance(entry, dict) or not isinstance(entry.get('proxy'), dict):
                        raise ValueError('Invalid legacy MegaProxy profile')
                    if data['version'] < 7:
                        entry.setdefault('id', f'import-{index}')
                    proxy = entry['proxy']
                    proxy.setdefault('type', 'HTTPS')
                    if not isinstance(proxy['type'], str):
                        raise ValueError('Invalid legacy proxy type')
                    proxy.setdefault('port', {'SSH': 22, 'SSH_JUMP': 22, 'SOCKS5': 1080}.get(proxy['type'], 443))
                data['version'] = 8
            return project(data)
        entries = legacy_entries(data)
    else:
        entries = []
        unknown_query = False
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if len(line) > 65536 or any(c.isspace() for c in line) or re.search(r'%(?![a-fA-F0-9]{2})', line):
                raise ValueError('Invalid ProxyList URL')
            try:
                url = urlsplit(line)
                if not url.scheme or not url.hostname or url.path not in ('', '/'):
                    raise ValueError
                query = parse_qs(url.query, max_num_fields=100)
                entry = {'type': url.scheme, 'host': url.hostname,
                         'port': url.port if url.port is not None else {'https': 443, 'socks5': 1080, 'socks5h': 1080, 'masque': 443}.get(url.scheme, 80),
                         'username': unquote(url.username or '', errors='strict'),
                         'password': unquote(url.password or '', errors='strict'),
                         'name': query.get('title', [''])[0], 'countryCode': query.get('cc', [''])[0]}
            except (ValueError, UnicodeError):
                raise ValueError('Invalid ProxyList URL') from None
            unknown_query |= bool(set(query) - {'title', 'cc'})
            entries.append(entry)
        if unknown_query:
            warn('Unknown ProxyList URL parameters were discarded')
    if not isinstance(entries, list) or not entries or len(entries) > 1000:
        raise ValueError('Import requires 1–1000 profiles')
    root = empty_config()
    skipped = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Invalid imported profile')
        proxy = entry.get('proxy', entry)
        if not isinstance(proxy, dict):
            raise ValueError('Invalid imported proxy')
        kind = str(proxy.get('type', proxy.get('proxyType', ''))).strip().upper()
        kind = {'SSL': 'HTTPS', 'SOCKS': 'SOCKS5', 'SOCKS5H': 'SOCKS5'}.get(kind, kind)
        if kind not in ('HTTPS', 'SOCKS5') or proxy.get('pac') or proxy.get('pacString') or proxy.get('allowInvalidProxyCertificate'):
            skipped += 1
            continue
        raw_port = proxy.get('port', 1080 if kind == 'SOCKS5' else 443)
        if isinstance(raw_port, str) and raw_port.isascii() and raw_port.isdigit():
            raw_port = int(raw_port)
        p = {'id': str(uuid4()), 'name': entry.get('name') or entry.get('title') or '',
             'countryCode': str(entry.get('countryCode') or entry.get('cc') or '').upper(),
             'proxy': {'type': kind, 'host': proxy.get('host') or proxy.get('hostname') or proxy.get('address') or '', 'port': raw_port}}
        if not re.fullmatch('[A-Z]{2}', p['countryCode']):
            p['countryCode'] = ''
        for key in ('username', 'password'):
            if key in proxy:
                p['proxy'][key] = proxy[key]
        root['profiles'].append(p)
    if skipped:
        warn(f'Skipped {skipped} unsupported profiles (HTTP, SSH, Jump, MASQUE or PAC)')
    if text[0] in '{[':
        warn('Only endpoint credentials and profile labels are imported from legacy formats; routing and other settings are discarded')
    return project(root)


def load_config(folder, missing_ok=False):
    path = folder / 'config.json'
    if path.exists():
        return parse_import(read_text(path))
    legacy = folder / 'proxy-list.txt'
    if legacy.exists():
        result = parse_import(read_text(legacy))
        chosen = folder / 'chosen'
        host = read_text(chosen).strip() if chosen.exists() else ''
        selected = next((p for p in result['profiles'] if not host or p['proxy']['host'] == normalized_host(host)), None)
        if selected is None:
            raise ValueError('Selected legacy hostname is absent from proxy list')
        result['activeProfileId'] = selected['id']
        atomic_write(path, result)
        return result
    if missing_ok:
        return empty_config()
    raise ValueError('No configuration; use proxy487ctl import FILE or proxy487ctl init')


def merge(current, incoming):
    result = {**current}
    profiles = {p['id']: p for p in current['profiles']}
    for entry in incoming['profiles']:
        old = profiles.get(entry['id'])
        if old and 'password' not in entry['proxy']:
            previous, new = old['proxy'], entry['proxy']
            if all(previous.get(k, '') == new.get(k, '') for k in ('type', 'host', 'port', 'username')) and 'password' in previous:
                entry = {**entry, 'proxy': {**new, 'password': previous['password']}}
        profiles[entry['id']] = entry
    result['profiles'] = list(profiles.values())
    result['activeProfileId'] = (active_profile(current)['id'] if current['profiles']
                                 else incoming.get('activeProfileId'))
    if 'routing' in incoming:
        result['routing'] = incoming['routing']
    if 'subscription' in incoming:
        new = incoming['subscription']
        previous = current.get('subscription')
        if (new is not None and previous and 'password' not in new and 'password' in previous and
                new['url'] == previous['url'] and new.get('username', '') == previous.get('username', '')):
            new = {**new, 'password': previous['password']}
        result['subscription'] = new
    validate(result)
    return result


def active_profile(config):
    profiles = config['profiles']
    selected = config.get('activeProfileId')
    return next((p for p in profiles if p['id'] == selected), profiles[0])
