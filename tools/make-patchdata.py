#!/usr/bin/env python3
"""DEVELOPER TOOL (not shipped in the AppImage): build data/patchdata.{json,bin}.

Reads the ORIGINAL archives of a CUSA07651 v01.00 dump plus the existing mod folders in
GB3-Port-Scope, and stores only the byte runs that each mod changes (our generated art and
constants). Every delta records the sha256 of the original decoded record, so the installer only
rebuilds records from the player's own matching files.

    python3 tools/make-patchdata.py --a000 <pristine GxArchivedFile000.dat> \
        --a001 <pristine GxArchivedFile001.dat> --scope <GB3-Port-Scope> --out data
"""
import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app'))
from gb3r import gdat  # noqa: E402

A000 = 'masterPS4/GxArchivedFile000.dat'
A001 = 'masterPS4/GxArchivedFile001.dat'


class Builder:
    def __init__(self):
        self.blob = bytearray()
        self.stats = {'changed': 0, 'records': 0}

    def delta(self, old, new):
        runs, b = gdat.make_delta(old, new)
        d = {'old_sha256': gdat.sha(old), 'new_sha256': gdat.sha(new), 'new_len': len(new),
             'blob_offset': len(self.blob), 'blob_len': len(b),
             'runs': [[o, n, bo] for o, n, bo in runs]}
        self.blob += b
        self.stats['changed'] += len(b)
        self.stats['records'] += 1
        # self-check
        got = gdat.apply_delta(old, d, bytes(self.blob[d['blob_offset']:]))
        assert got == new
        return d


def shader_patch(rec, data):
    buf = bytearray(data)
    for e in rec['edits']:
        a = int(e['offset'], 16)
        if struct.unpack_from('<I', buf, a)[0] != int(e['old'], 16):
            raise SystemExit('%s: unexpected bytes at %#x' % (rec['key'], a))
        struct.pack_into('<I', buf, a, int(e['new'], 16))
    for off, h in rec['shader_hash_bumped']:
        o = int(off, 16)
        assert buf[o:o + 7] == b'OrbShdr' and struct.unpack_from('<Q', buf, o + 16)[0] == int(h, 16)
        struct.pack_into('<Q', buf, o + 16, int(h, 16) | (0x07200720 << 32))
    out = bytes(buf)
    assert gdat.sha(out) == rec['decoded_sha256_patched'], rec['key']
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--a000', required=True)
    ap.add_argument('--a001', required=True)
    ap.add_argument('--scope', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    scope = a.scope
    B = Builder()
    idx1 = gdat.read_index(a.a001)
    idx0 = gdat.read_index(a.a000)

    def orig1(key):
        e = idx1[key]
        return gdat.read_at(a.a001, e[1], e[2])

    items1, items0 = [], []
    seen = set()

    def add_record(key, group, label, newblob_or_dec, decoded=False):
        if key in seen:
            raise SystemExit('duplicate key %s' % key)
        seen.add(key)
        old = gdat.decode(orig1(key))
        new = newblob_or_dec if decoded else gdat.decode(newblob_or_dec)
        items1.append({'kind': 'record', 'key': key, 'group': group, 'label': label,
                       'delta': B.delta(old, new)})

    # Xbox font atlases (14 controller cells per font + Korean HUD chars)
    m = json.load(open(os.path.join(scope, 'xbox-texture-mod/manifest.json')))
    for t in m['textures']:
        add_record(t['key'], 'xbox', 'font atlas %s' % t['language'],
                   open(os.path.join(scope, 'xbox-texture-mod/textures', t['file']), 'rb').read())
    # Xbox controller diagrams, layout presets, blue EX prompts, JP/CN page-0 atlases
    m = json.load(open(os.path.join(scope, 'xbox-controller-mod/manifest.json')))
    for t in m['textures']:
        add_record(t['key'], 'xbox', t['file'].rsplit('-', 1)[0],
                   open(os.path.join(scope, 'xbox-controller-mod/textures', t['file']), 'rb').read())
    # Skill badges v2 (loose 001 copies + pac bundles in 000)
    mb = json.load(open(os.path.join(scope, 'xbox-skill-badge-mod/manifest.json')))
    for t in mb['textures']:
        add_record(t['key'], 'xbox', 'skill badge %s' % t['letter'],
                   open(os.path.join(scope, 'xbox-skill-badge-mod/textures', t['file']), 'rb').read())
    for p in mb['pacs']:
        e = idx0[p['key']]
        pb = gdat.read_at(a.a000, e[1], e[2])
        assert gdat.sha(pb) == p['original_sha256'], p['key']
        ents = {gdat.pac_name(n): b for n, _, b in gdat.pac_walk(pb)}
        out = []
        for ent in p['entries']:
            old = gdat.decode(ents[ent['name']])
            new = gdat.decode(open(os.path.join(scope, 'xbox-skill-badge-mod/textures', ent['file']), 'rb').read())
            out.append({'name': ent['name'], 'delta': B.delta(old, new)})
        items0.append({'kind': 'pac', 'key': p['key'], 'group': 'xbox', 'label': p['label'], 'entries': out})
    # 720p shader constants
    ms = json.load(open(os.path.join(scope, 'render-720p/shader-mod/manifest.json')))
    for rec in ms['records']:
        old = gdat.decode(orig1(rec['key']))
        assert gdat.sha(old[128:]) == rec['decoded_sha256_original'], rec['key']
        new = old[:128] + shader_patch(rec, old[128:])
        seen.add(rec['key'])
        items1.append({'kind': 'record', 'key': rec['key'], 'group': 'render720', 'label': rec['what'],
                       'delta': B.delta(old, new)})

    meta = {
        'version': 1,
        'title': 'CUSA07651', 'app_ver': '01.00',
        'groups': {
            'xbox': 'Xbox button glyphs, controller pictures, EX prompts and skill-slot badges',
            'render720': '720p render fix: shader constants (pairs with the GB3-render-720p.xml eboot patch)',
        },
        'archives': {
            A001: {'pristine_size': os.path.getsize(a.a001), 'items': items1},
            A000: {'pristine_size': os.path.getsize(a.a000), 'items': items0},
        },
        'blob_sha256': gdat.sha(bytes(B.blob)),
    }
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, 'patchdata.bin'), 'wb') as f:
        f.write(B.blob)
    with open(os.path.join(a.out, 'patchdata.json'), 'w') as f:
        json.dump(meta, f, indent=1)
    print('records %d, delta bytes %d, items 001=%d 000=%d' % (B.stats['records'], B.stats['changed'],
                                                               len(items1), len(items0)))
    for it in items1 + items0:
        ds = [it['delta']] if it['kind'] == 'record' else [e['delta'] for e in it['entries']]
        print('  %-5s %s %-40s new %8d  delta %8d  runs %d' % (
            it['group'][:5], it['key'], it['label'][:40], sum(d['new_len'] for d in ds),
            sum(d['blob_len'] for d in ds), sum(len(d['runs']) for d in ds)))


if __name__ == '__main__':
    main()
