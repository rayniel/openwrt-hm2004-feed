"""Run every check in this tree and report a single verdict.

Run:  python tools/run_checks.py
Exit: 0 when all checks pass, 1 otherwise.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHECKS = [
    ("ABI: ioctl numbers vs the shipped binaries", "verify_abi.py"),
    ("M-OLT API: recovered reference vs libminiolt_svc.so", "verify_molt_api.py"),
    ("Vendor kernel: extraction and symbol recovery", "extract_kernel.py", "verify"),
    ("SPI controller: register map vs the vendor kernel", "verify_spi_regs.py"),
    ("Driver: sources vs the recovered protocol constants", "check_driver_consistency.py"),
    ("C: compile-time ABI assertions and miniolt", "check_c.py"),
    ("LuCI: rpcd shim and view contract", "check_luci.py"),
]


def main():
    results = []

    for label, script, *rest in CHECKS:
        print("=" * 72)
        print(label)
        print("=" * 72)
        proc = subprocess.run([sys.executable, str(ROOT / "tools" / script), *rest],
                              cwd=str(ROOT))
        results.append((label, proc.returncode == 0))
        print()

    print("=" * 72)
    for label, ok in results:
        print("  %-5s %s" % ("PASS" if ok else "FAIL", label))
    print("=" * 72)

    failed = [label for label, ok in results if not ok]
    if failed:
        print("%d check(s) failed." % len(failed))
        return 1

    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
