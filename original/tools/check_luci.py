"""Exercise the LuCI rpcd shim and validate everything it emits.

The shim is the only bridge between the LuCI view and the driver, and rpcd
silently produces a broken ubus object if a method emits anything that is not
valid JSON.  This runs the shim the way rpcd does -- `list`, then
`call <method>` with a JSON body on stdin -- and parses every response.

Run:  python tools/check_luci.py
Exit: 0 when every call returns valid JSON, 1 otherwise.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIM = (ROOT / "luci" / "luci-app-h3c-fttr" / "root" /
        "usr" / "libexec" / "rpcd" / "luci.h3c_fttr")
VIEW = (ROOT / "luci" / "luci-app-h3c-fttr" / "htdocs" / "luci-static" /
        "resources" / "view" / "h3c_fttr" / "status.js")

SH_CANDIDATES = [
    r"C:\Program Files\Git\usr\bin\sh.exe",
    r"C:\Program Files\Git\bin\sh.exe",
    "/bin/sh",
    "sh",
]

# (method, request body) pairs, matching how the JavaScript view calls them.
CALLS = [
    ("status", None),
    ("regread", '{"type":"fpga","addr":"0x0000"}'),
    ("regread", '{"type":"bosa","addr":"0x0000"}'),
    ("regread", '{"type":"bogus","addr":"0x0000"}'),
    ("regread", '{"type":"fpga"}'),
    ("regwrite", '{"type":"fpga","addr":"0x0000","value":"0x1"}'),
    ("regwrite", '{"type":"bogus","addr":"0x0","value":"0x0"}'),
    ("nosuchmethod", None),
]


def find_sh():
    for candidate in SH_CANDIDATES:
        path = shutil.which(candidate)
        if path:
            return path
        if Path(candidate).exists():
            return candidate
    return None


def main():
    sh = find_sh()
    if not sh:
        print("no POSIX shell found; tried: %s" % ", ".join(SH_CANDIDATES))
        return 1

    print("shell: %s" % sh)
    failures = []

    def check(label, ok, detail=""):
        print("  %-5s %-34s %s" % ("PASS" if ok else "FAIL", label, detail))
        if not ok:
            failures.append(label)

    proc = subprocess.run([sh, "-n", str(SHIM)], capture_output=True, text=True)
    check("sh -n", proc.returncode == 0, proc.stderr.strip()[:120])

    proc = subprocess.run([sh, str(SHIM), "list"], capture_output=True, text=True)
    try:
        methods = json.loads(proc.stdout)
        ok = (proc.returncode == 0 and
              set(methods) == {"status", "regread", "regwrite"} and
              methods["status"] == {} and
              "type" in methods["regread"] and "addr" in methods["regread"] and
              set(methods["regwrite"]) == {"type", "addr", "value"})
        check("list", ok, "methods: %s" % ", ".join(sorted(methods)))
    except json.JSONDecodeError as exc:
        check("list", False, "invalid JSON: %s -- %r" % (exc, proc.stdout[:120]))

    for method, body in CALLS:
        proc = subprocess.run([sh, str(SHIM), "call", method],
                              input=body or "", capture_output=True, text=True)
        raw = proc.stdout.strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            check("call %s" % method, False,
                  "invalid JSON: %s -- %r" % (exc, raw[:120]))
            continue

        ok = isinstance(parsed, dict) and bool(parsed)
        check("call %s" % method, ok, raw[:100])

    # The status object is the contract with the JavaScript view: every key the
    # view reads must exist on every call, including when the module is absent.
    proc = subprocess.run([sh, str(SHIM), "call", "status"],
                          input="", capture_output=True, text=True)
    try:
        status = json.loads(proc.stdout)
        expected = {"loaded", "chardev", "netdev_ploam", "netdev_omci",
                    "driver_version", "holdtimes", "irq_count",
                    "int_status0", "int_status1",
                    "ploam_rx", "ploam_tx", "omci_rx", "omci_tx"}
        check("status keys", set(status) == expected,
              "missing: %s" % (sorted(expected - set(status)) or "none"))
    except json.JSONDecodeError:
        check("status keys", False, "status was not JSON")

    # Every rpc.declare()/method name in the view must exist in the shim.
    view = VIEW.read_text(encoding="utf8")
    imported = set()
    for line in view.splitlines():
        line = line.strip()
        if line.startswith("method:"):
            imported.add(line.split(":", 1)[1].strip().strip("',"))
    check("view methods exist", imported <= set(methods),
          "view calls: %s" % ", ".join(sorted(imported)))

    print()
    if failures:
        print("FAILED: %s" % ", ".join(failures))
        return 1

    print("LuCI shim and view agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
