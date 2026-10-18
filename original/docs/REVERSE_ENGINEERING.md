# H3C HM2004-DU FTTR / M-OLT subsystem — reverse-engineering dossier

Everything in this document was recovered by disassembling and inspecting the
artefacts listed below. Every constant, offset and byte sequence is backed by a
concrete observation; where a claim is an inference rather than a measurement it
is marked **inferred**, and where the evidence is insufficient it is marked
**unknown**.

Scope: the "FMCS" downlink FPGA that gives the HM2004-DU its FTTR (fiber to the
room) master-OLT function, the kernel modules that drive it, the userspace tools
that talk to them, and the FPGA configuration bitstream.

---

## 1. Hardware topology

The HM2004-DU is an Airoha AN7581/EN7581 (aarch64) FTTR **main** gateway. In
addition to the normal G-PON uplink it contains a second, H3C-proprietary PON
implementation built around an FPGA, referred to throughout the vendor
firmware as **FMCS** ("FPGA management control system"), which acts as the
master OLT (**M-OLT**) for up to 16 FTTR sub-ONUs.

Evidence for the role:

| Observation | Source |
| --- | --- |
| The module's own description string is `fpga management control system Module` | `fmcs.ko` `.modinfo` |
| Net devices are named `molt_ploam` and `molt_omci` — "molt" = master OLT | `fmcs.ko` `.rodata.str1.8+0x0a68`, `+0x09a0` |
| Sub-ONU data path resolves `eth1` and `eth1.1` … `eth1.16` | `fmcs.ko:FmcsFttrEthNetDevInit` |
| Userspace stack is `moltd`, `moltcmd`, `libminiolt.so`, `libmolt_svc.so`, `libmoltapi.so` | stock rootfs `/userfs/bin`, `/lib` |
| Register access is via SPI to an FPGA; PLOAM/OMCI are bridged to the SoC MAC | `fmcs.ko:FmcsSpi*`, `FmcsFttr*Hook` |

The FPGA is a **Pango Microsystems (紫光同创)** part: the configuration
bitstream `/lib/firmware/FTTR_TOP.sbit` begins with the ASCII vendor banner
`PANGO MICROSYSTEMS, INC.`.

Board wiring, taken verbatim from the stock device tree (recovered from the
DTB appended to `mtd2_kernel.bin` at file offset `0x21fc`):

```
fmcs {
    compatible = "h3c,fmcs";
    spi-controller = <0xb>;          /* phandle -> spi_controller@1fa10000 */
    fpga-spi-int-gpio = <0x17>;      /* GPIO 23                            */
    interrupts = <0x0 0x1a 0x1>;     /* GIC SPI 26, IRQ_TYPE_LEVEL_HIGH    */
    fpga-load-rst-gpio        = <0x0>;
    fpga-load-cfg-done-gpio   = <0x0>;
    fpga-load-flag-gpio       = <0x0>;
    fpga-load-clk-gpio        = <0x0>;
    fpga-load-do-gpio         = <0x0>;
};
```

`spi_controller@1fa10000` is `compatible = "econet,ecnt-spi_ctrl"`, and the same
device tree reserves MDIO addresses `0x0d`/`0x0e` next to the EN8811H PHY at
`0x0f` as "the FMCS downlink FPGA". So the FPGA has:

* a **runtime register interface on the SoC SPI controller** (`0x1fa10000`,
  phandle `0xb`) — used for register reads/writes and for PLOAM transport;
* an **interrupt line** on GIC SPI 26, whose trigger is gated through GPIO 23;
* a **separate configuration port** wired to plain GPIOs, used once at boot to
  load `FTTR_TOP.sbit` (see §6).

The five `fpga-load-*-gpio` properties are all zero in the shipped DTB and are
never read by any shipped module — `fpga_load.ko` has no `of_*` dependency at
all. They are vestigial. **Unknown:** whether "0" meant "unset" or literally
GPIO 0.

---

## 2. Artefact inventory

From `D:\H3C\bak\mtd3_rootfs` (an extracted `mtd3_rootfs.bin`, 32571392 bytes):

| Path | Size | Role |
| --- | --- | --- |
| `lib/modules/fmcs.ko` | 75072 | FMCS FPGA driver — SPI, GPIO IRQ, `/dev/fmcs_mci`, netdevs, genetlink |
| `lib/modules/fpga_load.ko` | 12024 | One-shot bitstream loader, GPIO bit-bang on `/proc/fpgaLoad` |
| `lib/firmware/FTTR_TOP.sbit` | 2087000 | Pango FPGA configuration bitstream |
| `usr/bin/miniolt` | 16904 | CLI: FPGA/BOSA register access, PLOAM/OMCI injection |
| `usr/bin/moltdbg` | 23528 | M-OLT debug CLI |
| `usr/bin/momci` | 263472 | OMCI helper |
| `usr/bin/ploam` | 198144 | PLOAM daemon |
| `userfs/bin/moltd` | 1417512 | M-OLT daemon |
| `userfs/bin/moltcmd` | 36192 | M-OLT command-line front end |
| `userfs/bin/omci` | 483840 | OMCI stack |
| `userfs/bin/omcicfgCmd` | 35360 | OMCI configuration CLI |
| `lib/libminiolt.so` | 16752 | miniolt client library |
| `lib/libminiolt_svc.so` | 73784 | miniolt service library |
| `lib/libmolt_svc.so` | 35320 | M-OLT service library |
| `lib/libmoltapi.so` | 10032 | M-OLT API |
| `lib/libmoltlog.so` | 18480 | M-OLT logging |
| `lib/libapi_omci_adpt.so.1.0.0` | 908256 | OMCI adaptation layer |
| `lib/libapi_omci_lib.so.2.2.2` | 42952 | OMCI library |
| `dev/fmcs_mci` | 0 | Device node shipped in the rootfs |
| `userfs/led_fpga.conf` | 3626 | LED mapping driven through FPGA registers |
| `boaroot/cgi-bin/sta-fttr_molt.asp` | 10604 | Web UI page for M-OLT status |
| `boaroot/cgi-bin/sta-fttr_onu.asp` | 10876 | Web UI page for sub-ONU status |
| `boaroot/cgi-bin/fttr_onulist.cgi` | 274 | CGI helper |
| `boaroot/cgi-bin/fttr_moltinfo.cgi` | 440 | CGI helper |
| `boaroot/cgi-bin/fttr_onuaction.cgi` | 1128 | CGI helper |
| `usr/script/mosquitto_fttr_sub.sh` | 1881 | MQTT bridge for sub-ONU data |

Both kernel modules are **unstripped**: `.symtab` is present and every function
has a name. That is what made this reverse engineering tractable.
`fmcs.ko` `.modinfo`:

```
version=V2024-0418-0001
license=GPL
description=fpga management control system Module
srcversion=533BB7E5866E52F63B9ACCB
name=fmcs
vermagic=5.4.55 SMP mod_unload aarch64
```

`fpga_load.ko` `.modinfo`:

```
license=GPL
name=fpga_load
vermagic=5.4.55 SMP mod_unload aarch64
```

Both were built with `GCC: (Buildroot -gd7e7e55) 10.3.0` (`AArch64 GCC 10.3.0`),
and neither uses symbol versioning (`CONFIG_MODVERSIONS` off in the vendor
kernel), so `vermagic` alone gates loading.

---

## 3. SPI wire protocol (runtime register access)

The vendor SPI core exposes two calls, `spi_device_write(buf, len)` and
`spi_device_read(tx, tx_len, rx, rx_len)`. Only these six transactions are ever
issued.

### 3.1 FPGA register write — opcode `0xA8`

`FmcsSpiWriteFpgaReg(u32 addr, u32 value)` builds a 9-byte frame on the stack
and calls `spi_device_write(buf, 9)`:

```
offset  0     1   2   3   4     5   6   7   8
        A8    addr (big-endian)   value (big-endian)
```

Disassembly evidence (`FmcsSpiWriteFpgaReg`, `fmcs.ko` `.text+0x430`):

```
mov  w4, #-0x58        ; 0xffffffa8 -> low byte 0xA8
rev  w3, w0            ; byte-swap addr   -> big-endian
rev  w2, w1            ; byte-swap value  -> big-endian
strb w4, [sp, #0x3f]   ; buf[0] = 0xA8
stp  w3, w2, [sp, #0x40]  ; buf[1..4] = addr_be, buf[5..8] = value_be
mov  w1, #9            ; len = 9
bl   spi_device_write
```

Return value is 1 on success, 0 on failure, and callers compare against 1
(`and w0, w0, #0xffff; cmp w0, #1; b.ne error`).

### 3.2 FPGA register read — opcodes `0xA0` then `0x50`

`FmcsSpiReadFpgaReg(u32 addr, u32 *out)` is a **two-phase** transaction:

1. `spi_device_write(buf, 5)` with `buf = { 0xA0, addr_be32 }` — issue the read
   command;
2. `__const_udelay(0x346de)` — a delay in the region of 50 µs (**inferred**:
   see §3.7);
3. `spi_device_read(buf, 1, rx, 4)` with `buf[0] = 0x50` — clock out 4 bytes;
4. `*out = be32(rx[0..3])`.

Evidence for the result assembly (`.text+0x5b4`):

```
ldrb w1, [sp, #0x34]   ; rx[0]
ldrb w3, [sp, #0x35]   ; rx[1]
ldrb w2, [sp, #0x36]   ; rx[2]
ldrb w4, [sp, #0x37]   ; rx[3]
lsl  w3, w3, #0x10
add  w1, w3, w1, lsl #24   ; rx[0]<<24 | rx[1]<<16
add  w2, w4, w2, lsl #8    ; rx[2]<<8  | rx[3]
add  w1, w1, w2
str  w1, [x20]
```

The command byte `0xA0` is formed with `mov w0,#0xa; bfi w3,w0,#4,#4`, i.e. the
high nibble holds the opcode and the low nibble is zero.

### 3.3 BOSA register write — opcode `0xA8`

`FmcsSpiWriteBosaReg` is byte-for-byte identical to `FmcsSpiWriteFpgaReg`
(`.text+0x650` vs `.text+0x430`): same `0xA8` opcode, same 9-byte frame, same
`0xffffffa8` immediate. The two are distinguished by register address, not by
opcode — the FPGA is transparently bridging the BOSA (optical sub-assembly)
register window.

### 3.4 BOSA register read — opcodes `0xA0` then `0x50`

Same shape as §3.2 but with a longer inter-phase delay,
`__const_udelay(0x275268)` (≈600 µs, **inferred**), and the result is only
**one byte**, taken from the **last** received byte:

```
ldrb w1, [sp, #0x37]   ; rx[3]
str  w1, [x20]
```

### 3.5 PLOAM transmit — opcode `0xAA`

`FmcsSpiSendPloamMsg(const u8 *ploam)` builds an 18-byte frame:

```
offset  0     1   2   3   4     5 .. 17
        AA    00  00  00  00    ploam[0..12]
```

The 13-byte payload is copied with two overlapping 64-bit stores
(`ldr x1,[x2]` at `buf+5` and `ldur x2,[x2,#5]` at `buf+10`), which is the
compiler's idiom for an unaligned 13-byte struct copy; the overlap resolves to
`buf[5..17] == ploam[0..12]`. `stur wzr,[sp,#0x26]` before the stores zeroes
`buf[0..3]`, so bytes 1–3 of the frame are zero and byte 0 is then overwritten
with `0xAA`.

### 3.6 PLOAM receive — opcodes `0xA2` then `0x52`

1. `spi_device_write(buf, 5)` with `buf = { 0xA2, 0x10, 0x00, 0x00, 0x00 }`;
2. `__const_udelay(0x346de)` — same delay as §3.2;
3. `spi_device_read(buf, 1, rx, 13)` with `buf[0] = 0x52`;
4. `out[0..12] = rx[0..12]` (again two overlapping 64-bit stores).

### 3.7 Delay constants

The delay helpers are called as `__const_udelay(N)` with `N` a literal:

| Call site | Literal | Plausible intent |
| --- | --- | --- |
| FPGA read inter-phase | `0x346DE` = 214494 | ≈50 µs |
| PLOAM receive inter-phase | `0x346DE` = 214494 | ≈50 µs |
| BOSA read inter-phase | `0x275268` = 2573928 | ≈600 µs |
| `fpga_load.ko` nCONFIG low | `0x10C7` = 4295 | 1 µs |
| `fpga_load.ko` nCONFIG high → status check | `0x147AEB8` = 21479128 | ≈5 ms |
| `fpga_load.ko` status check → bitstream | `0x13A934` = 1286452 | ≈300 µs |
| `fpga_load.ko` config done → reset release | `0x418958` = 4297048 | ≈1 ms |

The microsecond figures are **inferred**, not measured: `__const_udelay()` takes
loop counts whose scale depends on `loops_per_jiffy`, so the literals cannot be
converted to time exactly from the binary alone. What *is* exact is that the
ratio of `0x147AEB8` to `0x10C7` is 5000.96, of `0x13A934` to `0x10C7` is 299.5
and of `0x418958` to `0x10C7` is 1000.5 — i.e. the four values stand in the
ratio 1 : 5000 : 300 : 1000, which is why they are read here as 1 µs, 5 ms,
300 µs and 1 ms. A port should preserve the raw `__const_udelay()` arguments
rather than the rounded microsecond values.

### 3.8 SPI device instantiation

`FmcsSpiInit()` calls `spi_device_init()` and then registers a platform driver
matching `h3c,fmcs`:

```
bl   spi_device_init
adrp x1, __this_module
adrp x0, .data+1728          ; &stFmcsSpiDriver
bl   __platform_driver_register
```

`spi_device_init` is called with no argument set up by the compiler, and
`FmcsSpiDriverProbe` never reads the `spi-controller` phandle. The SPI device is
therefore **hard-coded inside the vendor SPI core**, not derived from the device
tree. **Unknown:** the bus and chip-select numbers it uses.

`FmcsSpiDriverProbe` (`fmcs.ko` `.text+0xb70`) does read the device tree, but
only for the interrupt:

```c
priv = devm_kmalloc(&pdev->dev, 0x18, GFP_KERNEL);
pstFmcsSpiDev = priv;
of_property_read_variable_u32_array(np, "fpga-spi-int-gpio", &priv->gpio, 1, 0);
priv->irq = platform_get_irq(pdev, 0);
priv->trigger_type = 3;
FmcsSpiIntGpioInit();
request_threaded_irq(priv->irq, NULL, FmcsSpiGpioIsr, 0, "fmcs", NULL);
priv->dev = &pdev->dev;
```

with `struct fmcs_spi_priv { struct device *dev; u32 gpio; int irq; u32 trigger_type; }`
(offsets 0x00, 0x08, 0x0c, 0x10 — size 0x18).

`FmcsSpiGpioIsr()` is the threaded handler and is three instructions long:

```c
FmcsWakeUpPloamThread();
dmb(oshst);
*(u32 *)(g_gpio_base + 0x08) = 0xffffffff;   /* clear all GPIO interrupts */
return IRQ_HANDLED;
```

`FmcsSpiIntGpioInit()` programs the trigger type through raw writes to the ECNT
GPIO block, two bits per GPIO:

* if `gpio > 15`: clear the 2-bit field in `base + 0x20`, then set it in `base + 0x80`;
* else: clear the 2-bit field in `base + 0x00`, then set it in `base + 0x0c`;
* field shift is `(gpio & 0xf) * 2`;
* if `(trigger_type & 3) == 0` it logs and returns failure without touching hardware.

---

## 4. `/dev/fmcs_mci` ioctl ABI

`FmcsMciInit()` (`fmcs.ko` `.text+0x26e0`) calls
`register_chrdev_region(MKDEV(0xE6, 0), 1, "fmcs_mci")` — a **fixed major of
230** — registers a sysfs class named `fmcs_mci`, and adds the cdev. The
rootfs ships a pre-made `/dev/fmcs_mci` node.

### 4.1 Dispatcher

`FmcsMciIoctl()` rejects anything whose bits 8..15 are not `0xa5` *before*
taking the global mutex, then dispatches:

| Command | `_IOC` spelling | Handler | Argument |
| --- | --- | --- | --- |
| `0x4008a500` | `_IOW('a5', 0, struct fmcs_reg)` | `FmcsMciIoctlWriteFpgaReg` | `struct fmcs_reg` in |
| `0xc008a501` | `_IOWR('a5', 1, struct fmcs_reg)` | `FmcsMciIoctlReadFpgaReg` | `struct fmcs_reg` in/out |
| `0x4008a502` | `_IOW('a5', 2, struct fmcs_reg)` | `FmcsMciIoctlWriteBosaReg` | `struct fmcs_reg` in |
| `0xc008a503` | `_IOWR('a5', 3, struct fmcs_reg)` | `FmcsMciIoctlReadBosaReg` | `struct fmcs_reg` in/out |
| `0x4008a504` | `_IOW('a5', 4, __u8[13])` | `FmcsMciIoctlSendPloam` | 13-byte PLOAM frame |
| `0x8008a505` | `_IOR('a5', 5, __u8[13])` | `FmcsSpiRecvPloamMsg` | **ignored** |
| `0x4001a506` | `_IOW('a5', 6, __u8)` | `FmcsMciIoctlSendHsgmiiPacket` | **repetition count, not a pointer** |

The dispatcher's own constants, as decoded from the compare chain:

```
mov  w0, #0xa504 ; movk w0, #0x4008, lsl #16   -> 0x4008a504  (send ploam)
sub  w0, w0, #4                                 -> 0x4008a500  (wr fpga)
add  w0, w0, #2                                 -> 0x4008a502  (wr bosa)
mov  w0, #0xa501 ; movk w0, #0xc008, lsl #16   -> 0xc008a501  (rd fpga)
add  w0, w0, #2                                 -> 0xc008a503  (rd bosa)
mov  w0, #0xa505 ; movk w0, #0x8008, lsl #16   -> 0x8008a505  (recv ploam)
mov  w0, #0xa506 ; movk w0, #0x4001, lsl #16   -> 0x4001a506  (hsgmii)
```

Any other `0xa5`-typed command logs `Fmcs ioctl do not have this cmd!` when
`uiLogLevel` bit 1 is set, and returns `-EINVAL` (`-0x16`).

### 4.2 Argument structure

`struct fmcs_reg { __u32 addr; __u32 value; }` — 8 bytes. For writes both words
are consumed (`ldp w0, w1, [x19]` then `FmcsSpiWriteFpgaReg(addr, value)`). For
reads the helper `FmcsMciIoctlReadReg()` copies 8 bytes in, passes a pointer to
the **second word** (`ldr w0,[x1],#4` post-index leaves `x1 = kbuf + 4`) as the
read function's output slot, and then copies all 8 bytes back out — so the read
ioctls are genuinely `_IOWR`.

### 4.3 Semantics worth reproducing exactly

* **Write path returns 0 or `-EFAULT`.** `FmcsMciIoctlWriteFpgaReg` returns
  `-EFAULT` (`-0xe`) if the SPI write did not report success, `0` otherwise.
  `FmcsMciIoctlReadFpgaReg` propagates this through `FmcsMciIoctlReadReg`,
  which also returns `-EFAULT` on both `copy_from_user` and `copy_to_user`
  failure.
* **`FMCS_IOC_SEND_PLOAM` leaks.** `FmcsMciIoctlSendPloam` does
  `kmalloc(13, GFP_KERNEL)`, and on `copy_from_user` failure returns `-EFAULT`
  **without freeing the buffer**. This is a vendor defect, not behaviour to
  preserve; see §9.
* **`FMCS_IOC_RECV_PLOAM` always returns 0** and its argument is never touched.
  The received message is not returned to the caller at all — the call is a
  trigger, and the payload arrives through genetlink (`genl_PLOAM_NET`) or the
  `molt_ploam` netdev.
* **`FMCS_IOC_SEND_HSGMII` takes a count.** `FmcsMciIoctlSendHsgmiiPacket`
  loops `count` times, each iteration doing
  `alloc_skb(0x80, GFP_ATOMIC)`, `skb_put(skb, 0x80)`,
  `memset(skb->data, 0xA5, 0x80)`, stamping a 16-byte header from `.rodata`,
  setting `skb->dev` to the `eth1` netdev, and handing the skb to the vendor
  hook `__ECNT_HOOK(0x40, 0, &info, 4, skb->data)`. It logs
  `prepare to send packet to hsgmii` / `now send packet to hsgmii , CNT = %lu`.
  It does **not** validate `count` beyond treating it as `u8`.

---

## 5. Network data path

`FmcsNetDeviceInit()` builds, in order:

1. `FmcsFttrEthNetDevInit()` — `dev_get_by_name(&init_net, "eth1")` plus
   `eth1.1` … `eth1.16`, all resolved by name and cached in
   `g_apstFmcsFttrSubPonDev[16]` / `g_pstFmcsFttrMainPonDev`. **If any one is
   missing the whole module fails to load**, which means the sub-interface
   naming scheme is load-bearing.
2. `FmcsPloamNetDeviceInit()` — `alloc_netdev_mqs(0xb8, "molt_ploam", …,
   ether_setup, 1, 1)`, `flags &= ~IFF_MULTICAST`, `flags |= IFF_BROADCAST |
   IFF_NOARP`, MAC copied from `aucFmcsPloamNetDevMac`, `register_netdev()`.
3. `FmcsOmciNetDeviceInit()` — same shape, netdev `molt_omci`, MAC from
   `aucFmcsOmciNetDevMac`.
4. Installs the Ethernet-driver hooks:

```
hsgmii_lan_mac_tx_h3c_fttr_hook = FmcsFttrTxHook;   /* fmcs.ko .text+0x11e0 */
hsgmii_lan_mac_rx_h3c_fttr_hook = FmcsFttrRxHook;   /* fmcs.ko .text+0x1960 */
```

Both MAC globals are zeroed again on every error path, so they are a pair of
function-pointer slots owned by the vendor Ethernet driver and filled in by this
module. This is the single hardest thing to port: mainline and OpenWrt have no
such hook, so the new driver needs an equivalent registration mechanism.

`FmcsPloamNetDevStartXmit(skb, dev)` transmits `skb->data + 8` through
`FmcsSpiSendPloamMsg()` and then bumps `tx_packets` and `tx_bytes` by 13. The
8-byte skip is a vendor header convention whose layout is **unknown**.

---

## 6. FPGA configuration (bitstream loading)

There are two distinct mechanisms and only one of them works.

### 6.1 `fmcs.ko` — stubs

`fmcs.ko` exports `FmcsInitFpgaLoadRstGpio` and `FmcsInitFpgaRstGpio`, but both
have `st_size == 4`, i.e. a bare `ret`. The FMCS driver does **not** configure
the FPGA; it only consumes the result.

### 6.2 `fpga_load.ko` — the real loader

`fpga_load.ko` is a self-contained, hard-coded, GPIO bit-bang loader with no
device-tree dependency whatsoever. It is 100 % static: the GPIO numbers are
compile-time constants, and the module exposes its knobs through `/proc`.

**Global state** (`.bss`, 32 bytes):

```c
static unsigned holdtime2;   /* .bss+0x00 */
static unsigned holdtime1;   /* .bss+0x04 */
static struct file *File;    /* .bss+0x08 */
static loff_t file_size;     /* .bss+0x10 */
static char *FirmBuf;        /* .bss+0x18 */
```

**`ReadFirmToMemory()`** (`.text+0x0`):

```c
File = filp_open("/lib/firmware/FTTR_TOP.sbit", O_RDONLY, 0);
if (IS_ERR(File)) { printk("Error: Failed to open file"); File = NULL; return -1; }
file_size = File->f_inode->i_size;
FirmBuf = kmalloc(file_size, GFP_KERNEL);
if (!FirmBuf) {
    filp_close(File, NULL); File = NULL;
    printk("Error: Failed to allocate memory");
    return -1;
}
memset(FirmBuf, 0, file_size);
kernel_read(File, FirmBuf, file_size, &pos);
filp_close(File, NULL);
File = NULL;
return 0;
```

**`GpioStatInit()`** (`.text.unlikely+0x344`) muxes and enables four GPIOs by
poking the ECNT GPIO block directly, then prints `gpio set complete.`:

```
regs[0x00] |=  (1 << 10)
regs[0x20] &= ~(3 << 22)
regs[0x14] &= ~(1 << 27)
regs[0x20] |=  (1 << 26)
regs[0x20] |=  (1 << 28)
regs[0x20] &= ~(3 << 24)
regs[0x14] &= ~(1 << 28)
regs[0x20] |=  (1 << 12)
regs[0x04] |=  (1 << 5)      /* data latch for nCONFIG */
regs[0x04] &= ~(1 << 29)     /* CLK low  */
regs[0x04] &= ~(1 << 30)     /* DATA low */
regs[0x04] &= ~(1 << 22)     /* RST low  */
regs[0x14] |=  (1 << 5)      /* output enable: nCONFIG */
regs[0x14] |=  (1 << 29)     /* output enable: CLK     */
regs[0x14] |=  (1 << 30)     /* output enable: DATA    */
regs[0x14] |=  (1 << 22)     /* output enable: RST     */
```

Signal map, decoded from the bit positions used throughout the module:

| Signal | GPIO block bit | Register |
| --- | --- | --- |
| `nCONFIG` (program request) | 5 | data @ `0x04`, OE @ `0x14` |
| `RST` (FPGA reset) | 22 | data @ `0x04`, OE @ `0x14` |
| `CLK` | 29 | data @ `0x04`, OE @ `0x14` |
| `DATA` (to FPGA) | 30 | data @ `0x04`, OE @ `0x14` |
| state flag (pre-config) | 27 | read via `GET_GPIO_DATA()` |
| config done | 28 | read via `GET_GPIO_DATA()` |

`GET_GPIO_DATA` is an **undefined symbol** resolved at module load — it is a
function exported by the vendor GPIO driver that returns the current 32-bit pin
levels. It is not a register offset the module knows about.

**`WriteFirmToFpga(buf, len)`** (`.text.unlikely+0x30`) — the configuration
clock:

```c
printk("write firm......");
for (p = buf; p != buf + len; p++) {
    for (i = 7; i >= 0; i--) {
        if ((*p >> i) & 1) regs[0x04] |=  (1 << 30);
        else               regs[0x04] &= ~(1 << 30);
        ndelay(holdtime1);
        regs[0x04] |=  (1 << 29);      /* CLK rising */
        ndelay(holdtime1);
        regs[0x04] &= ~(1 << 29);      /* CLK falling */
        ndelay(holdtime2);
    }
    cond_resched();
}
```

Each byte is shifted out **MSB first**, immediately after being set (no setup
delay is inserted before the first data bit beyond the previous iteration's
falling-edge delay). `holdtime1` and `holdtime2` are unsigned globals that the
`/proc` interface can change at runtime; both default to 0.

**`DebugWriteFirmToFpga(buf, len)`** (`.text.unlikely+0x104`) is the same loop
with read-back assertions after every transition:

| Transition | Expected read-back | Message on mismatch |
| --- | --- | --- |
| DATA = 1 | bit 30 set | `Data value error,hope 1.` |
| DATA = 0 | bit 30 clear | `Data value error,hope 0.` |
| CLK = 1 | bit 29 set | `Clk value error,hope 1.` |
| CLK = 0 | bit 29 clear | `Clk value error,hope 0.` |

Nothing in the shipped module calls it; it exists for bring-up.

**`ExeLoadOnce()`** (`.text.unlikely+0x254`) — the full sequence:

```c
printk("Fpga load start......");
if (ReadFirmToMemory() != 0) goto out;

regs[0x04] &= ~(1 << 5);            /* nCONFIG low  */
__const_udelay(0x10C7);             /* ~1 us        */
regs[0x04] |=  (1 << 5);            /* nCONFIG high */
__const_udelay(0x147AEB8);          /* ~5 ms        */

if (!(GET_GPIO_DATA() & (1 << 27)))
    printk("Check fpga state flag fail.");

__const_udelay(0x13A934);           /* ~300 us */

WriteFirmToFpga(FirmBuf, file_size);

if (GET_GPIO_DATA() & (1 << 28)) {  /* config done */
    __const_udelay(0x418958);       /* ~1 ms       */
    regs[0x04] |= (1 << 22);        /* RST release */
    printk("Fpga load and rst success.");
} else {
    printk("Fpga load and rst fail.");
}

out:
if (FirmBuf) { kfree(FirmBuf); FirmBuf = NULL; }
```

Note the failure path still frees the buffer, and that a failed state-flag check
does **not** abort — it only logs.

**`init_module()`** (`.text+0x2b0`):

```c
holdtime2 = 0;
holdtime1 = 3;
File = NULL;
FirmBuf = NULL;
pe = create_proc_entry("fpgaLoad", 0666, NULL);
if (!pe) { printk("Failed to create proc entry"); return -ENOMEM; }
pe-><slot A> = WriteFirmToFpga;
pe-><slot B> = fpga_load_write;      /* the sscanf handler at .text+0x110 */
GpioStatInit();
ExeLoadOnce();
return 0;
```

So **loading the module immediately loads the FPGA**, and the module parameter
`holdtime1` defaults to **3** while `holdtime2` defaults to **0** — the `.bss`
zero-init only covers `holdtime2`, `holdtime1` is explicitly set to 3.

`cleanup_module()` closes `File` if open, `kfree`s `FirmBuf` if set, and calls
`remove_proc_entry("fpgaLoad", NULL)`.

### 6.3 `/proc/fpgaLoad`

`fpga_load_write()` (`.text+0x110`) parses the written buffer with
`sscanf(buf, "%31s %u %u %31s", tok, &t1, &t2, tok2)` and compares the first
token against `"load"`. On mismatch it prints `wrong fpga load cmd` and returns
the byte count. On match it applies a **floor of 3** to `t1`
(`cmp w0, #2; b.ls` — a value of 2 or less leaves `holdtime1` unchanged),
assigns `t2` to `holdtime2` unconditionally, prints
`Set hold time success, t1 = %u, t2 = %u.`, and re-runs
`GpioStatInit(); ExeLoadOnce();`.

The read direction is **broken in the shipped binary**: the string
`Fpga load info: holdtime1 = %u, holdtime2 = %u.` is present in
`.rodata.str1.8` at offset 0 but is never referenced by any instruction in the
module, and one of the two `proc_dir_entry` slots is filled with
`WriteFirmToFpga` — whose `(u8 *, size_t)` signature cannot serve as a
`read_proc_t`. **Inferred:** the read handler was removed late in development
and the slot assignment was not repaired. A port should provide a working read
handler, since the information is obviously meant to be readable.

So the operational interface is:

```sh
echo "load 100 100 x" > /proc/fpgaLoad     # t1=100, t2=100, then reload
```

(the fourth `%31s` token is parsed but never compared).

---

## 7. `FTTR_TOP.sbit`

* Size 2087000 bytes = 16 696 000 bits.
* First 16 bytes: `00 09 0f f0 0f f0 0f f0 0f f0 00`, followed by the ASCII
  banner `PANGO MICROSYSTEMS, INC. …`.
* **The loader does not parse it.** `ReadFirmToMemory()` reads the whole file
  into a buffer of exactly `i_size` and `WriteFirmToFpga()` shifts out every
  byte from the first, MSB first, with no header skip and no transformation.

**Conclusion:** for a faithful port, `FTTR_TOP.sbit` can be fed to the
configuration port byte-for-byte in order.

The file's own metadata block names the part, which is worth recording because
it fixes the search space for anything else that has to talk to the FPGA:

| Field | Value |
| --- | --- |
| Project | `FTTR_TOP` |
| Device | `Logos-PGL50H--6-FBG484` |
| Vendor / tool | Pango Microsystems, Fabric Compiler `2022.2<117120>` |
| Built | 11/04/2024 20:41:18 |

So the FPGA is a **Pango Logos PGL50H**, speed grade 6, in an FBG484 package —
roughly a 50 k-LUT class device, consistent with the 16.7 Mbit stream.

The header is a 141-byte block: an 11-byte magic, the vendor string, and six
`tag:u8 / len:u16be / NUL-terminated value` records running from `0x25` to
`0x8A`, followed by 1492 zero bytes. It carries **no length, checksum or
device-ID field** a loader could act on, which is exactly why the vendor loader
can ignore it and why this port does too.

Full byte-level analysis, the falsified encoding hypotheses and the marker map
are in [`SBIT_FORMAT.md`](SBIT_FORMAT.md), reproducible with
`../tools/sbit_analyze.py`.

---

## 8. Userspace: `miniolt`

`usr/bin/miniolt` is an `ET_EXEC` aarch64 binary, dynamically linked against
`libc.so.6` only, with interpreter `/lib/ld-linux-aarch64.so.1`, entry
`0x400900`, and a mere 4788 bytes of `.text`. It is small enough to reverse
completely.

Imports (from `.dynsym`, resolved through `.rela.plt` in GOT order
`0x413000…0x413080`):

```
sendto bind open strncmp __libc_start_main memset sleep strerror
close __gmon_start__ abort puts socket __isoc99_sscanf printf
__errno_location ioctl
```

Its string table names every operation it performs:

```
create ploam net dev socket failed
molt_omci
get net dev index failed
binding ploam net dev socket failed
create net dev sock success. iSock = %d
PloamSendMsgToNetDev. iSock = %d
send omci msg to net dev faield, errno = %d
/dev/fmcs_mci
[%s:%d]:open /dev/fmcs_mci failed!!
[%s:%d]:ioctl /dev/fmcs_mci failed!! ret = %d, %s
read        bosa   [%s:%d]:read bosa reg      [%s:%d]:read fpga reg
reg addr  : 0x%X     reg value : 0x%X
write       [%s:%d]:write bosa reg            [%s:%d]:write fpga reg
send        ploam
%02hhx%02hhx%02hhx%02hhx%02hhx%02hhx%02hhx%02hhx%02hhx%02hhx%02hhx%02hhx%02hhx
hsgmii      omci     uiCrc = %x     recv      unkown!!!
MiniOltWriteFpgaReg   MiniOltWriteFpgaRegForCmd   MiniOltReadFpgaReg
```

### 8.1 Socket setup — `CreatePloamNetDevSocket()`

```c
int CreatePloamNetDevSocket(void)
{
    int fd = socket(AF_PACKET /*17*/, SOCK_RAW /*3*/, htons(ETH_P_ALL /*3*/));
    if (fd == -1) { puts("create ploam net dev socket failed"); return -1; }

    struct sockaddr_ll sll;
    memset(&sll, 0, sizeof(sll));        /* 20 bytes */
    sll.sll_family   = AF_PACKET;
    sll.sll_protocol = htons(ETH_P_ALL);

    struct ifreq ifr;
    memcpy(ifr.ifr_name, "molt_omci", 9);

    for (i = 10; i > 0; i--) {
        if (ioctl(fd, SIOCGIFINDEX /*0x8933*/, &ifr) == 0) break;
        sleep(2);
    }
    if (i <= 0) {
        puts("get net dev index failed");
        close(fd);
        return -1;
    }

    sll.sll_ifindex = ifr.ifr_ifindex;
    if (bind(fd, (struct sockaddr *)&sll, sizeof(sll)) == -1) {
        puts("binding ploam net dev socket failed");
        close(fd);
        return -1;
    }
    printf("create net dev sock success. iSock = %d", fd);
    return fd;
}
```

Note the **ten retries at two-second intervals**: miniolt is written to start
before `molt_omci` exists and to wait up to 20 s for the FMCS driver to bring it
up. This is a hard sequencing requirement for the port — the driver must create
`molt_omci` for the tool to make progress.

`PloamSendMsgToNetDev(const void *msg, u8 len)` is a thin `sendto()` wrapper
that prints `send omci msg to net dev faield, errno = %d` on `-1`.

### 8.2 Register access

`MiniOltWriteFpgaReg(int idx, int value)` opens `/dev/fmcs_mci` `O_RDWR`,
issues `ioctl(fd, 0x4008a500, &reg)` and closes. `MiniOltWriteFpgaRegForCmd`
is the same with a different diagnostic banner. `MiniOltReadFpgaReg(addr)`
issues `0xc008a501` and prints `reg addr : 0x%X` / `reg value : 0x%X`.

The `idx` argument indexes a 12-byte-stride table at `0x413098`
(`ldr w2,[sp,#0x1c]; mov x0,#0xc; mul; ldr w0,[x1,x0]`) — **unknown:** what
that table holds, since it is only read into a local that the error path also
overwrites. It does not affect the ioctl payload.

### 8.3 Command surface

From the string table plus the `sscanf` format, the CLI accepts, at minimum:

| Verb | Object | Arguments |
| --- | --- | --- |
| `read` | `bosa` / `fpga` | register address |
| `write` | `bosa` / `fpga` | register address, value |
| `send` | `ploam` | 13 hex byte pairs |
| `send` | `omci` | hex payload, prefixed by `uiCrc = %x` |
| `send` | `hsgmii` | repetition count (matches ioctl `0x4001a506`) |
| `recv` | — | pulls a PLOAM message |
| anything else | — | prints `unkown!!!` |

The 13-conversion `%02hhx` format string matches `FMCS_PLOAM_LEN == 13` exactly.

`read`/`write` go through `/dev/fmcs_mci` ioctls; `send ploam`/`send omci` go
through the AF_PACKET socket bound to `molt_omci`; `send hsgmii` uses the
`0x4001a506` ioctl whose argument is the count.

---

## 9. Defects in the original (do not reproduce blindly)

1. `FmcsMciIoctlSendPloam` leaks its 13-byte `kmalloc` buffer on
   `copy_from_user` failure.
2. `FmcsSpiDriverProbe` allocates `priv` and assigns `pstFmcsSpiDev` before
   validating the device tree; every later error path returns without clearing
   it, so a failed probe leaves a dangling pointer.
3. `FmcsSpiInit` logs `platform_driver_register ret = %d` unconditionally, even
   on success, and then logs both `fpga spi driver init success???` and
   `fpga spi driver init FAILED` on the same path.
4. `fpga_load.ko` assigns `WriteFirmToFpga` to one of the `proc_dir_entry`
   function-pointer slots; its signature cannot match `read_proc_t`.
5. `fpga_load.ko`'s read handler is missing altogether; its message string is
   dead in `.rodata`.
6. `FmcsMciIoctlSendHsgmiiPacket` casts an `unsigned long` ioctl argument to
   `u8` with no range check.
7. `FmcsFttrEthNetDevInit` fails the entire module when any `eth1.N` is absent,
   with no retry — order-sensitive against the Ethernet driver.
8. `SpiGpioIsr` clears **all** GPIO interrupts (`0xffffffff`), not just the
   FPGA's.

---

## 10. Porting plan and open risks

### 10.1 What is fully specified

* The ioctl ABI (§4) — reproduced verbatim in `driver/fmcs_uapi.h`.
* The SPI wire protocol (§3) — every frame, every delay, every opcode.
* The bitstream load sequence (§6) — every GPIO bit and every delay.
* The device-tree binding (§1) — recovered from the stock DTB.
* The netdev names and the sub-interface naming scheme (§5).
* The userspace contract (§8) — `miniolt` can be rebuilt against it.

### 10.2 Open problems

**R1 — no general-purpose SPI master.** In the 6.18 tree
(`qwe3017/ponwrt`, `target/linux/airoha/dts/an7581.dtsi`) the block the stock
DTB calls `spi_controller@1fa10000` (`econet,ecnt-spi_ctrl`) is claimed by
`snfi: spi@1fa10000` with `compatible = "airoha,en7581-snand"` — the SPI-NAND
driver — covering both `0x1fa10000` and `0x1fa11000`. Mainline
`drivers/spi/spi-airoha-snfi.c` is a NAND-specific controller driver and does
not offer generic `spi_sync()` transfers. The FMCS FPGA sits on a second
chip-select of that same controller. Consequences:

* the vendor `spi_device_write()` / `spi_device_read()` calls have no direct
  mainline equivalent;
* the port in this tree therefore routes register access through a **transport
  abstraction** with two implementations — a standard `spi_sync()` path (used
  automatically once a generic master exists for that controller) and an
  in-driver **GPIO bit-bang** path that needs four GPIO numbers;
* **unknown:** which SoC pins carry SCK/MOSI/MISO/CS for the FPGA, and which
  chip-select the vendor core used. The GPIO path has not been validated on
  the stock board; the `fmcs` node must not be enabled until the wiring and
  pin mux are established.

**R2 — the HSGMII hooks.** `hsgmii_lan_mac_tx_h3c_fttr_hook` and
`hsgmii_lan_mac_rx_h3c_fttr_hook` are `EXPORT_SYMBOL`-less globals owned by the
vendor Ethernet driver; `fmcs.ko` writes its own functions into them. The
OpenWrt airoha Ethernet driver has no equivalent. The port needs a registration
mechanism (an exported registry or a small patch adding two callbacks) before
FTTR traffic can flow. Until then PLOAM/OMCI over the netdevs and all register
access still work — the hooks only carry the 16 sub-ONU data path.

**R3 — `GET_GPIO_DATA` and `g_gpio_base`.** Both are exported by the vendor GPIO
driver. `fpga_load.ko` reads pin levels through the former and pokes registers
through the latter. A port must use `gpiod` descriptors and the pinctrl/GPIO
subsystem instead, which also means it must know *which* GPIO lines bits 5, 22,
29, 30 and 27/28 correspond to.

**R4 — `__ECNT_HOOK`.** Used only by the HSGMII stress-test ioctl, so it can be
dropped or reimplemented as a plain `dev_queue_xmit()`.

**R5 — register map above the driver.** `libminiolt_svc.so` and `moltd` own the
bulk of the FPGA register map (status, per-ONU tables, ranging, BOSA optical
values). The driver only needs the handful of addresses in §9 of the header.
Recovering the full map is the prerequisite for any rich LuCI status page and is
the natural next reverse-engineering step.

### 10.3 Deliverable layout

```
fttr-port/
  docs/REVERSE_ENGINEERING.md      this document
  driver/fmcs_uapi.h               userspace ABI (§4)
  driver/fmcs.c                    ported driver for 6.18
  driver/Kconfig, driver/Makefile
  userspace/miniolt.c              ported CLI (§8)
  dts/h3c-fmcs.dtsi                device-tree node (§1)
  openwrt/…                        kmod + tool packages
  luci/…                           LuCI application
```
