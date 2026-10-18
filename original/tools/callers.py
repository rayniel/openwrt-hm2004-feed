"""List the callers of a function in the vendor image.

Complements find_refs.py: that one resolves data references (ADRP+ADD), this
one resolves direct calls (BL) and reports the enclosing exported symbol.

Caveat, same as find_refs.py: the enclosing symbol is the nearest *exported*
one at or below the call site, so a call inside a static function is attributed
to the preceding export.  Treat the label as approximate for statics.

Usage:  python callers.py <hex-target> [...]
"""
import re
import struct
import sys

IMAGE = r"D:\H3C\fttr-port\vendor\vmlinux.bin"
KSYM = r"D:\H3C\fttr-port\vendor\ksymtab.txt"

data = open(IMAGE, "rb").read()

syms = []
for line in open(KSYM, encoding="utf8"):
    a, n = line.split()
    syms.append((int(a, 16), n))
syms.sort()
addrs = [a for a, _ in syms]


def owner(addr):
    lo, hi, best = 0, len(addrs) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if addrs[mid] <= addr:
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    if best is None:
        return "(none)"
    a, n = syms[best]
    return "%s+0x%x" % (n, addr - a)


for arg in sys.argv[1:]:
    target = int(arg, 0)
    hits = []
    for off in range(0, len(data) - 4, 4):
        w = struct.unpack_from("<I", data, off)[0]
        if (w >> 26) != 0x25:            # BL
            continue
        imm = w & 0x03FFFFFF
        if imm & 0x02000000:
            imm -= 0x04000000
        if off + imm * 4 == target:
            hits.append(off)

    print("callers of 0x%x: %d" % (target, len(hits)))
    owners = {}
    for h in hits:
        owners.setdefault(owner(h), []).append(h)
    for name, sites in sorted(owners.items()):
        print("   %-34s %s" % (name, ", ".join("0x%x" % s for s in sites[:6])))
    print()
