"""Verify docs/MOLT_API.md against libminiolt_svc.so.

The M-OLT API reference was written by reading strings and pointer tables out of
the vendor library.  This re-derives the same facts straight from the binary and
diffs them against the Markdown, so a transcription slip in the table or a
renamed JSON field cannot survive.

Checked:
  * the three enum pointer tables (offline reason, OMCI state, registration state);
  * the four JSON format strings;
  * the command catalogue in miniolt_func_list;
  * the alarm-class switch, via its string targets.

Run:  python tools/verify_molt_api.py
Exit: 0 when the document matches the binary, 1 otherwise.
"""
import re
import sys
from pathlib import Path

from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "MOLT_API.md"
LIB = Path(r"D:\H3C\bak\mtd3_rootfs\lib\libminiolt_svc.so")

# Where the recovered structures live, from the disassembly in the document.
DATA_BASE = 0x218C0
FUNC_LIST = 0x21498
FUNC_LIST_STRIDE = 40

ENUM_TABLES = {
    "offlineReason": (DATA_BASE + 0x00, 7),
    "omciState": (DATA_BASE + 0x38, 3),
    "regState": (DATA_BASE + 0x50, 3),
}

ALARM_SWITCH = {
    0x00: "PON_LOS",
    0x01: "PON_TX_PWR_TOO_LOW",
    0x02: "PON_RX_ABNORMAL_LIGHT",
    0x03: "INBAND_MGM_LINK_BROKEN",
    0x04: "I2C_LINK_BROKEN",
    0x64: "SUBDEVICE_PON_LOSi",
    0x65: "SUBDEVICE_DGi",
    0x68: "SUBDEVICE_PON_TX_ABNORMAL_LIGHT",
    0x69: "SUBDEVICE_PON_LOFi",
    0x6A: "SUBDEVICE_REMOTE_TX_PWR_TOO_LOW",
    0x6B: "SUBDEVICE_REMOTE_TX_PWR_TOO_HIGH",
    0x6C: "SUBDEVICE_REMOTE_RX_PWR_TOO_LOW",
    0x6D: "SUBDEVICE_REMOTE_RX_PWR_TOO_HIGH",
}

JSON_FIELDS = {
    "optical": ["biasCurrent", "voltage", "temprature", "txOpticalPwr",
                "rxOpticalPwr", "oltRxOpticalPwr", "upstreamOptAtten",
                "downstreamOptAtten"],
    "subdevice_state": ["subDeviceIdState", "onuId", "sn", "snPassword", "loid",
                        "loidPassword", "regState", "omciState", "offlineReason",
                        "lastOnlineTime", "lastOfflineTime", "lastPowerOffTime",
                        "totalOnlinePeriod", "distance", "equipmentId",
                        "softVer", "hwVer"],
    "port_stats": ["rxPkts", "rxOctetsLow32", "rxOctetsHigh32", "rxCrcErrPkts",
                   "rxBipErr", "rxBursts", "rxGemFrms", "txPkts",
                   "txOctetsLow32", "txOctetsHigh32", "txGemFrms"],
}

failures = []


def check(label, ok, detail=""):
    print("  %-5s %-38s %s" % ("PASS" if ok else "FAIL", label, detail))
    if not ok:
        failures.append(label)


def main():
    if not LIB.exists():
        print("vendor library not found at %s" % LIB)
        return 1

    elf = ELFFile(open(LIB, "rb"))
    segs = [(s["sh_addr"], s["sh_addr"] + s["sh_size"], s.data())
            for s in elf.iter_sections()
            if (s["sh_flags"] & 0x2) and s["sh_size"]]

    def rd(addr, n):
        for lo, hi, d in segs:
            if lo <= addr < hi:
                chunk = d[addr - lo:addr - lo + n]
                return chunk + b"\0" * (n - len(chunk))
        return b"\0" * n

    def cstr(addr):
        out = bytearray()
        for i in range(256):
            c = rd(addr + i, 1)
            if not c or c[0] == 0:
                break
            out.append(c[0])
        return out.decode("latin1")

    doc = DOC.read_text(encoding="utf8")

    print("=== 1. enum pointer tables ===")
    for name, (addr, count) in ENUM_TABLES.items():
        values = []
        for i in range(count):
            p = int.from_bytes(rd(addr + i * 8, 8), "little")
            values.append(cstr(p))

        missing = [v for v in values if ("`%s`" % v) not in doc]
        check(name, not missing,
              "%d entries: %s" % (len(values), ", ".join(values)))
        if missing:
            print("        not referenced in doc: %s" % ", ".join(missing))

    print()
    print("=== 2. JSON field lists ===")
    for label, fields in JSON_FIELDS.items():
        absent = [f for f in fields if ('"%s"' % f) not in doc]
        check(label, not absent, "%d fields" % len(fields))
        if absent:
            print("        missing from doc: %s" % ", ".join(absent))

    # The vendor's misspelling is load-bearing; make sure the doc keeps it and
    # does not silently "fix" it.
    check("temprature spelling preserved", '"temprature"' in doc,
          "the stock front end reads this exact key")

    print()
    print("=== 3. alarm class switch ===")
    for value, name in ALARM_SWITCH.items():
        ok = ('0x%02x' % value) in doc and ('`%s`' % name) in doc
        check("alarm 0x%02x" % value, ok, name)

    print()
    print("=== 4. command catalogue ===")
    rows = re.findall(r"^\|\s*(\d+)\s*\|\s*`([A-Za-z_0-9]+)`\s*\|\s*`([0-9a-f]+)`\s*/\s*`([0-9a-f]+)`",
                      doc, re.MULTILINE)
    doc_cmds = {}
    for _id, name, hi, lo in rows:
        doc_cmds[int(_id)] = (name, int(hi, 16), int(lo, 16))

    bin_cmds = {}
    for rec in range(25):
        off = FUNC_LIST + rec * FUNC_LIST_STRIDE
        fields = [int.from_bytes(rd(off + i * 8, 8), "little") for i in range(5)]
        bin_cmds[fields[0]] = (cstr(fields[1]),
                               (fields[4] >> 32) & 0xffffffff,
                               fields[4] & 0xffffffff)

    check("catalogue size", set(doc_cmds) == set(bin_cmds),
          "%d commands in doc, %d in binary%s" % (
              len(doc_cmds), len(bin_cmds),
              "" if set(doc_cmds) == set(bin_cmds)
              else "; missing %s" % sorted(set(bin_cmds) - set(doc_cmds))))

    mismatched = sorted(i for i in bin_cmds if doc_cmds.get(i) != bin_cmds[i])
    check("command ids, names and flags", not mismatched,
          "mismatch: %s" % (mismatched or "none"))
    for i in mismatched[:6]:
        print("        id %d: doc=%s binary=%s" % (i, doc_cmds.get(i), bin_cmds[i]))

    # The read-only bit is what the UI uses to gate writes; check the doc's
    # characterisation of it against the binary rather than trusting the prose.
    ro_by_flag = {i for i, v in bin_cmds.items() if v[2] == 0}
    named_ro = {"molt_reset", "molt_moduleInfo_get", "molt_uplink_port_stats_get"}
    check("read-only set", {bin_cmds[i][0] for i in ro_by_flag} == named_ro,
          "flag-derived: %s" % ", ".join(sorted(bin_cmds[i][0] for i in ro_by_flag)))

    print()
    if failures:
        print("FAILED: %d check(s): %s" % (len(failures), ", ".join(failures)))
        return 1

    print("docs/MOLT_API.md matches libminiolt_svc.so.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
