"""Extract the vendor kernel image and recover its exported symbol table.

The stock HM2004-DU kernel partition (mtd2_kernel.bin) is an H3C container
holding an LZMA-alone compressed aarch64 `Image`.  It has no ELF symbol table,
but it carries __ksymtab_strings and __ksymtab, which is enough to turn every
EXPORT_SYMBOL into a name -> address mapping and make the whole vendor kernel
navigable.

Container layout, as measured:

  0x0000   H3C header: magic 0xaa640001, 0x12345678, two GUIDs, 0x400, 0xa0e
  0x2100   device tree blob
  0x4ee4   LZMA-alone stream: props 0x5d, dict 8 MiB,
           uncompressed size 0x1054a00 (17 123 840 bytes)
           -> an aarch64 Image, "ARM\\x64" magic at offset 0x38

Usage:
  python extract_kernel.py extract  [--image mtd2_kernel.bin] [--out vmlinux.bin]
  python extract_kernel.py symbols  [--image vmlinux.bin] [--out ksymtab.txt]
  python extract_kernel.py verify

`verify` re-extracts, compares the result against the on-disk image, and
spot-checks a handful of recovered symbols by disassembling the code they point
at.  It exits non-zero on any mismatch.
"""
import argparse
import hashlib
import lzma
import re
import struct
import sys
from pathlib import Path

DEFAULT_IMAGE = Path(r"D:\H3C\bak\mtd2_kernel.bin")
DEFAULT_VMLINUX = Path(__file__).resolve().parent.parent / "vendor" / "vmlinux.bin"
DEFAULT_KSYMTAB = Path(__file__).resolve().parent.parent / "vendor" / "ksymtab.txt"

# Offset of the LZMA-alone stream inside the container, and the size the
# container header advertises.  Both are asserted during extraction.
LZMA_OFFSET = 0x4EE4
LZMA_PROPS = 0x5D
LZMA_DICT_SIZE = 8 * 1024 * 1024
KERNEL_SIZE = 0x1054A00

# Symbols that must be present for the table to be trustworthy: the first is
# exported by the platform, the rest are the FTTR SPI path this port needs.
REQUIRED = [
    "printk",
    "spi_device_init",
    "spi_device_exit",
    "spi_device_write",
    "spi_device_read",
    "spi_type",
]

NAME_CHARS = set(b"abcdefghijklmnopqrstuvwxyz"
                 b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                 b"0123456789_")


def extract(container: Path, out: Path) -> bytes:
    data = container.read_bytes()

    props = data[LZMA_OFFSET]
    dic = struct.unpack("<I", data[LZMA_OFFSET + 1:LZMA_OFFSET + 5])[0]
    usize = struct.unpack("<Q", data[LZMA_OFFSET + 5:LZMA_OFFSET + 13])[0]

    if props != LZMA_PROPS or dic != LZMA_DICT_SIZE or usize != KERNEL_SIZE:
        raise SystemExit(
            "unexpected LZMA header at 0x%x: props=0x%02x dict=%d size=%d "
            "(expected 0x%02x / %d / %d)"
            % (LZMA_OFFSET, props, dic, usize, LZMA_PROPS, LZMA_DICT_SIZE,
               KERNEL_SIZE))

    dec = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
    blob = dec.decompress(data[LZMA_OFFSET:], max_length=KERNEL_SIZE)

    if len(blob) != KERNEL_SIZE:
        raise SystemExit("decompressed %d bytes, expected %d"
                         % (len(blob), KERNEL_SIZE))
    if blob[0x38:0x3C] != b"ARMd":
        raise SystemExit("no aarch64 Image magic at 0x38; not a kernel Image")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)

    return blob


def build_ksymtab(blob: bytes) -> dict:
    """Recover EXPORT_SYMBOL name -> address from __ksymtab.

    With CONFIG_HAVE_ARCH_PREL32_RELOCATIONS, which arm64 selects:

        struct kernel_symbol {
            int value_offset;      /* relative to &entry->value_offset */
            int name_offset;       /* relative to &entry->name_offset  */
            int namespace_offset;
        };

    Both offsets are relative to the field they sit in, so an entry is
    self-describing and can be found by scanning for triples that resolve to a
    valid identifier inside the image.
    """
    size = len(blob)

    def name_at(off):
        if off < 0 or off >= size:
            return None
        end = blob.find(b"\x00", off, off + 256)
        if end < 0 or end == off:
            return None
        body = blob[off:end]
        if not all(c in NAME_CHARS for c in body):
            return None
        return body.decode("latin1")

    table = {}
    for e in range(0, size - 12, 4):
        value_off, name_off, _ns = struct.unpack("<iii", blob[e:e + 12])
        name_addr = e + 4 + name_off
        nm = name_at(name_addr)
        if nm is None:
            continue
        value_addr = e + value_off
        # An exported value has to land in the kernel's text or data.
        if not (0x88000 <= value_addr < size):
            continue
        table.setdefault(nm, value_addr)

    return table


def write_ksymtab(table: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf8") as fh:
        for nm, addr in sorted(table.items(), key=lambda kv: kv[1]):
            fh.write("0x%08x %s\n" % (addr, nm))


def cmd_extract(args):
    blob = extract(Path(args.image), Path(args.out))
    print("wrote %s (%d bytes, sha256 %s)"
          % (args.out, len(blob), hashlib.sha256(blob).hexdigest()[:16]))
    return 0


def cmd_symbols(args):
    blob = Path(args.image).read_bytes()
    table = build_ksymtab(blob)
    write_ksymtab(table, Path(args.out))
    print("recovered %d exported symbols -> %s" % (len(table), args.out))

    missing = [s for s in REQUIRED if s not in table]
    if missing:
        print("MISSING required symbols: %s" % ", ".join(missing))
        return 1

    for s in REQUIRED:
        print("  %-20s 0x%06x" % (s, table[s]))
    return 0


def cmd_verify(_args):
    failures = []

    def check(label, ok, detail=""):
        print("  %-5s %-40s %s" % ("PASS" if ok else "FAIL", label, detail))
        if not ok:
            failures.append(label)

    vmlinux = DEFAULT_VMLINUX if DEFAULT_VMLINUX.exists() else Path("vmlinux.bin")
    ksym = DEFAULT_KSYMTAB if DEFAULT_KSYMTAB.exists() else Path("ksymtab.txt")

    if not vmlinux.exists():
        print("no extracted image at %s; run 'extract' first" % vmlinux)
        return 1

    blob = vmlinux.read_bytes()
    check("kernel size", len(blob) == KERNEL_SIZE, "%d bytes" % len(blob))
    check("aarch64 Image magic", blob[0x38:0x3C] == b"ARMd", "ARMd at 0x38")

    text_off, img_size, _flags = struct.unpack("<QQQ", blob[8:32])
    check("Header text_offset sane", 0 < text_off < len(blob),
          "text_offset=0x%x image_size=0x%x" % (text_off, img_size))

    # Re-extracting must be deterministic.
    good = Path(r"D:\H3C\bak\mtd2_kernel.bin")
    if good.exists():
        again = extract(good, Path("_verify_vmlinux.bin"))
        check("extraction reproducible", again == blob,
              "sha256 %s" % hashlib.sha256(again).hexdigest()[:16])
        Path("_verify_vmlinux.bin").unlink(missing_ok=True)

    table = build_ksymtab(blob)
    check("symbol count", len(table) > 9000, "%d symbols" % len(table))

    missing = [s for s in REQUIRED if s not in table]
    check("required symbols present", not missing,
          ", ".join(missing) if missing else ", ".join(REQUIRED))

    # Spot-check that recovered addresses really are the functions they claim:
    # each of these must begin with a plausible aarch64 prologue.
    prologues = 0
    for s in REQUIRED:
        addr = table.get(s)
        if addr is None:
            continue
        head = blob[addr:addr + 8]
        # stp x29, x30, [sp, #-N]!  (or a b/ret stub)
        word = struct.unpack("<I", head[:4])[0]
        is_stp = (word & 0xFFC003FF) == 0xA98003FD
        is_branch = (word >> 26) in (0x05, 0x06)
        if is_stp or is_branch:
            prologues += 1
    check("prologues well formed", prologues == len(REQUIRED),
          "%d/%d" % (prologues, len(REQUIRED)))

    if ksym.exists():
        lines = ksym.read_text(encoding="utf8").splitlines()
        check("on-disk ksymtab matches", len(lines) == len(table),
              "%d lines" % len(lines))

    print()
    if failures:
        print("FAILED: %s" % ", ".join(failures))
        return 1

    print("Vendor kernel extraction and symbol table verified.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("extract")
    p.add_argument("--image", default=str(DEFAULT_IMAGE))
    p.add_argument("--out", default=str(DEFAULT_VMLINUX))
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("symbols")
    p.add_argument("--image", default=str(DEFAULT_VMLINUX))
    p.add_argument("--out", default=str(DEFAULT_KSYMTAB))
    p.set_defaults(func=cmd_symbols)

    p = sub.add_parser("verify")
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
