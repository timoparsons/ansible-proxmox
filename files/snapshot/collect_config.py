#!/usr/bin/env python3
# Collect config files on a guest and write REDACTED copies only.
# Usage: collect_config.py MANIFEST_JSON OUT_DIR
# The manifest is a list of entries: {"src": FILE_OR_DIR, "recursive": bool, "include": [globs], "exclude": [globs]}
# to collect, or {"learn": FILE_OR_DIR, "include": [globs]} to read secrets from (secrets.yaml, .env) WITHOUT collecting them.
# Raw files are only read, never copied: the unredacted text never reaches disk or the network.
# Every secret value it redacts or learns is also scrubbed from every other place it appears in the output.
# Exits 1 and writes nothing if a tripwire check finds something that looks like a secret.
import fnmatch, json, os, re, sys

MAX_BYTES = 2 * 1024 * 1024

# Never collected, whatever the manifest says.
HARD_DENY = [
    'secrets.yaml', 'secrets.yaml.*', '.env', '*.env', 'passwd', '.jwt_secret', '*.pem', '*.key',
    '*.db', '*.db-*', '*.sqlite*', '*.log', '*.log.*', '*bak*', '*bkp*', '*removed*', '*.old',
    '._*', '.DS_Store', '*~', 'known_devices.yaml', 'coordinator_backup.json', 'Preferences.xml',
    'upsd.users', 'upsmon.conf', 'lovelace.map',
]

SECRET_WORDS = re.compile(
    r'(password|passwd|passphrase|secret|token|credential|cookie|jwt|bearer|psk|webhook|apikey|api_key|'
    r'private_key|auth_key|authkey|user_key|userkey|encryption_key|network_key)')
EXACT_KEYS = {'key', 'pass', 'pw', 'passcode', 'otp', 'openvpn_user', 'openvpn_username', 'vpn_user'}

LINE = re.compile(r'^(?P<lead>\s*(?:-\s+)?)(?P<q1>["\']?)(?P<key>[A-Za-z0-9_.\-]+)(?P<q2>["\']?)(?P<sep>\s*[:=]\s*)(?P<val>.*)$')
PEM = re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----', re.S)
URL_CRED = re.compile(r'(://)([^/\s:@"\']+):(?![{$])([^/\s@"\']+)@')
URL_QUERY = re.compile(r'(?i)([?&](?:token|access_token|api_?key|key|auth|password|passwd|secret|sig|signature)=)([^&\s"\']+)')
GOOGLE_ID = re.compile(r'((?:docs|drive|script)\.google\.com/(?:[a-z0-9_-]+/)*d/)([A-Za-z0-9_-]{20,})')
CLI_USER_PW = re.compile(r'(\s-u\s+\S+\s+-p\s+)(?![\'"]?[{$])(\S+)')
CLI_PW_FLAG = re.compile(r'(?i)(\s--?(?:pass(?:word|wd)?|pwd|secret|token)(?:=|\s+)|\bsshpass\s+-p\s+)(?![\'"]?[{$])([^\s\'"]+)')
BCRYPT = re.compile(r'\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}')
JWT = re.compile(r'eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*')
BEARER = re.compile(r'(?i)(bearer\s+)(?![${])[A-Za-z0-9._~+/=-]{16,}')
LONG = re.compile(r'(?<![A-Za-z0-9])(?<!sha256:)[A-Za-z0-9]{28,}(?![A-Za-z0-9])')
HEX32 = re.compile(r'^[0-9a-f]{32}$')
TOKEN_RUN = re.compile(r'(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{24,}(?![A-Za-z0-9_-])')
NOT_SECRET_PREFIX = ('sha256:', 'spotify:playlist:', 'spotify:track:', 'spotify:album:', 'spotify:artist:', 'spotify:show:', 'spotify:episode:')
BLOCK_MARKS = ('|', '>', '|-', '>-', '|+', '>+')
NONSECRET = {'', 'null', '~', 'true', 'false', "''", '""', 'none'}

count = {'n': 0}
KNOWN = set()


def learn(v):
    v = v.strip().strip('"\'').rstrip(',').strip()
    if len(v) < 6 or is_reference(v) or v.startswith('REDACTED'):
        return
    if v.startswith('/') and v.count('/') > 1 and ' ' not in v:
        return
    KNOWN.add(v)


def hit():
    count['n'] += 1


def is_secret_key(key):
    k = key.strip().lower().replace('-', '_').replace('.', '_')
    return k in EXACT_KEYS or k.endswith('_key') or bool(SECRET_WORDS.search(k))


def is_reference(v):
    v = v.strip()
    if v.lower() in NONSECRET:
        return True
    inner = v.strip('"\'')
    return inner.startswith(('${', '$(', '{env.', '!secret', '!env', '{{', '{%', 'REDACTED', '<')) or v.startswith(('!secret', '!env'))


def clean_string(s):
    def sub(rx, repl, text, grp=None):
        def f(m):
            hit()
            if grp:
                learn(m.group(grp))
            return m.expand(repl)
        return rx.sub(f, text)
    s = sub(CLI_USER_PW, r'\1REDACTED', s, 2)
    s = sub(CLI_PW_FLAG, r'\1REDACTED', s, 2)
    s = sub(URL_CRED, r'\1REDACTED@', s, 3)
    s = sub(URL_QUERY, r'\1REDACTED', s, 2)
    s = sub(GOOGLE_ID, r'\1REDACTED', s)
    s = sub(BCRYPT, 'REDACTED-BCRYPT', s)
    s = sub(JWT, 'REDACTED-JWT', s)
    s = sub(BEARER, r'\1REDACTED', s, 0)

    def long_sub(m):
        t = m.group(0)
        if not (any(c.isdigit() for c in t) and any(c.isalpha() for c in t)) or HEX32.match(t):
            return t
        hit()
        learn(t)
        return 'REDACTED-LONG'
    return LONG.sub(long_sub, s)


def indent_of(s):
    return len(s) - len(s.lstrip(' '))


def redact_text(text):
    text = PEM.sub(lambda m: (hit(), 'REDACTED-PRIVATE-KEY')[1], text)
    lines = text.split('\n')
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = LINE.match(line)
        if not (m and is_secret_key(m.group('key'))):
            out.append(clean_string(line))
            i += 1
            continue
        col = len(m.group('lead'))
        has_dash = m.group('lead').strip().startswith('-')
        val = re.sub(r'\s+#.*$', '', m.group('val')).strip()

        def continues(l):
            ind = indent_of(l)
            return ind > col or (ind == col and not has_dash and l.lstrip().startswith('- '))

        if val == '' or val in BLOCK_MARKS:
            j = i + 1
            consumed = 0
            while j < len(lines):
                if lines[j].strip() == '':
                    k = j
                    while k < len(lines) and lines[k].strip() == '':
                        k += 1
                    if k < len(lines) and continues(lines[k]):
                        j = k
                        continue
                    break
                if continues(lines[j]):
                    j += 1
                    consumed += 1
                    continue
                break
            out.append(line)
            if consumed:
                hit()
                for extra in lines[i + 1:j]:
                    learn(re.sub(r'^\s*-\s+', '', extra))
                out.append(' ' * (col + 2) + 'REDACTED')
            i = j
            continue
        if is_reference(val):
            out.append(line)
        else:
            hit()
            learn(val)
            out.append(m.group('lead') + m.group('q1') + m.group('key') + m.group('q2') + m.group('sep') + 'REDACTED')
        i += 1
    return '\n'.join(out)


def redact_json(o, key=None):
    if isinstance(o, dict):
        res = {}
        for k, v in o.items():
            if is_secret_key(str(k)) and not (isinstance(v, str) and is_reference(v)) and v not in (None, True, False, ''):
                hit()
                if isinstance(v, str):
                    learn(v)
                res[k] = 'REDACTED'
            else:
                res[k] = redact_json(v, k)
        return res
    if isinstance(o, list):
        return [redact_json(v, key) for v in o]
    if isinstance(o, str):
        return clean_string(o)
    return o


def random_looking(text):
    # A run of 24+ characters with upper, lower and a digit, and at most one _ or -, is not a name or a path.
    for m in TOKEN_RUN.finditer(text):
        t = m.group(0)
        if t.count('_') + t.count('-') > 1 or HEX32.match(t):
            continue
        if not (any(c.isupper() for c in t) and any(c.islower() for c in t) and any(c.isdigit() for c in t)):
            continue
        if text[max(0, m.start() - 17):m.start()].endswith(NOT_SECRET_PREFIX):
            continue
        return True
    return False


def tripwire(text):
    probs = []
    if re.search(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY', text):
        probs.append('a private key block survived')
    if URL_CRED.search(text):
        probs.append('a URL with credentials survived')
    if BCRYPT.search(text) or JWT.search(text):
        probs.append('a password hash or JWT survived')
    for v in KNOWN:
        if v in text:
            probs.append('a known secret value is still present')
            break
    if random_looking(text):
        probs.append('a long random-looking string survived')
    for line in text.split('\n'):
        m = LINE.match(line)
        if m and is_secret_key(m.group('key')):
            v = re.sub(r'\s+#.*$', '', m.group('val')).strip().rstrip(',')
            if not is_reference(v) and v not in BLOCK_MARKS:
                probs.append('a value under the key "%s" was not redacted' % m.group('key'))
                break
    return probs


def scrub(text):
    n = 0
    for v in sorted(KNOWN, key=len, reverse=True):
        if v in text:
            n += text.count(v)
            text = text.replace(v, 'REDACTED')
    return text, n


def learn_from(entry):
    # Read secrets from files we never collect. Values are only remembered in memory, never written.
    src = entry['learn']
    paths = []
    if os.path.isfile(src):
        paths = [src]
    elif os.path.isdir(src):
        for root, dirs, files in os.walk(src):
            if not entry.get('recursive', False):
                dirs[:] = []
            paths += [os.path.join(root, f) for f in sorted(files) if any(fnmatch.fnmatch(f, x) for x in entry.get('include', ['*']))]
    for p in paths:
        if os.path.islink(p) or not os.path.isfile(p) or os.path.getsize(p) > MAX_BYTES:
            continue
        for line in open(p, errors='replace').read().split('\n'):
            m = LINE.match(line)
            if m:
                learn(re.sub(r'\s+#.*$', '', m.group('val')))


def denied(name):
    return any(fnmatch.fnmatch(name, p) for p in HARD_DENY)


def expand(entry, missing):
    src = entry['src']
    if os.path.islink(src):
        missing.append(src + ' (symlink, skipped)')
        return
    if os.path.isfile(src):
        yield src
        return
    if not os.path.isdir(src):
        missing.append(src)
        return
    recursive = entry.get('recursive', False)
    inc = entry.get('include', ['*'])
    exc = entry.get('exclude', [])
    for root, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if recursive and not denied(d) and not any(fnmatch.fnmatch(d, p) for p in exc))
        for f in sorted(files):
            p = os.path.join(root, f)
            rel = os.path.relpath(p, src)
            if os.path.islink(p) or any(fnmatch.fnmatch(f, x) or fnmatch.fnmatch(rel, x) for x in exc):
                continue
            if any(fnmatch.fnmatch(f, x) for x in inc):
                yield p


def main():
    manifest = json.load(open(sys.argv[1], encoding='utf-8'))
    out_dir = sys.argv[2]
    for entry in manifest:
        if 'learn' in entry:
            learn_from(entry)
    results = {}
    missing = []
    skipped = []
    problems = []
    for entry in manifest:
        if 'src' not in entry:
            continue
        for path in expand(entry, missing):
            if path in results:
                continue
            if denied(os.path.basename(path)):
                skipped.append('%s (on the never-collect list)' % path)
                continue
            if os.path.getsize(path) > MAX_BYTES:
                skipped.append('%s (over %d bytes)' % (path, MAX_BYTES))
                continue
            raw = open(path, 'rb').read()
            if b'\x00' in raw:
                skipped.append('%s (binary)' % path)
                continue
            text = raw.decode('utf-8', errors='replace')
            count['n'] = 0
            base = os.path.basename(path)
            done = None
            if base.startswith('lovelace') or base.endswith('.json'):
                try:
                    done = json.dumps(redact_json(json.loads(text)), indent=2, ensure_ascii=False) + '\n'
                except ValueError:
                    done = None
            if done is None:
                done = redact_text(text)
            results[path] = [done, count['n']]
    # Second pass: every secret value learned anywhere is removed from everywhere, then the tripwire checks.
    for path in results:
        results[path][0], extra = scrub(results[path][0])
        results[path][1] += extra
        for b in tripwire(results[path][0]):
            problems.append('%s: %s' % (path, b))
    for s_ in skipped:
        print('SKIPPED ' + s_)
    for m in missing:
        print('MISSING ' + m)
    if problems:
        print('REDACTION CHECK FAILED, nothing written:')
        for p in problems:
            print('  ' + p)
        sys.exit(1)
    for path, (done, n) in sorted(results.items()):
        dest = os.path.join(out_dir, path.lstrip('/'))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'w', encoding='utf-8') as fh:
            fh.write(done)
        print('OK %s redactions=%d' % (path, n))
    print('files written: %d (learned %d secret values)' % (len(results), len(KNOWN)))


main()
