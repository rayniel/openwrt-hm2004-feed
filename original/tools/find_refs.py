"""Find every function that references a given .rodata address.

Scans the image for the ADRP+ADD pair that materialises a target address, which
is how aarch64 reaches a string literal, and reports the containing function by
matching the site against the recovered symbol table.

Usage:  python find_refs.py <hex-address> [context-bytes]
"""
import re
import struct
import sys

IMAGE = r"D:\H3C\fttr-port\vendor\vmlinux.bin"
KSYM = r"D:\H3C\fttr-port\vendor\ksymtab.txt"

target = int(sys.argv[1], 0)
context = int(sys.argv[2], 0) if len(sys.argv) > 2 else 64

data = open(IMAGE, "rb").read()

# name -> address, and the reverse for "nearest preceding symbol".
syms = []
for line in open(KSYM, encoding="utf8"):
    a, n = line.split()
    syms.append((int(a, 16), n))
syms.sort()
addrs = [a for a, _ in syms]


def owner(addr):
    """Nearest exported symbol at or before addr, with the offset."""
    lo, hi = 0, len(addrs) - 1
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if addrs[mid] <= addr:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        return "(no symbol below)"
    a, n = syms[best]
    return "%s+0x%x" % (n, addr - a)


hits = []
for off in range(0, len(data) - 8, 4):
    w = struct.unpack_from("<I", data, off)[0]
    # ADRP Xd, #imm
    if (w & 0x9F000000) != 0x90000000:
        continue
    rd = w & 0x1F
    immlo = (w >> 29) & 0x3
    immhi = (w >> 5) & 0x7FFFF
    imm = (immhi << 2) | immlo
    if imm & (1 << 20):
        imm -= 1 << 21
    page = (off & ~0xFFF) + (imm << 12)

    # next instruction: ADD Xd, Xd, #imm12  (or ADD Xd, Xn, #imm12 with Xn == Xd)
    w2 = struct.unpack_from("<I", data, off + 4)[0]
    if (w2 & 0xFF000000) != 0x91000000:
        continue
    rn = (w2 >> 5) & 0x1F
    rd2 = w2 & 0x1F
    if rn != rd or rd2 != rd:
        continue
    imm12 = (w2 >> 10) & 0xFFF
    if page + imm12 == target:
        hits.append(off)

print("references to 0x%x: %d" % (target, len(hits)))
for h in hits:
    print("  0x%06x   in %s" % (h, owner(h)))
    lo = max(0, h - context)
    print("      bytes before: %s" % data[lo:h].hex())
