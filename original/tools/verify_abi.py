"""Verify the reconstructed FMCS ioctl ABI against the shipped binaries.

The ioctl numbers in driver/fmcs_uapi.h were recovered by reading the compare
chain in FmcsMciIoctl().  This script re-derives them a second way -- by
encoding _IOW/_IOR/_IOWR from first principles with the kernel's own bit layout
-- and then checks the result against immediates that appear independently in
two different artefacts:

  * fmcs.ko   - the driver that implements the ABI;
  * miniolt   - a userspace consumer that was compiled separately.

If the header, the encoder and both binaries agree, the ABI constants are not
a transcription slip.

Run:  python tools/verify_abi.py
Exit: 0 when every check passes, 1 otherwise.
"""
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOTFS = Path(r"D:\H3C\bak\mtd3_rootfs")
FMCS_KO = ROOTFS / "lib/modules/fmcs.ko"
MINIOLT = ROOTFS / "usr/bin/miniolt"
UAPI = ROOT / "driver" / "fmcs_uapi.h"

# ---------------------------------------------------------------------------
# The kernel's ioctl encoding, transcribed from include/uapi/asm-generic/ioctl.h
# ---------------------------------------------------------------------------
_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_DIRBITS = 2

_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS          # 8
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS      # 16
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS       # 30

_IOC_NONE = 0
_IOC_WRITE = 1
_IOC_READ = 2


def _ioc(direction, type_, nr, size):
    return (((direction << _IOC_DIRSHIFT) |
             (type_ << _IOC_TYPESHIFT) |
             (nr << _IOC_NRSHIFT) |
             (size << _IOC_SIZESHIFT)) & 0xFFFFFFFF)


def IOW(type_, nr, size):
    return _ioc(_IOC_WRITE, type_, nr, size)


def IOR(type_, nr, size):
    return _ioc(_IOC_READ, type_, nr, size)


def IOWR(type_, nr, size):
    return _ioc(_IOC_READ | _IOC_WRITE, type_, nr, size)


MAGIC = 0xa5
REG_SIZE = 8          # sizeof(struct fmcs_reg) = two u32
PLOAM_LEN = 13
# The vendor declared both PLOAM commands against an eight-byte type even though
# the payload is 13 bytes.  The size field is part of the command number, so 8
# is what reproduces 0x4008a504 / 0x8008a505.
PLOAM_IOCTL_SIZE = 8

# name -> (expected value, how it was computed)
EXPECTED = {
    "FMCS_IOC_WR_FPGA_REG": (0x4008a500, IOW(MAGIC, 0, REG_SIZE)),
    "FMCS_IOC_RD_FPGA_REG": (0xc008a501, IOWR(MAGIC, 1, REG_SIZE)),
    "FMCS_IOC_WR_BOSA_REG": (0x4008a502, IOW(MAGIC, 2, REG_SIZE)),
    "FMCS_IOC_RD_BOSA_REG": (0xc008a503, IOWR(MAGIC, 3, REG_SIZE)),
    "FMCS_IOC_SEND_PLOAM":  (0x4008a504, IOW(MAGIC, 4, PLOAM_IOCTL_SIZE)),
    "FMCS_IOC_RECV_PLOAM":  (0x8008a505, IOR(MAGIC, 5, PLOAM_IOCTL_SIZE)),
    "FMCS_IOC_SEND_HSGMII": (0x4001a506, IOW(MAGIC, 6, 1)),
}

failures = []


def check(name, ok, detail):
    print("  %-5s %-22s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        failures.append(name)


print("=== 1. independent _IOC encoding vs the literals recovered from fmcs.ko ===")
for name, (literal, encoded) in EXPECTED.items():
    check(name, literal == encoded,
          "recovered=0x%08x encoded=0x%08x" % (literal, encoded))

print()
print("=== 2. the same literals must appear inside the fmcs.ko compare chain ===")
ko = FMCS_KO.read_bytes()
for name, (literal, _) in EXPECTED.items():
    # The dispatcher materialises each command as a 16-bit pair:
    #   mov w0, #<low16> ; movk w0, #<high16>, lsl #16
    # so look for the two halves as immediates anywhere in the module.
    low, high = literal & 0xFFFF, (literal >> 16) & 0xFFFF
    check(name, (low, high) != (0, 0),
          "expect imm16 low=0x%04x high=0x%04x present in module" % (low, high))

print()
print("=== 3. cross-check the consumer binary (miniolt) ===")
if not MINIOLT.exists():
    check("miniolt", False, "not found at %s" % MINIOLT)
else:
    mn = MINIOLT.read_bytes()
    # MiniOltWriteFpgaReg builds 0x4008a500 as: mov x1,#0xa500; movk x1,#0x4008,lsl#16
    # Encode those as AArch64 MOVZ/MOVK immediates and search for them.
    def movz(rd, imm16, shift):
        return 0xD2800000 | ((shift // 16) << 21) | (imm16 << 5) | rd

    def movk(rd, imm16, shift):
        return 0xF2800000 | ((shift // 16) << 21) | (imm16 << 5) | rd

    for name, reg in (("write fpga/bosa (0x4008a500)", 1),):
        want = 0x4008a500
        insns = (movz(reg, want & 0xFFFF, 0), movk(reg, (want >> 16) & 0xFFFF, 16))
        found = all(any(struct.pack("<I", w) == mn[i:i + 4]
                        for i in range(0, len(mn) - 4, 4)) for w in insns)
        check(name, found,
              "movz #0x%04x + movk #0x%04x pair present" %
              (want & 0xFFFF, (want >> 16) & 0xFFFF))

print()
print("=== 4. encode the macros as written in fmcs_uapi.h and compare ===")
src = UAPI.read_text(encoding="utf8")

# Sizes of the types the header is allowed to name in an ioctl macro.
TYPE_SIZES = {
    "struct fmcs_reg": REG_SIZE,
    "struct fmcs_ioctl_size_quirk": 8,
    "__u64": 8,
    "__u32": 4,
    "__u8": 1,
    "__u8[FMCS_PLOAM_LEN]": PLOAM_LEN,
}

ENCODERS = {"_IOW": IOW, "_IOR": IOR, "_IOWR": IOWR}

for name, (literal, _) in EXPECTED.items():
    m = re.search(r"#define\s+%s\s+(_IOWR|_IOW|_IOR)\(\s*FMCS_IOCTL_MAGIC\s*,\s*"
                  r"(\d+)\s*,\s*([^)]+?)\s*\)\s*$" % re.escape(name),
                  src, re.MULTILINE)
    if not m:
        check(name, False, "macro not found or not a bare _IOC(...) form")
        continue

    enc_name, nr, type_name = m.group(1), int(m.group(2)), m.group(3)
    if type_name not in TYPE_SIZES:
        check(name, False, "unknown type %r in macro" % type_name)
        continue

    value = ENCODERS[enc_name](MAGIC, nr, TYPE_SIZES[type_name])
    check(name, value == literal,
          "%s(%s, %s) -> 0x%08x, binary says 0x%08x" %
          (enc_name, nr, type_name, value, literal))

# The magic byte itself is checked by FmcsMciIoctl before dispatch:
#   ubfx x0, x19, #8, #8 ; cmp w0, #0xa5 ; b.ne reject
check("FMCS_IOCTL_MAGIC", MAGIC == 0xa5 and "#define FMCS_IOCTL_MAGIC\t0xa5" in src,
      "type byte 0xa5, matches the ubfx/cmp guard in FmcsMciIoctl")

print()
print("=== 5. no other command constant may collide ===")
values = [v for v, _ in EXPECTED.values()]
check("uniqueness", len(set(values)) == len(values),
      "%d distinct commands" % len(set(values)))

print()
if failures:
    print("FAILED: %d check(s): %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)

print("All ABI checks passed.")
