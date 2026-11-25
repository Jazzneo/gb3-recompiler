"""GDAT archive engine for GUNDAM BREAKER 3 (CUSA07651): read records, apply byte deltas, undo.

Every mod in this tool is stored as a *delta*: the list of byte runs that differ between the
original record (taken from the player's own archive at install time) and the modded record.
No original game bytes are shipped; a record is only rebuilt when the player's original decodes
to exactly the expected sha256.

Archive layout (little endian): 'GDAT', u32 count, count x {u64 key, u32 offset, u32 size}.
Record: 128-byte resource header, 'BILZ', u32be decoded size, u32be packed size, u32be mode (7),
zlib stream. A record's "decoded" form here is header128 + zlib-decoded payload.
pac bundle: +0 128-byte header ('pac\\0'), +128 u32 count, u32 largest entry,
+136 count x {name[256], u32 typehash, u32 size}, then the entries (each a record) back to back.

Install = append rebuilt records to the end of the archive and repoint their index entries; the
original records stay in the file. Restore = point the index back and truncate. A state file
beside the archive (`<archive>.gb3r-state.json`) is written and synced before any archive byte
changes.
"""
import hashlib
import json
import os
import struct
import zlib

STATE_SUFFIX = '.gb3r-state.json'


def sha(b):
    return hashlib.sha256(b).hexdigest()


class PatchError(Exception):
    pass


# ------------------------------------------------------------------ archive / record codec

def read_index(path):
    with open(path, 'rb') as f:
        magic, count = struct.unpack('<4sI', f.read(8))
        if magic != b'GDAT':
            raise PatchError('%s is not a GDAT archive' % os.path.basename(path))
        raw = f.read(16 * count)
    size = os.path.getsize(path)
    out = {}
    for i in range(count):
        key, off, ln = struct.unpack_from('<QII', raw, 16 * i)
        if off + ln > size:
            raise PatchError('%s: index entry %016x points past the end' % (os.path.basename(path), key))
        out['%016x' % key] = (8 + 16 * i, off, ln)
    return out


def read_at(path, off, ln):
    with open(path, 'rb') as f:
        f.seek(off)
        b = f.read(ln)
    if len(b) != ln:
        raise PatchError('truncated read at %#x' % off)
    return b


def decode(blob):
    """record blob -> header128 + payload."""
    if blob[128:132] != b'BILZ':
        raise PatchError('record has no BILZ wrapper')
    length, packed, mode = struct.unpack_from('>III', blob, 132)
    if mode != 7 or packed + 144 != len(blob):
        raise PatchError('unexpected BILZ metadata')
    data = zlib.decompress(blob[144:])
    if len(data) != length:
        raise PatchError('BILZ length mismatch')
    return blob[:128] + data


def encode(rec):
    """header128 + payload -> record blob."""
    data = rec[128:]
    packed = zlib.compress(data, 9)
    return rec[:128] + b'BILZ' + struct.pack('>III', len(data), len(packed), 7) + packed


def pac_walk(b):
    if b[:4] != b'pac\x00':
        raise PatchError('not a pac bundle')
    n, _ = struct.unpack_from('<II', b, 128)
    out, pos = [], 136 + 264 * n
    for i in range(n):
        p = 136 + 264 * i
        th, size = struct.unpack_from('<II', b, p + 256)
        out.append((b[p:p + 256], th, b[pos:pos + size]))
        pos += size
    if pos != len(b):
        raise PatchError('pac size mismatch')
    return out


def pac_build(head, entries):
    t = bytearray(head[:128]) + struct.pack('<II', len(entries), max(len(e[2]) for e in entries))
    for name, th, blob in entries:
        t += name + struct.pack('<II', th, len(blob))
    for _, _, blob in entries:
        t += blob
    return bytes(t)


def pac_name(name256):
    return name256.split(b'\0')[0].decode('latin1')


# ------------------------------------------------------------------ deltas

def make_delta(old, new, gap=16):
    """-> (runs, blob): runs = [[offset, length, blob_offset]], new bytes concatenated in blob."""
    runs, blob = [], bytearray()
    n = len(new)
    common = min(len(old), n)
    i = 0
    while i < n:
        if i < common and old[i] == new[i]:
            i += 1
            continue
        start = i
        last = i
        while i < n:
            if i >= common or old[i] != new[i]:
                last = i
                i += 1
            elif i - last > gap:
                break
            else:
                i += 1
        end = last + 1
        runs.append([start, end - start, len(blob)])
        blob += new[start:end]
    return runs, bytes(blob)


def apply_delta(old, d, blob):
    """d: {'old_sha256','new_sha256','new_len','runs'} -> new bytes (checked)."""
    if sha(old) != d['old_sha256']:
        raise PatchError('original data does not match')
    buf = bytearray(old[:d['new_len']])
    buf += b'\0' * (d['new_len'] - len(buf))
    for off, ln, bo in d['runs']:
        buf[off:off + ln] = blob[bo:bo + ln]
    out = bytes(buf)
    if sha(out) != d['new_sha256']:
        raise PatchError('rebuilt data checksum mismatch')
    return out


# ------------------------------------------------------------------ patch set

class PatchSet:
    """data/patchdata.json + data/patchdata.bin."""

    def __init__(self, folder):
        with open(os.path.join(folder, 'patchdata.json')) as f:
            self.meta = json.load(f)
        with open(os.path.join(folder, 'patchdata.bin'), 'rb') as f:
            self.blob = f.read()
        if sha(self.blob) != self.meta['blob_sha256']:
            raise PatchError('patchdata.bin is damaged (checksum mismatch)')

    def groups(self):
        return self.meta['groups']

    def items(self, archive, groups):
        return [it for it in self.meta['archives'][archive]['items'] if it['group'] in groups]

    def archives(self):
        return list(self.meta['archives'])

    def delta_bytes(self, d):
        return self.blob[d['blob_offset']:d['blob_offset'] + d['blob_len']]


def _record_state(rec_decoded, d):
    h = sha(rec_decoded)
    return 'original' if h == d['old_sha256'] else 'patched' if h == d['new_sha256'] else 'other'


def survey(game, ps, groups=None):
    """-> {archive: [(item, state, index_entry)]}; state original/patched/other/missing."""
    groups = groups or list(ps.groups())
    out = {}
    for arch in ps.archives():
        path = os.path.join(game, arch)
        items = ps.items(arch, groups)
        if not items:
            continue
        idx = read_index(path)
        res = []
        for it in items:
            ent = idx.get(it['key'])
            if ent is None:
                res.append((it, 'missing', None))
                continue
            blob = read_at(path, ent[1], ent[2])
            res.append((it, item_state(it, blob), ent))
        out[arch] = res
    return out


def item_state(it, blob):
    if it['kind'] == 'record':
        try:
            return _record_state(decode(blob), it['delta'])
        except (PatchError, zlib.error):
            return 'other'
    # pac: every listed entry must agree
    try:
        ents = {pac_name(n): b for n, _, b in pac_walk(blob)}
    except PatchError:
        return 'other'
    states = set()
    for e in it['entries']:
        b = ents.get(e['name'])
        if b is None:
            return 'other'
        try:
            states.add(_record_state(decode(b), e['delta']))
        except (PatchError, zlib.error):
            return 'other'
    return states.pop() if len(states) == 1 else 'other'


def build_item(ps, it, blob):
    """original blob -> new blob."""
    if it['kind'] == 'record':
        d = it['delta']
        return encode(apply_delta(decode(blob), d, ps.delta_bytes(d)))
    want = {e['name']: e['delta'] for e in it['entries']}
    ents, seen = [], set()
    for name256, th, b in pac_walk(blob):
        n = pac_name(name256)
        if n in want:
            d = want[n]
            b = encode(apply_delta(decode(b), d, ps.delta_bytes(d)))
            seen.add(n)
        ents.append((name256, th, b))
    if seen != set(want):
        raise PatchError('bundle %s is missing entries: %s' % (it['key'], sorted(set(want) - seen)))
    return pac_build(blob, ents)


def state_path(path):
    return path + STATE_SUFFIX


def _sync_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(json.dumps(obj, indent=1) + '\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def apply(game, ps, groups, log=print):
    """Install the given groups. Records another tool already patched are accepted as they are."""
    plan = {}
    for arch, res in survey(game, ps, groups).items():
        bad = [it['key'] for it, s, _ in res if s in ('other', 'missing')]
        if bad:
            raise PatchError('%s: %d record(s) hold data this tool does not know (%s...). '
                             'Is this the CUSA07651 v01.00 game, or did another mod change them? '
                             'Nothing was written.' % (arch, len(bad), ', '.join(bad[:3])))
        path = os.path.join(game, arch)
        todo = []
        for it, s, ent in res:
            if s == 'original':
                todo.append((it, ent, build_item(ps, it, read_at(path, ent[1], ent[2]))))
        done = len(res) - len(todo)
        log('%s: %d to install, %d already in place' % (arch, len(todo), done))
        if todo:
            plan[arch] = todo
    for arch, todo in plan.items():
        path = os.path.join(game, arch)
        sp = state_path(path)
        pre = os.path.getsize(path)
        st = json.load(open(sp)) if os.path.exists(sp) else {'pre_size': pre, 'entries': []}
        if os.path.exists(sp) and st.get('post_size') != pre:
            raise PatchError('%s changed size since the last install by this tool (another mod?). '
                             'Restore first.' % arch)
        pos = pre
        planned = []
        for it, ent, data in todo:
            planned.append({'key': it['key'], 'group': it['group'], 'index_pos': ent[0],
                            'offset': ent[1], 'size': ent[2], 'new_offset': pos, 'new_size': len(data)})
            pos += len(data)
        st['entries'].extend(planned)
        st['post_size'] = pos
        _sync_json(sp, st)                                   # 1. undo info first
        with open(path, 'r+b') as f:
            f.seek(pre)
            for _, _, data in todo:                         # 2. append
                f.write(data)
            f.flush()
            os.fsync(f.fileno())
            for p in planned:                               # 3. repoint
                f.seek(p['index_pos'] + 8)
                f.write(struct.pack('<II', p['new_offset'], p['new_size']))
            f.flush()
            os.fsync(f.fileno())
        log('%s: installed %d record(s), +%d bytes' % (arch, len(todo), pos - pre))
    verify(game, ps, groups, log)


def verify(game, ps, groups, log=print):
    ok = True
    for arch, res in survey(game, ps, groups).items():
        n = sum(1 for _, s, _ in res if s == 'patched')
        log('%s: %d/%d modded records in place' % (arch, n, len(res)))
        ok &= n == len(res)
    if not ok:
        raise PatchError('verification failed')
    return ok


def restore(game, ps, log=print):
    """Undo everything this tool installed (all groups)."""
    for arch in ps.archives():
        path = os.path.join(game, arch)
        sp = state_path(path)
        if not os.path.exists(sp):
            log('%s: nothing of ours to restore' % arch)
            continue
        st = json.load(open(sp))
        size = os.path.getsize(path)
        if size != st['post_size']:
            raise PatchError('%s is %d bytes, this tool left it at %d: something else changed it '
                             'afterwards. Undo that first.' % (arch, size, st['post_size']))
        idx = {v[0]: (v[1], v[2]) for v in read_index(path).values()}
        for e in st['entries']:
            if idx.get(e['index_pos']) not in ((e['new_offset'], e['new_size']), (e['offset'], e['size'])):
                raise PatchError('%s: index entry %s was changed by something else; refusing.' % (arch, e['key']))
        with open(path, 'r+b') as f:
            for e in st['entries']:
                f.seek(e['index_pos'] + 8)
                f.write(struct.pack('<II', e['offset'], e['size']))
            f.flush()
            os.fsync(f.fileno())
            f.truncate(st['pre_size'])
            f.flush()
            os.fsync(f.fileno())
        os.replace(sp, sp + '.used')
        log('%s: restored %d record(s), size back to %d' % (arch, len(st['entries']), st['pre_size']))


def installed_groups(game, ps):
    """-> {group: 'on'|'off'|'mixed'} from the live records."""
    res = {}
    for arch, items in survey(game, ps).items():
        for it, s, _ in items:
            res.setdefault(it['group'], set()).add(s)
    out = {}
    for g, states in res.items():
        out[g] = 'on' if states == {'patched'} else 'off' if states == {'original'} else 'mixed'
    return out
