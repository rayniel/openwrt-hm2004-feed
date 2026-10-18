# The vendor kernel, decompressed and symbolised

`mtd2_kernel.bin` is the stock H3C HM2004-DU kernel partition. It has no ELF
symbol table, which is why the port had been treating `fmcs.ko` as the only
source of truth about the hardware. It is no longer the only source: the image
can be decompressed in one step and its **9 692 exported symbols recovered by
name**, which turns the whole vendor kernel into something searchable.

Everything below is reproducible with `tools/extract_kernel.py`, which also
verifies its own output.

```
python tools/extract_kernel.py extract   # container -> vendor/vmlinux.bin
python tools/extract_kernel.py symbols   # -> vendor/ksymtab.txt
python tools/extract_kernel.py verify    # re-derives and checks both
```

---

## 1. Container layout

Measured, not guessed:

| Offset | Content |
| --- | --- |
| `0x0000` | H3C container header: magic `0xaa640001`, `0x12345678`, two GUIDs, two small counts (`0x400`, `0xa0e`) |
| `0x2100` | device tree blob |
| `0x4EE4` | **LZMA-alone stream** |

The `0x2100` device tree is the one used throughout
[`REVERSE_ENGINEERING.md`](REVERSE_ENGINEERING.md) for the FMCS wiring.

The LZMA stream header, read from the file:

```
props             0x5d          (lc=3, lp=0, pb=2; the standard value)
dict_size         0x00800000    (8 MiB)
uncompressed size 0x1054a00     (17 123 840 bytes)
```

The decompressed result begins `4d 5a 00 91 …` and carries `ARM\x64` at offset
`0x38` — an aarch64 `Image`, the EFI-stub form, not an ELF. Its own header
reports `text_offset = 0x88000` and `image_size = 0x115c000`.

Nothing else in the partition is compressed: a windowed entropy scan reads
≈7.997 bits/byte from `0x40000` to the end, which is why no gzip, xz, zstd, lz4,
bzip2 or lzo magic is present. LZMA-alone carries no magic of its own, which is
what made it easy to miss.

## 2. Recovering the symbol table

An `Image` has no symbol table, but it does keep `__ksymtab_strings` and
`__ksymtab`. On arm64, `CONFIG_HAVE_ARCH_PREL32_RELOCATIONS` is selected, so:

```c
struct kernel_symbol {
    int value_offset;      /* relative to &entry->value_offset */
    int name_offset;       /* relative to &entry->name_offset  */
    int namespace_offset;
};
```

Both offsets are relative to the address of the field they occupy, which makes
every entry **self-describing**. Scanning the image for 12-byte triples whose
name offset resolves to a valid identifier recovers the whole export list
without knowing where `__ksymtab` starts:

```
recovered 9692 exported symbols
```

The offsets are self-consistent, so the table can be used directly against file
offsets with no relocation step.

**Cross-check.** While reading the SPI core independently, a panic path at
`0x575d08` was found calling `0xc4a98` with a string loaded from `.rodata`. The
symbol table independently resolves `printk` to `0xc4a98`. Two unrelated
derivations agree, and `verify` additionally checks that every required symbol
starts with a well-formed aarch64 prologue.

## 3. What this unlocks

### 3.1 The vendor SPI implementation (R1)

`spi_device_init` (`0x575460`) is the function the FMCS driver calls to obtain
its register transport. It **maps physical address `0x1FA11550`**:

```
mov  x0, #0x1550
movk x0, #0x1fa1, lsl #16        ; x0 = 0x1FA11550
mov  x1, #4
bl   0x22830                     ; ioremap-by-physical-address helper
str  x0, [<.data 0x113f03e8>]
```

So the register transport is on the **hardware SPI controller**, confirming
what the device tree's `spi-controller = <0xb>` implies and ruling out the
possibility that the vendor bit-bangs the runtime port on the same GPIOs the
configuration port uses.

`0x1FA11550` is worth recording precisely: it sits at `spi2nfi@1fa11000 + 0x550`,
**outside** the 0x160-byte window the stock device tree declares for that node,
and outside the 4 KiB window `spi_controller@1fa10000` declares for itself. Any
new driver must map a window that actually covers it.

The controller is driven through `[[ctrl]] + 8`, a mapped base, at these
register offsets:

| Offset | Use, as observed |
| --- | --- |
| `+0x00` | status; `tst w1, #0xf` in a retry loop before each transfer |
| `+0x28` | chip-select and control write |
| `+0x2c` | polled until zero after a CS/control write |
| `+0x34` | polled until zero before writing FIFO data |
| `+0x38` | FIFO data write |
| `+0x3c` | polled until zero before reading FIFO data |
| `+0x40` | trigger, written `1` to start a byte |
| `+0x44` | FIFO data read |
| `+0xE4` | enables/disables the controller around a transfer |

The chip-select field is packed as `(cs << 9) | (length & 0x1ff)` into `+0x28`,
which is where the `ubfiz w19, w19, #9, #5` in `spi_device_write` comes from.

`spi_device_write(buf, len)` is `(x0 = buf, x1 = len)` and
`spi_device_read(x0 = buf, x1 = 1, x2 = rx, x3 = rxlen)`, matching how
[`REVERSE_ENGINEERING.md`](REVERSE_ENGINEERING.md) section 3 already read the
call sites. The transfer is a byte-at-a-time FIFO loop, guarded by a spinlock at
`0x113f03d8 + 0x20` — so the vendor core serialises both against itself and
against the SPI-NAND driver that shares the block.

### 3.2 What is still missing for R1

The register map above is enough to know *what* a SPIMEM-style transfer has to
poke, but not yet enough to write one safely: the retry and timeout semantics,
the exact meaning of the `+0xE4` enable, and the interaction with the SNFI/ECC
engine the NAND driver uses all still have to be recovered, and none of it can
be validated without the board.

The next step is therefore to read the rest of the vendor SPI core at
`0x575390`, `0x5755e0`, `0x5757d0` and `0x575b10` — all now addressable by name
from `vendor/ksymtab.txt` — and to compare them against
`drivers/spi/spi-airoha-snfi.c` in the 6.18 tree, which already drives the same
block for NAND.

### 3.3 Other things now addressable

The symbol table resolves everything the modules import, so each dependency the
port has to replace can now be read directly rather than inferred:

| Symbol | Address | Why it matters |
| --- | --- | --- |
| `spi_device_init` | `0x575460` | transport setup, R1 |
| `spi_device_read` | `0x575e40` | transport, R1 |
| `spi_device_write` | `0x575bd0` | transport, R1 |
| `spi_type` | `0x575750` | bus configuration |
| `spinand_lock` / `spinand_unlock` | `0x56d360` / `0x56dfc0` | the sharing discipline R1 must respect |

`GET_GPIO_DATA`, `g_gpio_base` and `__ECNT_HOOK` appear in
`__ksymtab_strings` but are not recovered by the current scan — their entries
fall outside the text range the scan accepts. Recovering them is a small,
bounded fix to `build_ksymtab` and is what R3 needs; it is listed here rather
than silently ignored.

## 4. Artefacts

| Path | Size | What it is |
| --- | --- | --- |
| `vendor/vmlinux.bin` | 17 123 840 B | the decompressed kernel `Image` |
| `vendor/ksymtab.txt` | 9 692 lines | `0xADDRESS name`, one exported symbol per line |

Both are regenerable from `D:\H3C\bak\mtd2_kernel.bin` with
`tools/extract_kernel.py`, which is the reason they are checked in as
convenience rather than as the source of truth.
