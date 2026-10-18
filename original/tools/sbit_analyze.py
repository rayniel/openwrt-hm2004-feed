#!/usr/bin/env python3
"""Structural analyser for Pango Microsystems `.sbit` FPGA configuration files.

Usage:
    python sbit_analyze.py <path-to-sbit> [--dump-bytes N] [--section LIST]
    python sbit_analyze.py FTTR_TOP.sbit
    python sbit_analyze.py FTTR_TOP.sbit --section header,tlv,map
    python sbit_analyze.py FTTR_TOP.sbit --section all

Sections: overview, header, tlv, stats, runs, markers, align, map, auto
(default: all).  Runs on the standard library alone; numpy is used only to
speed up byte autocorrelation when available.

Evidence produced per section:
  overview  file size, bit count, divisibility, first/last non-zero byte
  header    hex+ASCII dump of the first N bytes (default 256)
  tlv       parse of the vendor signature + tag/len/value ASCII records
  stats     byte histogram, entropy, bit density, popcount-vs-i.i.d. test
  runs      maximal runs of 0x00 and 0xFF
  markers   offsets/spacing of recurring byte patterns
  align     byte-histogram and count tests for 4-byte / 8-byte word framing
  map       per-64 KiB region table (zeros %, 0xFF %, bit density, distinct)
  auto      byte autocorrelation over the strongest lags
"""

from __future__ import annotations

import argparse
import collections
import math
import sys

DEFAULT_DUMP = 256
SECTION_NAMES = ("overview", "header", "tlv", "stats", "runs",
                 "markers", "align", "map", "auto")

TLV_TAG_NAMES = {
    0x61: "project name",
    0x62: "device / part",
    0x63: "build date",
    0x64: "build time",
    0x65: "tool name",
    0x66: "tool version",
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def hexdump(buf: bytes, base: int = 0, width: int = 16) -> str:
    """Return a classic `offset  hex  |ascii|` dump of `buf`."""
    out = []
    for i in range(0, len(buf), width):
        chunk = buf[i:i + width]
        h = " ".join(f"{b:02x}" for b in chunk)
        a = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append(f"{base + i:08x}  {h:<{width * 3 - 1}}  |{a}|")
    return "\n".join(out)


def popcount_bytes(buf: bytes) -> int:
    """Number of set bits in `buf`."""
    return sum(bin(b).count("1") for b in buf)


def entropy(counts: collections.Counter, total: int) -> float:
    """Shannon entropy in bits per byte for a byte histogram."""
    return -sum((n / total) * math.log2(n / total) for n in counts.values() if n)


def runs_of(buf: bytes, value: int, min_len: int = 1):
    """Yield (offset, length) for maximal runs of `value` at least `min_len` long."""
    n = len(buf)
    i = 0
    while i < n:
        if buf[i] == value:
            j = i
            while j < n and buf[j] == value:
                j += 1
            if j - i >= min_len:
                yield i, j - i
            i = j
        else:
            i += 1


def find_all(hay: bytes, needle: bytes, limit: int = 200000):
    """Return every offset at which `needle` occurs in `hay`."""
    out = []
    i = 0
    while True:
        j = hay.find(needle, i)
        if j < 0 or len(out) >= limit:
            return out
        out.append(j)
        i = j + 1


def spacing_summary(offsets):
    """Return (min, median, max) spacing of an offset list, or None."""
    if len(offsets) < 2:
        return None
    d = sorted(offsets[i + 1] - offsets[i] for i in range(len(offsets) - 1))
    return d[0], d[len(d) // 2], d[-1]


def is_command_word(w: bytes) -> bool:
    """True for the `aX ?? 00 0[01]` word shape seen throughout the payload.

    Excludes the all-`a0` fill word, which matches the shape but is a filler.
    """
    return (len(w) == 4 and (w[0] >> 4) == 0xA and w[2] == 0x00
            and w[3] in (0, 1) and w != b"\xa0\x00\x00\x00")


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------

def sec_overview(raw: bytes) -> None:
    n = len(raw)
    print(f"file size          : {n} bytes (0x{n:X}) = {n * 8} bits")
    print(f"divisible by 2/4/8/16: {n % 2 == 0}/{n % 4 == 0}/{n % 8 == 0}/{n % 16 == 0}")
    nz = [i for i, b in enumerate(raw) if b]
    if nz:
        print(f"first non-zero byte : 0x{nz[0]:X} (0x{raw[nz[0]]:02x})")
        print(f"last  non-zero byte : 0x{nz[-1]:X} (0x{raw[nz[-1]]:02x})")
        print(f"leading zero prefix : {nz[0]} bytes")
        print(f"trailing zero suffix: {n - 1 - nz[-1]} bytes")


def sec_header(raw: bytes, dump_bytes: int) -> None:
    print(f"--- first {dump_bytes} bytes ---")
    print(hexdump(raw[:dump_bytes]))


def sec_tlv(raw: bytes) -> None:
    print("--- header signature + tag/length/value records ---")
    print("preamble 0x00..0x0a : " + raw[0:0x0b].hex(" "))
    # vendor signature string
    i = 0x0B
    j = raw.index(b"\x00", i)
    print(f"0x{i:02x}..0x{j:02x}        : ASCII {raw[i:j]!r} + NUL")
    o = j + 1

    print(f"0x{o:02x}              : lone byte 0x{raw[o]:02x}")
    o += 1

    records = []
    while o + 3 <= len(raw):
        tag = raw[o]
        ln = int.from_bytes(raw[o + 1:o + 3], "big")
        val = raw[o + 3:o + 3 + ln]
        sane = (3 + ln <= len(raw)
                and len(val) > 0
                and val[-1] == 0
                and all((32 <= b < 127) or b == 0 for b in val))
        if not sane:
            print(f"0x{o:02x}              : STOP - tag=0x{tag:02x} "
                  f"len=0x{ln:04x} is not a NUL-terminated ASCII value")
            break
        records.append((o, tag, ln, val))
        print(f"0x{o:02x}..0x{o + 3 + ln - 1:02x}      : tag=0x{tag:02x} "
              f"({TLV_TAG_NAMES.get(tag, '?')}) len={ln:3d} "
              f"value={val[:-1]!r}")
        o += 3 + ln

    print(f"payload-shaped bytes from 0x{o:02x}: {raw[o:o + 6].hex(' ')} ...")
    if records:
        print(f"parsed {len(records)} records ending at 0x{o:X}")


def sec_stats(raw: bytes) -> None:
    n = len(raw)
    c = collections.Counter(raw)
    print(f"byte entropy        : {entropy(c, n):.3f} bits/byte")
    print(f"distinct byte values: {len(c)}/256")
    print(f"zeros               : {c[0]} ({100 * c[0] / n:.2f}%)")
    print(f"0xFF                : {c[255]} ({100 * c[255] / n:.3f}%)")
    print(f"bit density         : {100 * popcount_bytes(raw) / (8 * n):.3f}% ones")
    print("top 12 byte values  :")
    for b, v in c.most_common(12):
        print(f"    0x{b:02x} {v:9d} {100 * v / n:7.3f}%")

    print("\npopcount per byte vs. i.i.d. model (whole file):")
    pc = collections.Counter(bin(b).count("1") for b in raw)
    p = sum(k * v for k, v in pc.items()) / (8 * n)
    print(f"    implied i.i.d. p = {p:.4f}")
    print(f"    {'k':>3} {'observed':>10} {'observed%':>10} {'iid%':>10} {'ratio':>8}")
    for k in range(9):
        obs = pc[k]
        f_obs = obs / n
        f_iid = math.comb(8, k) * (p ** k) * ((1 - p) ** (8 - k))
        ratio = f_obs / f_iid if f_iid else float("inf")
        print(f"    {k:3d} {obs:10d} {100 * f_obs:9.4f}% {100 * f_iid:9.4f}% {ratio:8.2f}")


def sec_runs(raw: bytes) -> None:
    for value, name, minlen in ((0x00, "0x00", 64), (0xFF, "0xFF", 4)):
        print(f"--- maximal runs of {name} (>= {minlen} bytes) ---")
        found = list(runs_of(raw, value, minlen))
        print(f"    count: {len(found)}")
        for off, ln in sorted(found, key=lambda t: -t[1])[:15]:
            print(f"    {off:#08x}..{off + ln - 1:#08x}  len={ln:8d} "
                  f"({100 * ln / len(raw):6.3f}% of file)")
        if not found:
            print("    (none)")


MARKERS = [
    (b"\x0f\xf0", "0f f0"),
    (b"\xf0\x0f", "f0 0f"),
    (b"\x0f\xf0\x0f\xf0\x0f\xf0\x0f\xf0", "0f f0 x4 (8-byte)"),
    (b"\x00\x09", "00 09"),
    (b"\x00\x09\x0f\xf0", "00 09 0f f0"),
    (b"\xa0\x00\x00\x00", "a0 00 00 00 (fill word)"),
    (b"\xff\xff\xff\xff", "ff ff ff ff"),
    (b"\x00\x00\x00\x00", "00 00 00 00"),
]


def sec_markers(raw: bytes) -> None:
    print("--- recurring byte patterns ---")
    for pat, name in MARKERS:
        offs = find_all(raw, pat, limit=1000000)
        sp = spacing_summary(offs)
        head = " ".join(f"{o:#x}" for o in offs[:8])
        line = f"  {name:26s} count={len(offs):8d}  first: {head}"
        if sp:
            line += f"  | spacing min={sp[0]} med={sp[1]} max={sp[2]}"
        print(line)


def sec_align(raw: bytes) -> None:
    n = len(raw)
    print("--- 4-byte / 8-byte word framing tests (payload) ---")
    print("A 32-bit big-endian word stream should show:")
    print("  * the fill word a0 00 00 00 concentrated on one offset-mod-4 phase")
    print("  * command words aX ?? 00 0[01] concentrated on one offset-mod-8 phase")

    print("\n[1] occurrences of 'a0 00 00 00' by offset % 4")
    counts = [sum(1 for o in range(m, n - 3, 4)
                  if raw[o:o + 4] == b"\xa0\x00\x00\x00") for m in range(4)]
    for m in range(4):
        print(f"    offset%4=={m}: {counts[m]:6d}")
    if min(counts) > 0:
        print(f"    peak/floor ratio = {max(counts) / min(counts):.2f}x")

    print("\n[2] command words 'aX ?? 00 0[01]' by offset % 8")
    cmd = [0, 0, 0, 0, 0, 0, 0, 0]
    words = [0, 0, 0, 0, 0, 0, 0, 0]
    for o in range(0, n - 8, 4):
        m = o % 8
        words[m] += 1
        if is_command_word(raw[o:o + 4]):
            cmd[m] += 1
    for m in range(8):
        if words[m]:
            print(f"    offset%8=={m}: words={words[m]:7d} commands={cmd[m]:6d}")
    even, odd = cmd[0], cmd[4]
    if even + odd:
        print(f"    commands at %8==0 : %8==4 = {even} : {odd} "
              f"({100 * even / (even + odd):.1f}% : {100 * odd / (even + odd):.1f}%)")
        print(f"    total command words: {even + odd}")

    print("\n[3] fill word a0 00 00 00 by offset % 8")
    f = [0] * 8
    for o in range(0, n - 4, 4):
        if raw[o:o + 4] == b"\xa0\x00\x00\x00":
            f[o % 8] += 1
    for m in range(8):
        if f[m]:
            print(f"    offset%8=={m}: {f[m]:6d}")

    print("\n[4] alternative encodings of the fill word (falsification test)")
    for pat, name in ((b"\x05\x00\x00\x00", "bit-reversed a0"),
                      (b"\x0a\x00\x00\x00", "nibble-swapped a0"),
                      (b"\x00\x00\x00\xa0", "byte-reversed a0")):
        offs = find_all(raw, pat)
        print(f"    {name:20s}: {len(offs)} occurrences")


def sec_map(raw: bytes, bucket: int = 0x10000) -> None:
    n = len(raw)
    print(f"--- macro map, {bucket:#x}-byte buckets ---")
    print(f"  {'range':>19} {'size':>8} {'zeros%':>8} {'0xff%':>7} "
          f"{'bitdens%':>9} {'distinct':>9}")
    for b0 in range(0, n, bucket):
        seg = raw[b0:b0 + bucket]
        if not seg:
            break
        c = collections.Counter(seg)
        zeros = 100 * c[0] / len(seg)
        ff = 100 * c[255] / len(seg)
        dens = 100 * popcount_bytes(seg) / (8 * len(seg))
        print(f"  {b0:#08x}-{b0 + len(seg) - 1:#08x} {len(seg):8d} "
              f"{zeros:8.2f} {ff:7.3f} {dens:9.3f} {len(c):9d}")


def sec_auto(raw: bytes, sample: int = 262144) -> None:
    seg = raw[:sample]
    print(f"--- byte autocorrelation, first {len(seg)} bytes ---")
    try:
        import numpy as np
        s = np.frombuffer(seg, dtype=np.uint8).astype(np.float64)
    except ImportError:
        s = None
    lags = list(range(1, 33)) + [48, 64, 128, 256]
    results = []
    if s is not None:
        g = s.mean()
        s = s - g
        den = float((s * s).sum())
        for lag in lags:
            if lag >= len(seg):
                continue
            r = float((s[:-lag] * s[lag:]).sum()) / den
            results.append((lag, r))
    else:
        mean = sum(seg) / len(seg)
        for lag in lags:
            if lag >= len(seg):
                continue
            num = 0.0
            m = len(seg) - lag
            for i in range(m):
                num += (seg[i] - mean) * (seg[i + lag] - mean)
            den = sum((b - mean) ** 2 for b in seg)
            results.append((lag, num / den if den else 0.0))
    for lag, r in results:
        print(f"    lag={lag:4d}  r={r:+.5f}")
    top = sorted(results, key=lambda t: -abs(t[1]))[:5]
    print("    strongest lags: " + ", ".join(f"{l}({r:+.3f})" for l, r in top))


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def run(path: str, dump_bytes: int, sections) -> None:
    with open(path, "rb") as fh:
        raw = fh.read()
    print(f"=== {path} ===")
    print()
    for name in SECTION_NAMES:
        if name not in sections:
            continue
        print(f"########## {name.upper()} ##########")
        if name == "overview":
            sec_overview(raw)
        elif name == "header":
            sec_header(raw, dump_bytes)
        elif name == "tlv":
            sec_tlv(raw)
        elif name == "stats":
            sec_stats(raw)
        elif name == "runs":
            sec_runs(raw)
        elif name == "markers":
            sec_markers(raw)
        elif name == "align":
            sec_align(raw)
        elif name == "map":
            sec_map(raw)
        elif name == "auto":
            sec_auto(raw)
        print()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Structural analysis of a Pango Microsystems .sbit file.")
    ap.add_argument("path", help="path to the .sbit file")
    ap.add_argument("--dump-bytes", type=int, default=DEFAULT_DUMP,
                    help=f"bytes to hex-dump in the header section (default {DEFAULT_DUMP})")
    ap.add_argument("--section", default="all",
                    help="comma-separated sections, or 'all' (default). "
                         "choices: " + ",".join(SECTION_NAMES))
    args = ap.parse_args(argv)

    if args.section.strip().lower() == "all":
        sections = set(SECTION_NAMES)
    else:
        sections = {s.strip().lower() for s in args.section.split(",") if s.strip()}
        unknown = sections - set(SECTION_NAMES)
        if unknown:
            ap.error(f"unknown section(s): {', '.join(sorted(unknown))}")

    try:
        run(args.path, args.dump_bytes, sections)
    except FileNotFoundError:
        print(f"error: no such file: {args.path}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: cannot read {args.path}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
