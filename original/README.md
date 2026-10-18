# H3C HM2004-DU FTTR master-OLT (FMCS) — reverse engineering and port

Source reconstruction of the "FMCS" FTTR master-OLT subsystem of the H3C
HM2004-DU, so that it can run on the OpenWrt 6.18 / Airoha AN7581 kernel tree
(`qwe3017/ponwrt`) instead of the vendor's Linux 5.4.55 Buildroot image.

Everything here was derived from the artefacts in `D:\H3C\bak\mtd3_rootfs` and
`D:\H3C\bak\mtd2_kernel.bin`. The evidence for every constant, register frame
and GPIO bit is recorded in [`docs/REVERSE_ENGINEERING.md`](docs/REVERSE_ENGINEERING.md).

---

## What the subsystem is

The HM2004-DU is an FTTR **main** gateway. Besides the normal G-PON uplink it
carries a second, H3C-proprietary PON built around a **Pango Logos PGL50H**
FPGA that acts as master OLT for up to sixteen sub-ONUs:

```
        userspace                      kernel                        hardware
  ┌────────────────────┐   ioctl    ┌──────────────┐   SPI    ┌────────────────┐
  │ miniolt, moltd,    │──────────▶ │ /dev/fmcs_mci│─────────▶│  FMCS FPGA     │
  │ moltcmd, momci     │  0xa5…     │              │          │  (PGL50H)      │
  ├────────────────────┤            │   fmcs.ko    │          │                │
  │ PLOAM / OMCI stack │  netdev    │              │ GPIO IRQ │  16 × sub-ONU  │
  │                    │◀──────────▶│ molt_ploam   │◀─────────│                │
  │                    │            │ molt_omci    │          └────────────────┘
  └────────────────────┘            └──────────────┘
                                            │
                                     gpio bit-bang (once, at boot)
                                            ▼
                                    FPGA configuration port
                                    /lib/firmware/FTTR_TOP.sbit
```

Stock components, all reversed here:

| Artefact | What it is | Replaced by |
| --- | --- | --- |
| `lib/modules/fmcs.ko` | FPGA driver: SPI, GPIO IRQ, chardev, netdevs, genetlink | `driver/fmcs*.c` |
| `lib/modules/fpga_load.ko` | one-shot bitstream loader, GPIO bit-bang | `driver/fmcs_load.c` |
| `usr/bin/miniolt` | register and PLOAM/OMCI command line tool | `userspace/miniolt.c` |
| `lib/firmware/FTTR_TOP.sbit` | FPGA configuration bitstream | used unchanged |
| vendor web pages | `sta-fttr_molt.asp`, `sta-fttr_onu.asp` | `luci/` |

---

## State of the port

### Recovered and reproduced exactly

* **ioctl ABI** on `/dev/fmcs_mci` — all seven `0xa5`-typed commands, argument
  layouts and return conventions. Encoded once in `driver/fmcs_uapi.h` and
  proven equal to the literals in `fmcs.ko` by compile-time assertions in
  `tools/abi_static_assert.c`.
* **SPI wire protocol** — write `A8 <addr_be32> <val_be32>`; read
  `A0 <addr_be32>` → delay → `50` + 4 bytes; PLOAM transmit
  `AA 00 00 00 <13 bytes>`; PLOAM receive `A2 10 00 00 00` → delay → `52` + 13
  bytes. Every frame and every delay is transcribed from the vendor functions.
* **Bitstream load sequence** — nCONFIG pulse, status check, 8-bit MSB-first
  clock-out of the whole file, configuration-done check, reset release, with the
  vendor's hold times exposed as `/proc/fpgaLoad`.
* **Bitstream payload** — `FTTR_TOP.sbit` is fed byte-for-byte, MSB first, with
  no header stripping. See [`docs/SBIT_FORMAT.md`](docs/SBIT_FORMAT.md).
* **The vendor kernel itself** — `mtd2_kernel.bin` is decompressed to a 17 MB
  aarch64 `Image` and its **9 692 exported symbols recovered by name**, so every
  kernel API the vendor modules depend on can be read directly. See
  [`docs/VENDOR_KERNEL.md`](docs/VENDOR_KERNEL.md).
* **Device tree binding** — recovered from the DTB appended to the stock kernel
  image, including the five GPIO lines the vendor hard-coded.
* **Device and interface names** — `/dev/fmcs_mci`, `molt_ploam`, `molt_omci`,
  and the seventeen `genl_*` families.

### Not yet possible — see the dossier for the evidence

**R1 — no generic SPI master on the target kernel.** The FPGA's register
interface sits on the SoC SPI controller at `0x1fa10000` on a chip select of its
own. In the 6.18 tree that block is claimed by the SPI-NAND driver
(`airoha,en7581-snand`, covering `0x1fa10000` and `0x1fa11000`), and
`spi-airoha-snfi.c` offers no generic `spi_sync()` transfers. Until that block
serves general transfers, the driver cannot reach the FPGA registers.

Round 3 removed most of the guesswork, and round 5 finished the register map.
The stock kernel is decompressed and symbolised (see
[`docs/VENDOR_KERNEL.md`](docs/VENDOR_KERNEL.md)), and
[`docs/SPI_CONTROLLER.md`](docs/SPI_CONTROLLER.md) cross-references the vendor's
SPI core against mainline `spi-airoha-snfi.c`. They drive **the same register
block**: the mainline header's `REG_SPI_CTRL_OPFIFO_WDATA` at `0x0028`,
`OPFIFO_FULL` at `0x002C`, `DFIFO_FULL` at `0x0034`, `DFIFO_WDATA` at `0x0038`
and `DFIFO_RDATA` at `0x0044` are the vendor's `+0x28`, `+0x2C`, `+0x34`,
`+0x38` and `+0x44` — and the vendor's `ubfiz ..., #9, #5` with a `#0x1ff`
length mask is literally
`FIELD_PREP(OPFIFO_OP, op) | FIELD_PREP(OPFIFO_LEN, len)`.

It also establishes that the runtime port really is on the hardware controller,
not bit-banged: `spi_device_init` maps physical **`0x1FA11550`**, which is
*outside* the windows the stock device tree declares for either SPI node, so a
new driver must map a range that actually covers it.

**One thing still stands between this map and a driver, and it is not subtle.**
`spi_device_write` does not issue a single OPFIFO word for its payload; it
brackets the data phase with an `OP = 1` word and an `OP = 0` word. `OP = 8` is
confirmed against the mainline constant table as single-bit transmit, but what
`OP = 1` and `OP = 0` mean is not recovered, and they are part of what the FPGA
sees. A patch emitting only the data phase would put *nearly* the right bytes on
the wire and still be wrong — worse than not shipping one — so
`docs/SPI_CONTROLLER.md` section 5 records the exact next steps instead,
cheapest first. `verify_spi_regs.py` fails the build if the document stops
declaring that gap.

The port is written so the transport is the **only** missing piece: register
access goes through `driver/fmcs_spi.c`, which already has two back ends behind
one wire protocol. Adding the missing master is a change to the SPI controller
driver, not to this one. `dts/h3c-fmcs.dtsi` documents both wiring options.

**R2 — the FTTR data path hook belongs to a module, not the kernel.**

The vendor Ethernet driver publishes two function-pointer globals
(`hsgmii_lan_mac_{rx,tx}_h3c_fttr_hook`) and `fmcs.ko` installs its own functions
into them. Round 24 established where they live: they are **not in the vendor
kernel's symbol table at all** — searching the whole decompressed image for the
name returns nothing. They are defined in **`lib/modules/hsgmii_lan.ko`**, a
117 KB module that is also where the FTTR virtual-device layer lives:

```
hsgmii_lan_mac_rx_h3c_fttr_hook      8-byte OBJECT (function pointer)
hsgmii_fttr_init_virtual_dev         hsgmii_fttr_deinit_virtual_dev
hsgmii_fttr_virtual_dev_open/close   hsgmii_fttr_add_vlan_tag_tx
hsgmii_fttr_remove_vlan_tag_rx       hsgmii_fttr_mac  (128-byte OBJECT)
hsgmii_fttr_vir_if_def_mac           hsgmii_lan_mac_rx / _tx
```

So the sub-ONU data path — the `eth1.1` … `eth1.16` interfaces the FMCS driver
resolves by name at load time — is implemented by that module, and it is
**unstripped**, which makes it a tractable target in a way the mainline Ethernet
driver is not.

This reframes R2 usefully: it is not "add a hook to the upstream airoha driver",
it is "port `hsgmii_lan.ko`'s FTTR portions" — a bounded module with full symbols
and a known interface. Until that is done, the FMCS driver's outbound OMCI frames
are counted and dropped rather than silently queued.

**R5 — the register map above the driver — resolved differently.** The FPGA
register map itself is still unrecovered, but it turns out not to be the right
target. The vendor's FTTR management layer, `libminiolt_svc.so`, exposes a
complete typed service API whose output formats are already JSON, and
[`docs/MOLT_API.md`](docs/MOLT_API.md) recovers all of it: 25 commands with
their ids, the OLT and per-ONU optical fields, the sub-ONU state record, port
statistics, every enumeration, and the asynchronous notification sets. That is
the specification a LuCI application and any replacement daemon should be built
against, and it does not require knowing a single FPGA register address.

What is missing is the daemon that produces it — `moltd` needs the FMCS driver
to reach the FPGA. So the LuCI application is staged: stage 1 (driver state plus
a register console) is shipped and works as soon as the register transport
exists; stage 2 (the M-OLT panels) is specified field-for-field in
`docs/MOLT_API.md` section 8 but not yet wired, because wiring it to a daemon
that cannot run would be a mock-up rather than a feature.

---

## Layout

```
docs/REVERSE_ENGINEERING.md   the dossier: every finding and its evidence
docs/SBIT_FORMAT.md           structural analysis of FTTR_TOP.sbit
docs/MOLT_API.md              the recovered M-OLT service API and data model
docs/VENDOR_KERNEL.md         decompressing and symbolising the stock kernel
docs/SPI_CONTROLLER.md         ECNT SPI register map, cross-referenced to mainline
docs/NEXT_STEPS.md            bench procedure for closing R1 on hardware
driver/fmcs_uapi.h            userspace ABI (the contract)
driver/fmcs.c                 core: chardev, ioctls, netdevs, events
driver/fmcs_spi.c             register transport: SPI device or GPIO bit-bang
driver/fmcs_load.c            bitstream loader and /proc/fpgaLoad
driver/{Kconfig,Makefile}     in-tree build glue
dts/h3c-fmcs.dtsi             device tree, with both transport wirings
userspace/miniolt.c           command line tool
openwrt/fttr-fmcs/            kernel module package
openwrt/fttr-tools/           userspace package
luci/luci-app-h3c-fttr/       LuCI application
tools/                        verification and analysis
```

## Building

In-tree, from the OpenWrt tree root:

```sh
cp -r fttr-port/driver      target/linux/airoha/files/drivers/fttr-fmcs
# add to target/linux/airoha/{an7581/,}config-6.18:
#   CONFIG_FTTR_FMCS=m
#   CONFIG_FTTR_FMCS_LOAD_AT_PROBE=y
# source the Kconfig from target/linux/airoha/modules.mk
```

or as packages, by copying `openwrt/fttr-fmcs`, `openwrt/fttr-tools` and
`luci/luci-app-h3c-fttr` into a feed and adding:

```
src-link fttr /path/to/fttr-port
```

Then add `fttr-fmcs`, `fttr-tools` and `luci-app-h3c-fttr` to the image.

Userspace alone:

```sh
cd userspace && make
```

Device tree: include `dts/h3c-fmcs.dtsi` from
`target/linux/airoha/dts/an7581-h3c-hm2004-du.dts` and delete the placeholder
`fmcs { … status = "disabled"; };` node that is there today.

## Verifying

```sh
python tools/run_checks.py     # everything below, one verdict
python tools/verify_abi.py     # ioctl numbers vs two shipped binaries
python tools/verify_molt_api.py # docs/MOLT_API.md vs libminiolt_svc.so
python tools/extract_kernel.py verify # kernel extraction + symbol table
python tools/verify_spi_regs.py  # SPI register map vs the vendor instruction stream
python tools/check_c.py        # compile-time ABI assertions + miniolt
python tools/check_luci.py     # rpcd shim exercised the way rpcd calls it
```

All must exit 0. `verify_abi.py` and `verify_molt_api.py` are the load-bearing
ones. The first re-derives every ioctl number from the kernel's `_IOC` bit
layout and checks it against the compare chain in `fmcs.ko` *and* the immediates
in `miniolt`. The second re-reads the enum pointer tables, the JSON format
strings and the command catalogue straight out of `libminiolt_svc.so` and diffs
them against the reference document, so neither a transcription slip nor an
"improved" vendor spelling can survive.

## Why the vendor binaries still work

The point of reproducing the ABI rather than redesigning it is that the stock
`miniolt`, `moltd`, `moltcmd`, `momci` and the OMCI libraries keep working
against the new driver without a recompile. That is what makes this a port
rather than a rewrite, and it is why `fmcs_uapi.h` documents the vendor's
inconsistencies — including the eight-byte `_IOC` size on both PLOAM commands —
instead of quietly correcting them.

## Licensing

GPL-2.0-only, matching the vendor modules' own `license=GPL`.
