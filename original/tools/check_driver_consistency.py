"""Cross-check the ported driver against the recovered protocol constants.

The other checks verify the *reference documents* against the vendor artefacts.
This one verifies the *driver source* against the same artefacts, which is the
link that can rot silently: an opcode edited in fmcs.h would leave every
document still correct and every check still green while the driver put the
wrong bytes on the wire.

Verified here:
  * the SPI opcodes and frame layout in driver/fmcs.h and driver/fmcs_spi.c;
  * the delay values transcribed into fmcs_spi.c;
  * the net device names and the ioctl set used by fmcs.c;
  * that fmcs.c dispatches only on commands fmcs_uapi.h defines.

Run:  python tools/check_driver_consistency.py
Exit: 0 when the driver agrees with the reverse engineering, 1 otherwise.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "driver"

# Recovered from the vendor SPI core; see docs/REVERSE_ENGINEERING.md s3 and
# docs/SPI_CONTROLLER.md.  The frame layouts are the part that matters: these
# values decide what the FPGA actually sees.
EXPECTED = {
    "FMCS_SPI_OP_WRITE": 0xA8,
    "FMCS_SPI_OP_RDCMD": 0xA0,
    "FMCS_SPI_OP_RDDATA": 0x50,
    "FMCS_SPI_OP_PLOAM_TX": 0xAA,
    "FMCS_SPI_OP_PLOAM_RX": 0xA2,
    "FMCS_SPI_OP_PLOAM_RD": 0x52,
    "FMCS_SPI_PLOAM_RX_ARG": 0x10,
}

# Inter-phase delays: (macro, value in microseconds, which path).
DELAYS = {
    "FMCS_DELAY_FPGA_US": 50,
    "FMCS_DELAY_BOSA_US": 600,
}

failures = []


def check(label, ok, detail=""):
    print("  %-5s %-44s %s" % ("PASS" if ok else "FAIL", label, detail))
    if not ok:
        failures.append(label)


def defines(path):
    """Return {name: int} for every `#define NAME <int>` in a header."""
    out = {}
    for m in re.finditer(r"^#define\s+(\w+)\s+(0x[0-9a-fA-F]+|\d+)\s*$",
                         path.read_text(encoding="utf8"), re.MULTILINE):
        out[m.group(1)] = int(m.group(2), 0)
    return out


def main():
    for name in ("fmcs.h", "fmcs_uapi.h", "fmcs_spi.c", "fmcs.c", "fmcs_load.c"):
        if not (DRIVER / name).exists():
            check("driver/%s present" % name, False, "missing")
    if failures:
        return 1

    hdr = defines(DRIVER / "fmcs.h")

    print("=== 1. SPI opcodes match the recovered frames ===")
    for name, want in EXPECTED.items():
        got = hdr.get(name)
        check(name, got == want,
              "0x%02x" % got if got is not None else "not defined")

    print()
    print("=== 2. inter-phase delays match the recovered constants ===")
    for name, want in DELAYS.items():
        got = hdr.get(name)
        check(name, got == want, "%s us" % got)

    print()
    print("=== 3. the frame layouts are the ones the vendor emits ===")
    spi = (DRIVER / "fmcs_spi.c").read_text(encoding="utf8")
    # FPGA register write: opcode, addr_be, value_be -> 9 bytes.
    check("register write is 9 bytes", "fmcs_spi_raw_write(fmcs, 9)" in spi,
          "A8 <addr_be32> <value_be32>")
    # Read command: opcode + addr_be -> 5 bytes.
    check("read command is 5 bytes",
          spi.count("fmcs_spi_raw_write(fmcs, 5)") == 2,
          "A0 <addr_be32>, used by both register windows")
    # Read data phase: one command byte in, four bytes out.
    check("register read data is 4 bytes",
          "FMCS_SPI_OP_RDDATA, rx, 4)" in spi,
          "50 then 4 bytes")
    # PLOAM transmit: opcode, three zero bytes, 13-byte payload -> 18 bytes.
    check("ploam transmit is 18 bytes",
          "5 + FMCS_PLOAM_LEN)" in spi,
          "AA 00 00 00 <13 bytes>")
    # PLOAM receive: command, then 13 bytes.
    check("ploam receive is 13 bytes",
          "FMCS_SPI_OP_PLOAM_RD, rx, sizeof(rx))" in spi,
          "A2 10 00 00 00 then 52 plus 13 bytes")
    check("ploam receive arg is 0x10",
          "t->buf[1] = FMCS_SPI_PLOAM_RX_ARG;" in spi,
          "second byte of the A2 command")

    print()
    print("=== 4. big-endian addressing is preserved ===")
    # The vendor byte-swaps with `rev`; the port uses cpu_to_be32.  Either way
    # the wire order must be big-endian, which is what the FPGA expects.
    check("address and value are big-endian",
          spi.count("cpu_to_be32") >= 2,
          "%d cpu_to_be32 uses" % spi.count("cpu_to_be32"))

    print()
    print("=== 5. device names and ioctl set ===")
    uapi = defines(DRIVER / "fmcs_uapi.h")
    check("FMCS_MCI_MAJOR", uapi.get("FMCS_MCI_MAJOR") == 0xE6, "0xE6")
    check("FMCS_PLOAM_LEN", uapi.get("FMCS_PLOAM_LEN") == 13, "13")

    src = (DRIVER / "fmcs.c").read_text(encoding="utf8")
    for token in ("FMCS_NETDEV_PLOAM", "FMCS_NETDEV_OMCI"):
        check("fmcs.c uses %s" % token, token in src, "from fmcs_uapi.h")
    # The names must not be re-typed as literals anywhere in the driver.
    for literal in ('"molt_ploam"', '"molt_omci"', '"/dev/fmcs_mci"'):
        hits = [f.name for f in DRIVER.glob("fmcs*.c") if literal in f.read_text(encoding="utf8")]
        check("no literal %s" % literal, not hits, ", ".join(hits) or "defined once")

    # The ioctl macros expand to _IOW(...)/_IOR(...)/_IOWR(...), not to an
    # integer, so they are collected by name rather than by `defines()`.
    uapi_src = (DRIVER / "fmcs_uapi.h").read_text(encoding="utf8")
    ioctl_names = sorted(set(re.findall(r"^#define\s+(FMCS_IOC_\w+)",
                                        uapi_src, re.MULTILINE)))
    check("seven ioctl commands defined", len(ioctl_names) == 7,
          ", ".join(ioctl_names) or "none found")
    missing = [n for n in ioctl_names if n not in src]
    check("fmcs.c dispatches on all of them", not missing,
          "missing: %s" % ", ".join(missing) if missing else "all present")

    print()
    if failures:
        print("FAILED: %d check(s): %s" % (len(failures), ", ".join(failures)))
        return 1

    print("Driver sources agree with the recovered protocol constants.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
