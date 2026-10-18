"""Generate the HM2004-DU fmcs DTS patch by computing the hunk directly.

Git on Windows rewrites line endings on add, which makes its diff claim the
whole file changed.  This builds the unified diff itself so the counts are
exact and the line endings are whatever the source has.
"""
from pathlib import Path

SRC = Path(r"D:\H3C\work\caizhenbing-hm2004-du.dts")
OUT = Path(r"D:\H3C\fttr-port\patches\0001-arm64-dts-airoha-hm2004-du-enable-fmcs.patch")
REL = "target/linux/airoha/dts/an7581-h3c-hm2004-du.dts"

text = SRC.read_text(encoding="utf8").replace("\r\n", "\n").replace("\r", "\n")
lines = text.split("\n")

OLD = [
    '\tfmcs {',
    '\t\tcompatible = "h3c,fmcs";',
    '\t\tstatus = "disabled";',
    '\t};',
]

NEW = [
    '\tfmcs {',
    '\t\tcompatible = "h3c,fmcs";',
    '',
    '\t\t/*',
    "\t\t * The FPGA interrupt arrives through the pinctrl's GPIO",
    '\t\t * interrupt controller, not the GIC directly: the stock node',
    '\t\t * names GIC SPI 26, which is exactly the interrupt',
    '\t\t * en7581_pinctrl claims for itself in an7581.dtsi.',
    '\t\t */',
    '\t\tinterrupt-parent = <&en7581_pinctrl>;',
    '\t\tinterrupts = <23 IRQ_TYPE_LEVEL_HIGH>;',
    '',
    '\t\t/*',
    '\t\t * FPGA configuration port, driven once at probe by the driver\'s',
    '\t\t * bitstream loader.  ACTIVE_HIGH throughout, because the vendor',
    '\t\t * shifts raw bit values rather than using inverted logic.',
    '\t\t */',
    '\t\tnconfig-gpios   = <&en7581_pinctrl 5  GPIO_ACTIVE_HIGH>;',
    '\t\trst-gpios       = <&en7581_pinctrl 22 GPIO_ACTIVE_HIGH>;',
    '\t\tclk-gpios       = <&en7581_pinctrl 29 GPIO_ACTIVE_HIGH>;',
    '\t\tdata-gpios      = <&en7581_pinctrl 30 GPIO_ACTIVE_HIGH>;',
    '\t\tstatus-gpios    = <&en7581_pinctrl 27 GPIO_ACTIVE_HIGH>;',
    '\t\tconf-done-gpios = <&en7581_pinctrl 28 GPIO_ACTIVE_HIGH>;',
    '',
    '\t\t/*',
    '\t\t * Runtime register transport.',
    '\t\t *',
    '\t\t * The FPGA sits on chip select 1 of the SPI controller at',
    '\t\t * 0x1fa10000, which this tree hands to the SPI-NAND driver.',
    '\t\t * Until that driver serves generic transfers the register path',
    '\t\t * cannot bind and only the bitstream load above takes effect.',
    '\t\t * See docs/NEXT_STEPS.md.',
    '\t\t */',
    '\t\tstatus = "okay";',
    '\t};',
]

# Locate the placeholder; it must appear exactly once or we refuse.
starts = [i for i in range(len(lines) - len(OLD) + 1)
          if lines[i:i + len(OLD)] == OLD]
if len(starts) != 1:
    raise SystemExit("placeholder fmcs node matched %d times; refusing to guess"
                     % len(starts))
at = starts[0]

CTX = 3
lo = max(0, at - CTX)
hi = min(len(lines), at + len(OLD) + CTX)

before = lines[lo:at]
after = lines[at + len(OLD):hi]

hunk = ([(" ", l) for l in before]
        + [("-", l) for l in OLD]
        + [("+", l) for l in NEW]
        + [(" ", l) for l in after])

old_count = len(before) + len(OLD) + len(after)
new_count = len(before) + len(NEW) + len(after)

body = "\n".join(p + l for p, l in hunk)

header = """From: H3C HM2004-DU FTTR port
Subject: [PATCH] arm64: dts: airoha: hm2004-du: wire up the FMCS FTTR FPGA

Replace the disabled placeholder fmcs node with the real binding.

The wiring is recovered from the stock device tree (the DTB appended to
mtd2_kernel.bin at file offset 0x21fc), which reads:

    fmcs {
        compatible = "h3c,fmcs";
        spi-controller = <0xb>;
        fpga-spi-int-gpio = <0x17>;
        interrupts = <0x0 0x1a 0x1>;
        fpga-load-rst-gpio      = <0x0>;
        fpga-load-cfg-done-gpio = <0x0>;
        fpga-load-flag-gpio     = <0x0>;
        fpga-load-clk-gpio      = <0x0>;
        fpga-load-do-gpio       = <0x0>;
    };

The five fpga-load-* properties are zero in the shipped DTB and no shipped
module reads them: the loader that actually runs, fpga_load.ko, has no
device-tree code at all and drives hard-coded GPIO block bits.  Those bits map
one-to-one onto GPIO numbers, which is how the configuration port below is
derived.  See docs/REVERSE_ENGINEERING.md sections 1 and 6.

The register transport is deliberately left unbound: the SPI controller that
carries chip select 1 is owned by the SPI-NAND driver in this tree and does not
yet serve generic transfers.  See docs/NEXT_STEPS.md.

---
 %s | %d %s
 1 file changed, %d insertions(+), %d deletions(-)

diff --git a/%s b/%s
--- a/%s
+++ b/%s
@@ -%d,%d +%d,%d @@
%s
""" % (REL, len(OLD) + len(NEW), "line changed" if len(OLD) == 1 else "lines changed",
       len(NEW), len(OLD),
       REL, REL, REL, REL,
       lo + 1, old_count, lo + 1, new_count, body)

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(header, encoding="utf8")

print("wrote %s (%d bytes)" % (OUT, len(header)))
print("hunk: -%d,%d +%d,%d  (old %d lines -> new %d lines)"
      % (lo + 1, old_count, lo + 1, new_count, len(OLD), len(NEW)))
print()
print("\n".join(header.splitlines()[-len(hunk) - 1:]))
