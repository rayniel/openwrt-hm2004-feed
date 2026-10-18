"""Re-derive the ECNT SPI controller register offsets from the vendor kernel.

docs/SPI_CONTROLLER.md claims that the vendor's SPI core and mainline
spi-airoha-snfi.c address the same registers, and lists the offsets.  This
re-derives those offsets from the vendor instruction stream and fails if the
document and the binary disagree.

Method: the vendor addresses the controller as `[[ctrl]] + 8`, a mapped base
held in a register.  Every access therefore appears as either
`str wN, [xM, #off]` or as `add xM, xM, #off` immediately followed by a
load/store through `[xM]`.  Both forms are collected over the SPI core and
compared against the expected set.

Run:  python tools/verify_spi_regs.py
Exit: 0 when the document matches the binary, 1 otherwise.
"""
import re
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

ROOT = Path(__file__).resolve().parent.parent
IMAGE = ROOT / "vendor" / "vmlinux.bin"
DOC = ROOT / "docs" / "SPI_CONTROLLER.md"

# Function bounds inside the decompressed Image, from vendor/ksymtab.txt.
# The range covers spi_device_init/exit, the FIFO primitives, the OPFIFO
# writer and spi_device_write/read.
SPI_CORE = (0x575440, 0x575F00)

# Offsets the document tabulates, with the register name it gives each.
EXPECTED = {
    0x28: "REG_SPI_CTRL_OPFIFO_WDATA",
    0x2C: "REG_SPI_CTRL_OPFIFO_FULL",
    0x34: "REG_SPI_CTRL_DFIFO_FULL",
    0x38: "REG_SPI_CTRL_DFIFO_WDATA",
    0x3C: "DFIFO status, RX side",
    0x40: "trigger",
    0x44: "REG_SPI_CTRL_DFIFO_RDATA",
    0xE4: "controller enable",
}

# The mainline names the document claims for the offsets that ARE confirmed.
MAINLINE_CONFIRMED = {0x28, 0x2C, 0x34, 0x38, 0x44}

failures = []


def check(label, ok, detail=""):
    print("  %-5s %-42s %s" % ("PASS" if ok else "FAIL", label, detail))
    if not ok:
        failures.append(label)


def main():
    if not IMAGE.exists():
        print("no vendor image at %s; run tools/extract_kernel.py extract" % IMAGE)
        return 1

    blob = IMAGE.read_bytes()
    lo, hi = SPI_CORE
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    insns = list(md.disasm(blob[lo:hi], lo))

    # Form 1: direct "op wN, [xM, #off]"
    direct = {}
    re_direct = re.compile(r"^[wx]\d+, \[([wx]\d+), #(0x[0-9a-f]+)\]$")
    for ins in insns:
        if ins.mnemonic not in ("ldr", "str", "ldrb", "strb", "ldrh", "strh"):
            continue
        m = re_direct.match(ins.op_str)
        if m:
            direct.setdefault(int(m.group(2), 16), []).append(ins.address)

    # Form 2: "add xM, xM, #off" followed by a load/store through [xM]
    indirect = {}
    re_add = re.compile(r"^([wx]\d+), ([wx]\d+), #(0x[0-9a-f]+)$")
    re_use = re.compile(r"\[([wx]\d+)\]")
    for i, ins in enumerate(insns[:-1]):
        if ins.mnemonic != "add":
            continue
        m = re_add.match(ins.op_str)
        if not m:
            continue
        reg, off = m.group(1), int(m.group(3), 16)
        if off < 0x10 or off > 0x200:
            continue
        nxt = insns[i + 1]
        if nxt.mnemonic not in ("ldr", "str", "ldrb", "strb", "ldrh", "strh",
                                "ldur", "stur"):
            continue
        mu = re_use.match(nxt.op_str.split(", ", 1)[-1])
        if mu and mu.group(1) == reg:
            indirect.setdefault(off, []).append(ins.address)

    observed = set(direct) | set(indirect)

    print("=== 1. every documented offset appears in the instruction stream ===")
    for off, name in sorted(EXPECTED.items()):
        where = direct.get(off, []) + indirect.get(off, [])
        check("+0x%02x %s" % (off, name), bool(where),
              "at %s" % ", ".join("0x%x" % a for a in where[:3]) if where
              else "not observed")

    print()
    print("=== 2. the OPFIFO packing matches the mainline field layout ===")
    # FIELD_PREP(OPFIFO_OP, op) | FIELD_PREP(OPFIFO_LEN, len) with
    # OP = GENMASK(13,9) and LEN = GENMASK(8,0) is (op << 9) | (len & 0x1ff).
    # The vendor code must therefore contain a "#9, #5" ubfiz and a #0x1ff mask.
    text = " ".join(i.mnemonic + " " + i.op_str for i in insns)
    check("ubfiz to bit 9, width 5", "#9, #5" in text,
          "op field -> GENMASK(13,9)")
    check("length masked to 0x1ff", "#0x1ff" in text,
          "len field -> GENMASK(8,0)")
    check("writes OPFIFO_WDATA", 0x28 in observed,
          "regmap_write(REG_SPI_CTRL_OPFIFO_WDATA, ...)")

    print()
    print("=== 3. the document names the right registers for them ===")
    doc = DOC.read_text(encoding="utf8")
    for off in sorted(MAINLINE_CONFIRMED):
        name = EXPECTED[off]
        check("+0x%02x -> %s" % (off, name),
              ("`+0x%02X`" % off) in doc and ("`%s`" % name) in doc,
              "both the offset and the name are in the document")

    # The three offsets the document explicitly flags as unnamed must stay
    # flagged: they are read off the binary without a mainline counterpart.
    print()
    print("=== 4. unconfirmed offsets stay declared as unconfirmed ===")
    for off in (0x3C, 0x40, 0xE4):
        mark = "`+0x%02X`" % off
        idx = doc.find(mark)
        ok = idx >= 0 and "__not__" not in doc[idx:idx + 200]
        # They must appear in section 5's list of unverified items.
        check("+0x%02X declared unverified" % off,
              mark in doc and ("`+0x%02X`" % off) in doc.split("## 5")[-1],
              "listed under 'What is not yet established'")

    print()
    print("=== 5. the shared-block conclusion is stated ===")
    check("mainline cross-reference recorded",
          "spi-airoha-snfi" in doc and "0x0038" in doc and "0x0044" in doc,
          "both mainline offsets cited")
    check("transmit framing declared unresolved",
          "OP = 1" in doc and "not recovered" in doc,
          "the remaining blocker is stated, not glossed")
    check("no patch claimed", "patches/airoha-spi-generic-transfer.patch" not in doc,
          "document does not promise an artefact that does not exist")

    # --- vendor trace strings -------------------------------------------------
    # 0x575390 is called with a literal format string at the head of each SPI
    # function; those strings are the vendor's own names for the core.
    print()
    print("=== 6. the vendor trace strings exist where the document says ===")
    TRACE = {
        0xBD1598: "spi_controller_write_data_fifo : len=0x%x, data: 0x%x",
        0xBD1608: "spi_controller_set_opfifo: set op_cmd =0x%x, op_len=0x%x",
        0xBD16A8: "SPI_CONTROLLER_Set_Configure: AUTO Mode",
        0xBD16D8: "SPI_CONTROLLER_Set_Configure: Manual Mode",
        0xBD1708: "SPI_CONTROLLER_Set_Configure: DMA Mode",
        0xBD1760: "SPI_CONTROLLER_Write_NByte: len=0x%x",
        0xBD1788: "SPI CS1 device wait for flash operation done timeout",
    }

    def cstr(off):
        end = blob.find(b"\x00", off, off + 300)
        # The trace strings each end in a newline; the document quotes them
        # without it, so compare on the trimmed form.
        return blob[off:end].decode("latin1").rstrip("\n")

    for addr, want in sorted(TRACE.items()):
        got = cstr(addr)
        check("0x%06x" % addr, got == want, repr(got)[:58])

    for token in ("SPI_CONTROLLER_Set_Opfifo", "AUTO Mode", "Manual Mode",
                  "DMA Mode", "CS1"):
        check("doc records %s" % token, token in doc, "in SPI_CONTROLLER.md")

    # --- the mode table -------------------------------------------------------
    print()
    print("=== 7. spi_device_read's mode table is the mainline RX buswidth set ===")
    table = [blob[0x9DC0C8 + i] for i in range(3)]
    check("table {0x0c, 0x0e, 0x0f}", table == [0x0C, 0x0E, 0x0F],
          "SNAND_FIFO_RX_BUSWIDTH_SINGLE/DUAL/QUAD, got %s"
          % ", ".join("0x%02x" % v for v in table))

    # --- the Manual-mode claim is a different code path from mainline ---------
    check("Manual Mode is a distinct path",
          "does *not* already implement the mode" in doc,
          "document no longer implies mainline covers this path")

    # --- the corrected inference must stay corrected --------------------------
    print()
    print("=== 8. the 0x5776f0 mis-identification is recorded, not re-made ===")
    check("document states it was wrong",
          "corrected inference" in doc and "That was wrong" in doc,
          "the retraction is explicit")
    check("0x5776f0 described as a hex dump",
          "hex-dump helper" in doc and "%02x" in doc,
          "described by what it actually is")
    check("debug flag not called a mode selector",
          "payload-dump" in doc and "not a mode selector" in doc,
          "0x113f03e0 is recorded as a debug flag")
    check("second register base recorded",
          "[ctrl+0x10]" in doc and "second register base" in doc,
          "the two-base finding is captured")
    # The stale bullet must not quietly come back.
    check("stale next-step struck through",
          "~~`0x5776f0`~~" in doc,
          "the superseded list item is marked")

    # --- the OPFIFO op scan result must stay honest ---------------------------
    print()
    print("=== 9. the OPFIFO op scan result is recorded with its caveat ===")
    for token in ("op_cmd = 0x00", "op_cmd = 0x01", "op_cmd = 0x08",
                  "heuristic", "bracketing control"):
        check("doc records %r" % token[:28], token in doc, "in SPI_CONTROLLER.md")

    scan = ROOT / "tools" / "opfifo_ops.py"
    check("scan tool present", scan.exists(), str(scan.name))
    if scan.exists():
        src = scan.read_text(encoding="utf8")
        # The regex bug from round 9: the immediate group must not repeat the
        # '#' the literal ", #" already consumed, or small decimals are skipped.
        check("immediate regex fixed",
              r"#(0x[0-9a-f]+|[0-9]+)$" in src and r"#(0x[0-9a-f]+|#[0-9]+)$" not in src,
              "no double-'#' alternation")
        check("false-positive limitation documented",
              "false positives" in src and "heuristic" in src,
              "stated in the module docstring")

    print()

    if failures:
        print("FAILED: %d check(s): %s" % (len(failures), ", ".join(failures)))
        return 1

    print("docs/SPI_CONTROLLER.md matches the vendor instruction stream.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
