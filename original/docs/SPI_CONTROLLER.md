# ECNT/AN7581 SPI controller — register map and generic-transfer plan

This closes the last open question behind **R1**: how the vendor reaches the FMCS
FPGA registers, and what a generic `spi_sync()` path for the same block has to
do.

Two independent sources were cross-referenced and they agree register for
register:

* the vendor's own SPI core, recovered from the decompressed stock kernel
  (`vendor/vmlinux.bin`, symbols resolved through `vendor/ksymtab.txt`) —
  see [`VENDOR_KERNEL.md`](VENDOR_KERNEL.md);
* mainline `drivers/spi/spi-airoha-snfi.c`, which drives the **same** block for
  SPI-NAND and names every register.

---

## 1. The block is the same one mainline already drives

`spi_device_init` (`0x575460` in the image) maps physical **`0x1FA11550`**:

```
mov  x0, #0x1550
movk x0, #0x1fa1, lsl #16        ; 0x1FA11550
mov  x1, #4
bl   0x22830                     ; map-by-physical helper
```

The controller is then addressed as `[[ctrl]] + 8`, a mapped base, with these
offsets. The right-hand column is the mainline name for the identical offset —
this is the whole finding, because it turns unnamed offsets into documented
registers:

| Offset | Mainline register | Field layout | How the vendor uses it |
| --- | --- | --- | --- |
| `+0x00` | `REG_SPI_CTRL_STATUS`-class | — | `tst w1, #0xf` retry loop before a transfer |
| `+0x1C` | `REG_SPI_CTRL_MACMUX_SEL` | — | written during transfer setup |
| `+0x28` | `REG_SPI_CTRL_OPFIFO_WDATA` | `OP` = `GENMASK(13,9)`, `LEN` = `GENMASK(8,0)` | command + length, one word per transfer |
| `+0x2C` | `REG_SPI_CTRL_OPFIFO_FULL` | `BIT(0)` | polled until clear before writing `+0x28` |
| `+0x34` | `REG_SPI_CTRL_DFIFO_FULL` | `BIT(0)` | polled until clear before each TX byte |
| `+0x38` | `REG_SPI_CTRL_DFIFO_WDATA` | `GENMASK(7,0)` | one data byte per write |
| `+0x3C` | DFIFO status, RX side | — | polled until clear before each RX byte |
| `+0x40` | trigger | — | written `1` to pull one byte from the RX FIFO |
| `+0x44` | `REG_SPI_CTRL_DFIFO_RDATA` | `GENMASK(7,0)` | one data byte per read |
| `+0xE4` | controller enable | — | written `1` to enable around a transfer, `0` after |

The two rows that matter most are `+0x28` and the FIFO pair, because they are
where the vendor's arithmetic and the mainline field definitions are visibly the
same code:

```
vendor:    ubfiz w19, w19, #9, #5      ; op   -> bits 13:9
           orr   w19, w19, w20         ; len  -> bits  8:0
           str   w19, [base, #0x28]

mainline:  FIELD_PREP(SPI_CTRL_OPFIFO_OP,  op)
         | FIELD_PREP(SPI_CTRL_OPFIFO_LEN, len)
           regmap_write(regmap_ctrl, REG_SPI_CTRL_OPFIFO_WDATA, ...)
```

`GENMASK(13,9)` is five bits and `ubfiz ..., #9, #5` shifts five bits to bit 9;
`GENMASK(8,0)` is nine bits and the vendor masks the length with `#0x1ff`. There
is no room left for it to be a coincidence.

The mainline header spells the same offsets as `0x0028`, `0x002C`, `0x0034`,
`0x0038` and `0x0044` — the vendor's `+0x28`, `+0x2C`, `+0x34`, `+0x38` and
`+0x44`. Same block, same address, two independent naming schemes.

## 2. FIFO opcodes

`REG_SPI_CTRL_OPFIFO_WDATA.OP` selects the bus width and direction, and the
values are the mainline `SNAND_FIFO_*` constants verbatim:

| Value | Mainline name | Vendor call site |
| --- | --- | --- |
| `0x08` | `SNAND_FIFO_TX_BUSWIDTH_SINGLE` | `spi_data_rw(buf, len, dir = 0)` → op `dir + 8` |
| `0x09` | `SNAND_FIFO_TX_BUSWIDTH_DUAL` | `dir = 1` |
| `0x0A` | `SNAND_FIFO_TX_BUSWIDTH_QUAD` | `dir = 2` |
| `0x0C` | `SNAND_FIFO_RX_BUSWIDTH_SINGLE` | `spi_device_read` picks it from a table indexed by SPI mode |

So the vendor's third argument to `spi_data_rw` is a **bus-width selector for
transmit**, not a read/write flag — reads take a separate path. `spi_device_read`
indexes `0x9DC0C8` with the SPI mode and feeds the result straight into the OP
field, which is consistent with a three-entry table of
`{0x0C, 0x0E, 0x0F}`.

## 3. What the protocol needs, in mainline terms

The FMCS wire protocol in
[`REVERSE_ENGINEERING.md`](REVERSE_ENGINEERING.md) section 3 reduces to a small
set of primitives, each expressible in these registers:

| FMCS operation | Mainline equivalent |
| --- | --- |
| `A8 <addr> <val>`, 9 bytes out | select CS, `OP = 0x08`, `LEN = 9`, push 9 bytes to `DFIFO_WDATA` |
| `A0 <addr>`, 5 bytes out | CS, `OP = 0x08`, `LEN = 5`, push 5 bytes |
| `50` + 4 bytes in | CS, `OP = 0x0C`, `LEN = 4`, pull 4 bytes from `DFIFO_RDATA` |
| `AA` + 13 bytes, 18 bytes out | CS, `OP = 0x08`, `LEN = 18`, push 18 bytes |
| `A2 …`, then `52` + 13 bytes in | two transfers, CS held low across both |

Every transfer is byte-at-a-time PIO. The longest is 18 bytes, so the FIFO depth
is irrelevant and no DMA path is needed.

## 4. Why this is a patch to the SPI driver, not to the FMCS driver

The block is claimed in the 6.18 tree by:

```dts
snfi: spi@1fa10000 {
    compatible = "airoha,en7581-snand";
    reg = <0x0 0x1fa10000 0x0 0x140>,
          <0x0 0x1fa11000 0x0 0x160>;
    spi_nand: nand@0 { compatible = "spi-nand"; reg = <0>; };
};
```

`spi-airoha-snfi.c` registers a `spi_controller` but exposes only
`spi_controller_mem_ops` (`supports_op` / `exec_op`) — a SPI-MEM interface for
NAND, with no `transfer_one`. Two consequences:

1. The FPGA cannot be a plain `spi_device` child today, because nothing would
   service its transfers.
2. **The fix belongs in that driver.** It already owns `regmap_ctrl`, already has
   the register defines in section 1, and already knows how to share the block
   with the NAND side. Adding a `set_cs` and a `transfer_one` built on
   `OPFIFO_WDATA` + the data FIFO is a small, contained change there — whereas
   a second driver poking the same registers would race the NAND path.

The FMCS driver needs no change at all: `driver/fmcs_spi.c` already selects its
hardware-SPI back end whenever the device tree binds it as a SPI client, and its
wire protocol is written against `spi_write` / `spi_write_then_read`.

**There is no patch in this tree yet, deliberately.** Section 5 explains why the
one thing a patch would have to get right is still unresolved.

## 5. What is not yet established

Three offsets are read off the vendor binary without a mainline counterpart I
could confirm, and they are marked as such in the table above:

* `+0x3C` — an RX-side FIFO status polled until clear before each read. The
  mainline driver names `DFIFO_FULL` at `+0x34` but no counterpart at `+0x3C`
  was visible in the definitions I could retrieve.
* `+0x40` — a trigger written `1` per received byte. Behaviour is clear from the
  vendor loop; the name is not.
* `+0xE4` — an enable written around each transfer. `spi_device_write` sets it to
  `1` and restores `0` on the way out; whether that is a clock gate, a reset or a
  mode bit is not established.

**The blocker is the transmit framing.** `spi_device_write` does not issue a
single OPFIFO word for its payload. The recovered sequence is:

```
0x5757d0(&{1,1})        ; transfer setup, op selector 1
0x5755e0(1, 1)          ; OPFIFO_WDATA = (1 << 9) | 1
0x575b10(buf, len, 0)   ; data phase, chunks of <= 0x1ff, OPFIFO_WDATA = (8 << 9) | chunk
0x5755e0(0, 1)          ; OPFIFO_WDATA = (0 << 9) | 1
```

so every write is bracketed by an `OP = 1` word and an `OP = 0` word. `OP = 8`
is confirmed by the mainline constant table as single-bit transmit, but **what
`OP = 1` and `OP = 0` mean is not recovered**. They are plausibly a frame
selector, a chip-select pseudo-op, or a command/terminator pair for this
controller's generic mode; nothing read so far distinguishes those.

That matters because those two words are part of what the FPGA sees. A patch
that emitted only the data phase would put close to the right bytes on the wire
and still be wrong, which is a worse outcome than not shipping one.

### Next steps, in order

All of these are now addressable by name from `vendor/ksymtab.txt`:

1. `0x5757d0` — the transfer-setup function, whose argument selects between at
   least three register configurations (`+0x130`/`+0x14`/`+0x20` on one path,
   `+0x80` on another). Its `0x519d0` call and the `cmp w0, #7` guard are the
   likely place the op-selector values are defined.
2. `0x575390` — called at the head of nearly every SPI function with a format
   string; almost certainly a per-operation trace hook. Running the vendor
   kernel with its log level raised would name each op for free.
3. ~~`0x5776f0`~~ — see "A corrected inference" below: this is a hex-dump helper,
   not a mode path.
4. The mainline `airoha_snand_set_fifo_op()` and its `SPI_MAX_TRANSFER_SIZE`
   chunking, to see whether mainline already sends a bracketing word that the
   vendor's `OP = 1` corresponds to.

Item 4 is the cheapest and most likely to close it: if mainline's NAND path
already brackets its FIFO data with an op word, the encoding is documented in
code rather than only in the hardware.

### The trace strings name the whole core

Item 2 paid off without needing a board. `0x575390` is called with a literal
format string at the head of each SPI function, and those strings are the
vendor's own function names. Read out of `.rodata` at `0xbd1580`–`0xbd17c0`:

```
spi_controller_write_data_fifo : len=0x%x, data: 0x%x
 spi_controller_write_data_fifo: write data =0x%x
spi_controller_set_opfifo: set op_cmd =0x%x, op_len=0x%x
>>> Auto Mode and Manual Mode access in the same time
>>> Strange!! should not come here
SPI_CONTROLLER_Set_Configure: AUTO Mode
SPI_CONTROLLER_Set_Configure: Manual Mode
SPI_CONTROLLER_Set_Configure: DMA Mode
SPI_CONTROLLER_Write_One_Byte : data=0x%x
SPI_CONTROLLER_Write_NByte: len=0x%x
SPI CS1 device wait for flash operation done timeout
```

Three things fall out of this.

**`0x5755e0` is `SPI_CONTROLLER_Set_Opfifo(op_cmd, op_len)`.** The signature I
recovered from the instructions is confirmed by the vendor's own format string,
including the two field names.

**The controller has three modes — AUTO, Manual and DMA** — selected by the
argument to `0x5757d0`, with an explicit guard against interleaving AUTO and
Manual access. Mainline `spi-airoha-snfi.c` uses the AUTO path (it programs the
SNFI engine and ECC). `spi_device_write` selects **Manual Mode**, which is the
simpler PIO path this port actually needs, and which is a different code path
from the one mainline exercises.

That last point changes the conclusion of section 4 in an important way:
mainline does *not* already implement the mode the FMCS FPGA is driven in. The
register block is shared, but the operating mode is not, and the `OP = 1` /
`OP = 0` bracketing belongs to Manual Mode, not to the AUTO sequences mainline
uses for NAND. Comparing against `airoha_snand_set_fifo_op()` therefore cannot
settle it.

**A "CS1 device" exists on this controller, and it is the FPGA.** An earlier
revision read the timeout message as evidence that CS1 was the SPI-NOR flash.
That is superseded: resolving which functions reference the string shows it
belongs to `spi_device_write` and `spi_device_read`, the two functions the FMCS
driver calls. See "The chip select is CS1" below. CS0 is the boot SPI-NAND;
**CS1 is the FMCS FPGA.**

### A corrected inference

The first revision of this section named `0x5776f0` as the Manual-mode body and
made it the next step. **That was wrong, and reading it disproved it.** The
function is a hex-dump helper:

```
0x577730  mov  w1, w19          ; running offset
0x577734  mov  x0, <"%04x: ">   ; .rodata 0xbd1590
0x577738  bl   printk
0x57773c  ldrb w1, [x23, x19]   ; buffer byte
0x577740  mov  x0, <"%02x ">    ; .rodata 0xbce3a8
0x577748  bl   printk
```

— eight bytes to a line, an offset every line, a newline at the end. It is the
same helper the vendor userspace exposes as `PrintHex`. The branch into it from
`spi_data_rw` fires when `[0x113f03e0] == 1`, so that global is a **payload-dump
debug flag**, not a mode selector. Recorded here because the mis-identification
would otherwise cost a future round the same detour.

**Positively corroborated.** There is a wrapper at `0x5757a0` whose entire body
is the gate:

```
0x5757a0  adrp x2, #0x113f000
0x5757a4  ldrb w2, [x2, #0x3e0]   ; the global in question
0x5757a8  cmp  w2, #1
0x5757ac  b.eq #0x5757b4
0x5757b0  ret                     ; flag != 1 -> return, dump nothing
0x5757b4  ...  bl 0x5776f0        ; the hex-dump helper
```

A function whose only purpose is `if (flag == 1) hexdump(...)` is a debug
facility, so this is not just an inference from the callee's body: the caller
structure says the same thing. Same for `spi_type` at `0x575750`, which reads
`[ctrl]+8 → +0x114` to report the controller type, and which is also guarded by
the dump flag on another path.

That reading did produce one real result. Immediately after the dump helper,
`0x577770` is a register accessor:

```
0x577794  ldr  x0, [<ctrl>]        ; 0x113f03d8
0x577798  ldr  x0, [x0, #0x10]     ; <- a *second* register base
0x57779c  add  x0, x0, w19, uxtw   ; indexed
0x5777a0  ldr  w0, [x0]
```

So the driver holds **two** mapped bases: the one reached as `[[ctrl]] + 8` that
carries every FIFO register in section 1, and a second at `[ctrl+0x10]`
addressed by index. The `spi_device_write` status poll (`tst w1, #0xf`) reads
index 0 of the second one. That matches the two-entry `reg` property the stock
device tree gives its SPI node, and it means any replacement has to map both.
`spi_device_init`'s `0x1FA11550` is a candidate for one of them; which one is
now a specific question instead of a general one.

### Revised next steps

1. `0x5757d0` — the mode configuration, whose two branches seen so far log
   "Manual Mode" and "AUTO Mode". The third selector path and the meaning of the
   values written to `+0x14`/`+0x20` are where the op encoding should fall out.
2. Identify the second register base at `[ctrl+0x10]`, and map it to one of the
   ranges in the stock device tree's two-entry `reg` property. This also settles
   whether `0x1FA11550` in `spi_device_init` belongs to the first base or the
   second.
3. Identify the FPGA's chip select from the device tree's `spi-controller`
   phandle together with the CS1 evidence above.

### The OPFIFO op scan — result

Next-step 3 in an earlier revision was to tabulate every `op_cmd` passed to
`SPI_CONTROLLER_Set_Opfifo` across the image. `tools/opfifo_ops.py` does this:
it finds the **12 call sites** and recovers the first argument by walking the
preceding instructions and tracking the last literal assigned to each register.
The result:

```
op_cmd = 0x00   4 sites   0x575cb4, 0x575f40, 0x576058, 0x576098
op_cmd = 0x01   4 sites   0x575c84, 0x575f00, 0x575fd8, 0x576018
op_cmd = 0x08   1 site    0x575ad8
unresolved      3 sites   0x575a7c, 0x575b80, 0x575d90
```

Nine of the twelve sites resolve, three decline to, and there are no known false
positives left. The three unresolved sites are the ones whose argument is a
function parameter rather than a literal: `0x575a7c` is `Write_One_Byte`'s
`op_cmd` argument, and `0x575b80` / `0x575d90` compute `direction + 8` inside
`Write_NByte`.

**Read this with a caveat: the tracker is a heuristic.** It models `mov` and
discards a register when a call clobbers it or when an instruction names it as a
destination, but it does not do real dataflow. An earlier revision was looser
and reported `0x00` for `0x575a7c` and `0x01` for `0x575b80`, both wrong — the
first cost a round, chasing a contradiction that turned out to be the tool's.
Sites reported here should still be spot-checked by disassembling them before
being built on; the four `0x01`/`0x00` sites in `spi_device_write` and
`spi_device_read` have been, and the pair `0x575c84`/`0x575cb4` was verified
instruction by instruction.

**What that establishes:** `0x00` and `0x01` are a **pair of bracketing control
operations** wrapped around every data phase, in both the write and the read
path — four matched pairs across two functions, not a chip-select index and not
a bus width. `0x08` is a confirmed TX-single one-byte data op, verified by
reading `0x575aa0` where it appears as a literal followed by a FIFO push. Every
other data op is computed rather than literal, so the encoding is a small
control set plus a parameterised data range.

It does not yet name `0x00` and `0x01`, and it does not explain why the data
phase needs both a preceding and a following word. Those are what step 1 below
has to answer.

### A hypothesis worth testing for 0x00 and 0x01

The observed values, written as five-bit fields (`OP` is `GENMASK(13,9)`):

| Value | Binary | Site |
| --- | --- | --- |
| `0x00` | `00000` | trailing word, and `0x575a7c` |
| `0x01` | `00001` | leading word, and `0x575a7c`'s partner |
| `0x08` | `01000` | confirmed TX-single data op |
| `0x09` | `01001` | TX dual (`spi_data_rw` with direction 1) |
| `0x0A` | `01010` | TX quad (direction 2) |
| `0x0C` | `01100` | RX single (mode table) |
| `0x0E` | `01110` | RX dual |
| `0x0F` | `01111` | RX quad |

The data ops share **bit 3 set**. `0x00` and `0x01` clear it, so they are a
different class of command rather than a bus width — which is what the pairing
already suggests.

The testable part is the high bits. If `OP[4:3]` carried a chip-select index and
`OP[2:0]` a manual-mode command, then `0x08` would decode as CS1 plus command 0,
and the envelope `0x01` … `0x00` would read as *select one target, transfer,
select another*. Under that reading the FMCS FPGA sits on **chip select 1**.

That conflicts with the vendor timeout string `SPI CS1 device wait for flash
operation done timeout`, which names CS1 as a flash part. So the hypothesis is
probably wrong as stated — **but it is wrong in a useful way**: whichever of the
two readings hold, the chip-select index is in the same place, and
`vendor/ksymtab.txt` resolves both the timeout string's function and every
`SPI_CONTROLLER_*` helper by name. Checking which function contains that string
is a two-minute question and it settles the conflict directly.

### The chip select is CS1 — and an earlier reading of the CS1 string was wrong

An earlier revision of this document read the vendor timeout string

```
SPI CS1 device wait for flash operation done timeout
```

as evidence that CS1 is the SPI-NOR flash and that the FPGA is therefore on
some third chip select. **That was wrong.** Resolving which functions reference
the string (`tools/find_refs.py`) gives exactly two sites:

```
0x575d00   in spi_device_write+0x130
0x575f90   in spi_device_read+0x150
```

Both are the **timeout arm of the operation-done wait loop**, and both belong to
`spi_device_write` and `spi_device_read` — the two functions the FMCS driver
calls for every register access.

- `spi_device_write(buf, len)` takes no chip-select argument, so the device it
  addresses is fixed by construction.
- The vendor names that device **CS1** in its own error text.
- The FMCS driver uses these functions for the FPGA.

So **the FMCS FPGA is on chip select 1.** "flash" in the message is stale
wording inherited from the SPI-NOR path that shares the helper, not a
description of the device.

This closes next-step 4, and it removes the conflict recorded in the hypothesis
section below: there is no contradiction left to resolve, because CS1 is the
FPGA rather than a flash part.

**Still open:** whether the chip-select index is carried in the `OP` field of
`OPFIFO_WDATA` or set separately by `0x5757d0`. The `0x01` … `0x00` envelope
around each data phase is consistent with *select CS1 / transfer / deselect*,
but nothing yet rules out its being a start/stop pair for the controller's
manual mode. Step 2 of [`NEXT_STEPS.md`](NEXT_STEPS.md) settles it on the wire.

### CS1 is hardcoded, which narrows the envelope question

Scanning the whole image for strings that mention a chip select returns
**exactly one**:

```
0xbd1788  SPI CS1 device wait for flash operation done timeout
```

There is no CS0, CS2 or CS3 counterpart anywhere in the kernel. That is what a
hardcoded transport looks like, and it fits everything else:

* `spi_device_write(buf, len)` and `spi_device_read(tx, tx_len, rx, rx_len)`
  take **no chip-select argument**, so CS is fixed by construction — and the
  one CS the vendor ever names is CS1.
* The SPI-NAND and SPI-NOR go through their own drivers rather than through
  `spi_device_*`, which is why no other chip-select string exists.
* Therefore the `spi_device_*` layer exists **specifically to reach the CS1
  device**, and the only CS1 device in this system is the FMCS FPGA.

This closes the chip-select question: **CS1, hardcoded, no selector needed.**
The port does not have to implement a general chip-select mechanism — it has to
drive CS1, which is what `dts/h3c-fmcs.dtsi` already declares as `reg = <1>`.

It also **narrows the `OP = 1` / `OP = 0` question usefully**. Since the chip
select is fixed and never selected at runtime, the envelope cannot be a
chip-select select/deselect pair. That leaves it as either a start/stop for the
controller's manual mode, or a frame delimiter the FPGA expects. The hypothesis
in the previous section, which assumed `OP` might carry a chip-select index, is
retired — the index has nowhere to go.

The remaining question is now purely: does the envelope produce bus activity or
not? Step 2 of [`NEXT_STEPS.md`](NEXT_STEPS.md) answers it with one capture.

### The exported SPI surface is tiny — and it exists for this driver alone

Filtering `vendor/ksymtab.txt` for exported symbols whose name contains `SPI` in
any case returns the **complete** set:

```
0x56b120  ReadSPIByte
0x56b1a0  ReadSPIDWord
0x575440  spi_device_exit
0x575460  spi_device_init
0x575990  SPI_CONTROLLER_Enable_Auto_Mode
0x575bd0  spi_device_write
0x575e40  spi_device_read
0x575750  spi_type
0x100ad28 SPI_SEM
```

Eight functions plus a semaphore. Two consequences.

**`spi_device_write` and `spi_device_read` have zero in-kernel callers.**
`tools/callers.py` finds no `BL` to either anywhere in the image. They are
exported symbols with no internal user, which means their only consumers are
loadable modules — and the only module that imports them is `fmcs.ko`
(`REVERSE_ENGINEERING.md` section 3 records both in its undefined-symbol list).
Combined with CS1 being the one chip select the vendor ever names, that settles
it: **this transport exists to reach the FMCS FPGA and nothing else.**

**`ReadSPIByte` / `ReadSPIDWord` are not an alternative.** They look tempting as
a bit-bang path that would need no controller driver, but disassembling
`0x56b120` shows they are ops-table dispatchers:

```
ldr x3, [<global 0x109dac0>]
ldr x2, [x3, #0x190]
ldr x0, [x2, #0x60]
ldr x4, [x0, #0x18]        ; a registered function pointer
cbz x4, out                ; return 0 when nothing is registered
blr x4                     ; x4(ctrl, &val, 1, addr & 0x3ffffff)
```

They route through whatever read op was registered — the EcoNet `ecnt_ops`-style
registration pattern, whose unregister counterpart `ecnt_ops_unregister` is
also exported. There is no second transport hiding here.

The practical upshot is unchanged and now better supported: the port needs one
generic transfer path on the AN7581 SPI controller for CS1, and nothing else.

**Method note.** An earlier pass listed the SPI symbols by filtering on
`'spi' in name` combined with a lowercase `startswith('spi')` test. That missed
every uppercase `SPI_CONTROLLER_*` name. `vendor/ksymtab.txt` should be searched
case-insensitively before concluding a symbol is absent.

### The SPI core, resolved to named functions

Resolving the trace strings to their referencing sites (`tools/find_refs.py`)
gives the boundaries that the symbol table alone did not, because most of this
core is static:

| Address | Name | How it was resolved |
| --- | --- | --- |
| `0x575440` | `spi_device_exit` | exported |
| `0x575460` | `spi_device_init` | exported |
| `0x575500` | TX FIFO push loop | references `spi_controller_write_data_fifo`, `spi_device_init+0xbc` |
| `0x5755f0` | `SPI_CONTROLLER_Set_Opfifo` | references `spi_controller_set_opfifo`, `spi_device_init+0x1a0` |
| `0x575750` | `spi_type` | exported |
| `0x5757d0` | `SPI_CONTROLLER_Set_Configure` | references the AUTO/Manual/DMA strings |
| `0x575a50` | **`SPI_CONTROLLER_Write_One_Byte`** | references `SPI_CONTROLLER_Write_One_Byte`, `spi_type+0xd0` |
| `0x575b10` | **`SPI_CONTROLLER_Write_NByte`** | references `SPI_CONTROLLER_Write_NByte`, `spi_type+0x19c` |
| `0x575bd0` | `spi_device_write` | exported |
| `0x575e40` | `spi_device_read` | exported |
| `0x575990` | `SPI_CONTROLLER_Enable_Auto_Mode` | exported |
| `0x56b120` | `ReadSPIByte` / `0x56b1a0` `ReadSPIDWord` | exported, ops dispatchers |

This supersedes the earlier reading of `0x575b10` as an unnamed helper: it is
`SPI_CONTROLLER_Write_NByte`, the bulk transmit primitive.

### A contradiction in the op values — resolved, and it was the scan's fault

Mapping the recovered `op_cmd` values onto the newly named functions appeared to
produce a contradiction: `0x00` as a prefix in `Write_One_Byte`, `0x00` as a
suffix in `spi_device_write`. **Reading `0x575a50` shows it was an artefact of
the scan, not a property of the code.**

The function is:

```
0x575a50  and  w19, w0, #0xff      ; arg0 -> op_cmd, saved
0x575a60  ...  printk("SPI_CONTROLLER_Write_One_Byte : data=0x%x\n", data)
0x575a74  mov  w0, w19             ; op_cmd
0x575a78  mov  w1, #1
0x575a7c  bl   0x5755e0            ; Set_Opfifo(op_cmd, 1)
0x575a80  add  x0, sp, #0x2f       ; &data
0x575a84  mov  w1, #1
0x575a88  bl   0x575500            ; push 1 byte to the DFIFO
```

So the `op_cmd` at `0x575a7c` is **a function argument**, and the `0x00` the
tracker reported is a stale `mov w0, #0` from an unrelated branch — precisely the
false positive the tool's own docstring warns about, and which `opfifo_ops.py`
listed among its resolved values rather than its unresolved ones.

The immediately following function at `0x575aa0`, which prints the same message,
is the fixed-op variant:

```
0x575ad0  mov  w1, #1
0x575ad4  mov  w0, #8
0x575ad8  bl   0x5755e0            ; Set_Opfifo(8, 1)
0x575ae4  bl   0x575500            ; push 1 byte
```

**What this settles:**

* `0x00` never appears as a prefix anywhere. The envelope is `0x01` … `0x00`
  and only in `spi_device_write` and `spi_device_read`, which is what the
  hand-verified reading always said.
* `Set_Opfifo(op, 1)` followed by a one-byte FIFO push is a **one-byte data
  transfer**, with `op` selecting the transfer type — `0x08` here, matching
  `SNAND_FIFO_TX_BUSWIDTH_SINGLE`.
* The envelope's `Set_Opfifo(1, 1)` and `Set_Opfifo(0, 1)` are **not** followed
  by a FIFO push, so they are control operations, not data. That is consistent
  with, though not proof of, a begin/end pair.

The reading of `OPFIFO_OP` as a transfer-type selector plus a pair of non-data
control ops now stands on its own without the conflicting data point.

**A tool correction.** `opfifo_ops.py` should report `0x575a7c` as unresolved,
not as `0x00`. Sites whose argument is a register parameter rather than a
literal are indistinguishable from stale-literal sites with the current tracker;
the false-positive caveat in its docstring is the mitigation, and this round
shows the caveat is load-bearing rather than theoretical.

### The core is the NAND driver's own code, exported for modules

Caller counts settle what this layer *is*:

| Function | Callers | Where they are |
| --- | --- | --- |
| `SPI_CONTROLLER_Write_One_Byte` (`0x575a50`) | **27** | all in the SPI-NAND driver, `0x56d298`–`0x573f28` |
| the fixed-op one-byte helper (`0x575aa0`) | **61** | same region |
| `spi_device_write` (`0x575bd0`) | **0** | — |
| `spi_device_read` (`0x575e40`) | **0** | — |

So the SPI core at `0x575440`–`0x575f00` is **the SPI-NAND driver's own register
layer**, and `spi_device_write` / `spi_device_read` are thin exported wrappers
over it with no in-kernel users at all.

This is the strongest evidence yet for the porting conclusion in section 4: the
block belongs to the NAND driver, the FMCS FPGA borrows it, and any replacement
**must live inside `spi-airoha-snfi.c`** rather than beside it. A separate driver
sharing those registers is not a style choice to be debated — the NAND path
drives the same FIFO repeatedly during a page operation, and an interleaved write
from another driver would corrupt both.

**Attempted and unresolved:** sampling the 27 `Write_One_Byte` call sites for
their `op_cmd` argument resolved **none** of them. The NAND driver passes a
register rather than a literal at every site — consistent with a driver that
loops over bus widths and byte counts, and it means the op encoding cannot be
recovered from call sites on this side either. Same conclusion as the
`Set_Opfifo` scan, now for an independent reason.

### Caveat on `tools/find_refs.py` and `tools/callers.py`

The tool reports the **nearest exported symbol at or below** a reference, not
the true containing function. For a reference inside a static function it will
attribute it to the preceding export — for example, the Manual-Mode string at
`0x57588c` is reported as `spi_type+0x13c` although it actually lives in the
separate static mode-setup function at `0x5757d0`. The two findings that matter
here are unaffected, because `0x575d00` and `0x575f90` both fall inside
`spi_device_write` (0x575bd0, exported) and `spi_device_read` (0x575e40,
exported) respectively, verified by disassembling both.

Also unresolved and deliberately not guessed at: the retry and timeout semantics
of the `+0x00` status loop (`tst w1, #0xf`, bounded at 0x2710 iterations before
the vendor gives up and logs).

## 6. Status

What is verified: the register cross-reference in section 1 is reproducible from
two independent sources, and `tools/verify_spi_regs.py` re-derives every offset
from the vendor instruction stream — including the `ubfiz #9, #5` and `#0x1ff`
mask that prove the OPFIFO packing — and fails if the document drifts from the
binary.

What is not: the transmit framing in section 5, which is the last thing standing
between this map and a driver. It is a bounded reading task, not an unknown.
