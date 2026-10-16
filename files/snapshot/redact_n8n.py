#!/usr/bin/env python3
# Redact n8n workflow exports before they leave the n8n host.
# Usage: redact_n8n.py RAW_DIR OUT_DIR
# Writes one pretty JSON file per workflow, named slug--id.json.
# Exits 1 and writes nothing if a suspicious string survives redaction.
import glob, json, os, re, sys

DROP = ['pinData', 'staticData', 'shared']
SECRET_KEY = re.compile(r'(?i)^(userkey|user_key|token|apikey|api_key|accesstoken|access_token|password|passwd|secret|clientsecret|authorization)$')
SECRET_NAMES = ['user', 'token', 'key', 'apikey', 'api_key', 'api-key', 'x-api-key', 'authorization', 'password', 'secret', 'access_token']
ASSIGN = re.compile(r'(?i)((?:api[_-]?key|token|secret|passw(?:or)?d|user[_-]?key|authorization)\w*[\x27\x22]?\s*[:=]\s*[\x27\x22\x60])([^\x27\x22\x60\s]{8,})([\x27\x22\x60])')
BEARER = re.compile(r'(?i)(bearer\s+)(?![$][{])[A-Za-z0-9._~+/=-]{16,}')
HEX64 = re.compile(r'\b[0-9a-fA-F]{64}\b')
MIXED = re.compile(r'[A-Za-z0-9]{28,}')
TRIPWIRE = re.compile(r'[A-Za-z0-9]{20,}')
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+')
CALID = re.compile(r'[^\s\x27\x22@]{12,}@group(?:\.v)?\.calendar\.google\.com')
SAFE = re.compile(r'^[A-Za-z]+[Oo][Aa]uth2(Api)?$')


def has_both(t):
    return any(c.isdigit() for c in t) and any(c.isalpha() for c in t)


def clean_string(s, key):
    if key and SECRET_KEY.match(key) and not s.startswith('='):
        return 'REDACTED'
    s = EMAIL.sub(lambda m: m.group(0) if m.group(0).endswith('.calendar.google.com') else 'REDACTED-EMAIL', s)
    s = CALID.sub('REDACTED-CALENDAR-ID@group.calendar.google.com', s)
    s = ASSIGN.sub(r'\1REDACTED\3', s)
    s = BEARER.sub(r'\1REDACTED', s)
    s = HEX64.sub('REDACTED-HEX64', s)
    s = MIXED.sub(lambda m: 'REDACTED-LONG' if has_both(m.group(0)) and not SAFE.match(m.group(0)) else m.group(0), s)
    return s


def walk(o, key):
    if isinstance(o, dict):
        nm = o.get('name')
        pair = isinstance(nm, str) and nm.strip().lower() in SECRET_NAMES
        out = {}
        for k, v in o.items():
            if k == 'value' and pair and isinstance(v, str) and not v.startswith('='):
                out[k] = 'REDACTED'
            else:
                out[k] = walk(v, k)
        return out
    if isinstance(o, list):
        return [walk(v, key) for v in o]
    if isinstance(o, str):
        return clean_string(o, key)
    return o


def slug(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'workflow'


def main():
    raw, out = sys.argv[1], sys.argv[2]
    docs = []
    for f in sorted(glob.glob(os.path.join(raw, '*.json'))):
        d = json.load(open(f, encoding='utf-8'))
        for w in (d if isinstance(d, list) else [d]):
            for k in DROP:
                w.pop(k, None)
            for n in w.get('nodes', []):
                p = n.get('parameters')
                if n.get('type') == 'n8n-nodes-base.webhook' and isinstance(p, dict) and 'path' in p:
                    p['path'] = 'REDACTED-WEBHOOK-PATH'
                if 'webhookId' in n:
                    n['webhookId'] = 'REDACTED'
            docs.append(walk(w, None))
    problems = []
    for w in docs:
        text = json.dumps(w, ensure_ascii=False)
        label = str(w.get('name', '?'))[:40]
        if HEX64.search(text):
            problems.append('%s: a 64 character hex string survived' % label)
        for m in TRIPWIRE.finditer(text):
            if has_both(m.group(0)) and not SAFE.match(m.group(0)):
                problems.append('%s: a long mixed letter and digit string survived (length %d)' % (label, len(m.group(0))))
        if BEARER.search(text):
            problems.append('%s: a literal bearer value survived' % label)
    if problems:
        print('REDACTION CHECK FAILED, nothing written:')
        for p in problems:
            print('  ' + p)
        sys.exit(1)
    os.makedirs(out, exist_ok=True)
    for w in docs:
        path = os.path.join(out, '%s--%s.json' % (slug(str(w.get('name', 'workflow'))), w.get('id', 'noid')))
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(w, fh, indent=2, ensure_ascii=False)
            fh.write(chr(10))
    print('redacted workflows written: %d' % len(docs))


main()
