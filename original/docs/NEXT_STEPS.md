# Bench procedure: closing R1 on hardware

Everything in this tree that can be established without a board has been. R1 —
the FPGA register transport — is now gated on measurements rather than reading,
and this file is the procedure for taking them.

It is ordered so that each step either produces a result or tells you to stop.
Steps 1 and 2 need no kernel work at all.

---

## Background in one paragraph

The FMCS FPGA's register interface is on the SoC SPI controller at `0x1fa10000`,
on a chip select of its own. The vendor reaches it through
`SPI_CONTROLLER_Set_Opfifo` with a two-word control envelope around each data
phase. The register block is the same one mainline `spi-airoha-snfi.c` drives
for SPI-NAND, but **not in the same mode**: mainline uses AUTO mode with the SNFI
engine, while the FPGA is driven in Manual Mode, which mainline never exercises.
That gap is why a patch cannot simply be lifted from the existing driver.

## Step 1 — confirm the FPGA is where the stock device tree says

Boot the vendor firmware (or any image that loads `fmcs.ko`) and, as root:

```sh
# Which chip selects does the controller see devices on?
cat /proc/interrupts | grep -i fmcs          # moltdbg's own hint
dmesg | grep -iE 'spi|fmcs|fpga' | head -50
cat /sys/bus/spi/devices/*/modalias
ls -l /sys/class/spi_master/ 2>/dev/null
```

**Looking for:** the bus number and confirmation that the FPGA answers on chip
select 1. **CS1 is already established from the binary** — see "The chip select
is CS1" and "CS1 is hardcoded" in [`SPI_CONTROLLER.md`](SPI_CONTROLLER.md): the
one chip-select string in the whole kernel belongs to `spi_device_write` and
`spi_device_read`, the two functions `fmcs.ko` calls, and
`spi_device_write(buf, len)` takes no chip-select argument at all. So this step
is a confirmation, not a discovery. An earlier revision of this file claimed CS1
was the NOR flash; that reading was wrong and has been retracted.

If the FPGA turns out **not** to be on `0x1fa10000`, stop — the rest of this
procedure does not apply.

## Step 2 — read one register with the vendor tool, and watch the bus

This is the single most informative measurement available, and it needs no new
code.

On the vendor firmware:

```sh
# a known-safe read: the FPGA interrupt status word the driver itself polls
miniolt read fpga 0x0000
```

While it runs, capture the SPI lines with a logic analyser or scope on SCK,
MOSI, MISO and CS. **One read should produce this sequence**, and it is the
reference waveform for everything that follows:

```
CS      ____/‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾\____
MOSI    A0 <addr_be32>           50 <don't care>
MISO    .............................  <4 bytes, big-endian result>
```

Two things fall out of the capture that no amount of reading settled:

* **what the `OP = 1` and `OP = 0` envelope looks like on the wire.** The
  OPFIFO command word is written to a register, not shifted out, so it may
  produce no bus activity at all — in which case it is a controller-internal
  start/stop and can be copied literally. If it *does* clock bytes, the capture
  shows which.
* **the real chip-select index**, from which line asserts.

If you have no analyser, `miniolt read fpga 0x0000` returning a plausible,
stable value is itself partial evidence that the protocol in
[`REVERSE_ENGINEERING.md`](REVERSE_ENGINEERING.md) section 3 is right.

## Step 3 — name `OP = 1` from the vendor kernel's own logs

Cheaper than a capture if you have console access to the vendor kernel: the SPI
core calls a trace hook (`0x575390`) with a format string at the head of every
operation. Raise the vendor module's log level and re-run step 2. The output
names each phase directly.

```sh
# the level the vendor exposes; see docs/MOLT_API.md for the enumeration
moltdbg fpga ...        # or
echo 3 > /sys/module/fmcs/parameters/...   # check what the module exposes
```

**Looking for:** lines matching
`spi_controller_set_opfifo: set op_cmd =0x.., op_len=0x..`. The `op_cmd` values
emitted during one register read are the answer to the only remaining question
in section 5.

## Step 4 — only then, write the transport

With steps 1–3 done, the patch to `spi-airoha-snfi.c` is mechanical:

1. add `set_cs()` and a `transfer_one()` in Manual Mode;
2. issue `SPI_CONTROLLER_Set_Opfifo` per phase using the recovered register map
   (`+0x28` with `OP` at bits 13:9 and `LEN` at bits 8:0, `+0x2C`/`+0x34` busy
   polls, `+0x38`/`+0x44` data);
3. bracket as the capture shows;
4. make the FMCS node a SPI child with `reg = <cs>`.

`docs/SPI_CONTROLLER.md` has the register table and the open questions;
`dts/h3c-fmcs.dtsi` has both device-tree wirings ready.

## Step 5 — verify against the port, not against the vendor

Once the transport exists, the port's own checks become the acceptance test.
On the target:

```sh
miniolt read fpga 0x0000      # should print the same value the vendor tool did
cat /proc/fpgaLoad            # hold times, and whether the bitstream loaded
cat /proc/interrupts | grep fmcs
```

If step 2 produced a captured reference waveform, compare the port's waveform
against it byte for byte. That is a stronger test than any value comparison,
because it catches a framing error that happens to read back correctly.

---

## If you cannot get to a board

The alternative is to finish the reading, which needs no hardware but does need
patience. The three steps are in `docs/SPI_CONTROLLER.md` section 5, and
`vendor/ksymtab.txt` resolves every function involved by name, so nothing has to
be found by scanning.

---

## What is already settled, so you do not re-check it

* The ioctl ABI is exact and cross-checked against two shipped binaries.
* The SPI wire protocol — opcodes, frame lengths, byte order, delays — is
  recovered and the driver is checked against it on every run of
  `tools/run_checks.py`.
* The bitstream needs no parsing: feed `FTTR_TOP.sbit` byte for byte, MSB first.
* The FPGA is a Pango Logos **PGL50H-6-FBG484**.
* The M-OLT service API and its JSON data model are fully recovered, so the
  LuCI application's second stage is specified even though it is not wired.
* **The chip select is 1**, hardcoded — there is exactly one chip-select string
  in the kernel and it belongs to the two functions `fmcs.ko` calls.
* **The SPI core belongs to the SPI-NAND driver.** `SPI_CONTROLLER_Write_One_Byte`
  has 27 callers, all inside it; `spi_device_write` and `spi_device_read` have
  zero in-kernel callers and exist only for modules. Any replacement must live
  inside `spi-airoha-snfi.c`, not beside it — the NAND path drives the same FIFO
  repeatedly and an interleaved writer would corrupt both.
* **The SPI core is resolved to named functions** (`Set_Opfifo`, `Set_Configure`,
  `Write_One_Byte`, `Write_NByte`, `spi_device_write/read`, `spi_type`), with
  addresses, in [`SPI_CONTROLLER.md`](SPI_CONTROLLER.md).

## Two static routes to the op encoding, both dead

Worth knowing before trying a third:

1. **Scanning `Set_Opfifo` call sites** for the `op_cmd` argument — 9 of 12
   resolve, but the ones that matter are computed (`direction + 8`) or are
   parameters of `Write_One_Byte`.
2. **Sampling `Write_One_Byte`'s 27 call sites** — resolves *none*; the NAND
   driver passes a register at every site.

The encoding is not a literal anywhere it matters, which is why step 2 or 3
below needs the board or the vendor's own logs.
