"""Tabulate every op_cmd passed to SPI_CONTROLLER_Set_Opfifo (0x5755e0).

docs/SPI_CONTROLLER.md documents this as a next step: the set of op values the
vendor kernel actually uses bounds the OPFIFO encoding even if each member is
not individually named.

**The tracker is a heuristic, not dataflow.**  It models `mov`, clears registers
on a call, and clears a register named as an instruction destination -- but it
does not follow values through arithmetic or memory.  An earlier revision was
looser and produced false positives: `0x00` for `0x575a7c` (really
Write_One_Byte's op_cmd argument) and `0x01` for `0x575b80` (really
`direction + 8`).  The first cost a round chasing a contradiction that did not
exist.  Spot-check a reported site by disassembling it before building on it.

Current result: 9 of 12 sites resolve, 3 decline to, no known false positives.

Usage:  python opfifo_ops.py
"""
import re
import struct

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

IMAGE = r"D:\H3C\fttr-port\vendor\vmlinux.bin"
TARGET = 0x5755E0

data = open(IMAGE, "rb").read()
md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)

# Any BL in the image whose encoding resolves to TARGET.  BL is
# 0b100101 imm26 with a sign-extended, word-scaled offset.
sites = []
for off in range(0, len(data) - 4, 4):
    w = struct.unpack_from("<I", data, off)[0]
    if (w >> 26) != 0x25:
        continue
    imm = w & 0x03FFFFFF
    if imm & 0x02000000:
        imm -= 0x04000000
    if off + imm * 4 == TARGET:
        sites.append(off)

print("call sites of 0x%x: %d" % (TARGET, len(sites)))

# The immediate group must not repeat the '#': op_str is "w20, #1", so the
# literal ", #" is already consumed before the value is matched.
re_movN = re.compile(r"^(w\d+), #(0x[0-9a-f]+|[0-9]+)$")
re_movreg = re.compile(r"^(w\d+), (w\d+)$")
re_dst = re.compile(r"^([wx]\d+),")

results = []
for site in sites:
    # Disassemble a window ending at the call and walk it forwards, modelling
    # the writes that actually clobber a register.
    back = data[max(0, site - 64):site]
    regs = {}
    for ins in md.disasm(back, site - len(back)):
        if ins.mnemonic in ("bl", "blr", "blx"):
            # A call clobbers the argument registers.
            regs.clear()
            continue
        if ins.mnemonic == "mov":
            m = re_movN.match(ins.op_str)
            if m:
                regs[m.group(1)] = int(m.group(2), 0)
                continue
            m = re_movreg.match(ins.op_str)
            if m:
                if m.group(2) in regs:
                    regs[m.group(1)] = regs[m.group(2)]
                else:
                    regs.pop(m.group(1), None)
            continue
        if ins.mnemonic.startswith(("str", "stp", "stur", "stl")):
            # Stores name their source first, not a destination.
            continue
        if ins.mnemonic in ("dmb", "dsb", "isb", "nop", "prfm", "cmp", "tst",
                            "cbz", "cbnz", "b", "ret", "csel", "cset", "csdb",
                            "eor"):
            continue
        # Anything else that names a register first writes it.
        m = re_dst.match(ins.op_str)
        if m:
            regs.pop(m.group(1), None)
            alias = ("x" if m.group(1).startswith("w") else "w") + m.group(1)[1:]
            regs.pop(alias, None)
    results.append((site, regs.get("w0")))

print()
print("recovered op_cmd values:")
by_value = {}
for site, value in results:
    if value is not None:
        by_value.setdefault(value, []).append(site)
for value in sorted(by_value):
    sites_hex = ", ".join("0x%x" % s for s in by_value[value])
    print("  op_cmd = 0x%02x  (%2d site(s))  %s"
          % (value, len(by_value[value]), sites_hex))

unresolved = [s for s, v in results if v is None]
if unresolved:
    print()
    print("unresolved (argument is a parameter or computed, not a literal): %s"
          % ", ".join("0x%x" % s for s in unresolved))
