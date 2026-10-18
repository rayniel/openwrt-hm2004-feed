# `FTTR_TOP.sbit` — structural analysis

Target: `D:\H3C\bak\mtd3_rootfs\lib\firmware\FTTR_TOP.sbit`
Size: 2,087,000 bytes = `0x1FD858` = 16,696,000 bits (divisible by 8, not by 16)
Generator string (from the file itself): **Pango Design Suite / Fabric Compiler 2022.2<117120>**, project `FTTR_TOP`, device `Logos-PGL50H--6-FBG484`, built 11/04/2024 20:41:18.

Companion tool: `sbit_analyze.py` (same directory). Every number below is reproducible with
`python sbit_analyze.py <file> --section all`.

---

## 0. Bottom line

**A loader must not strip, skip, reorder, or transform anything. It can feed the file byte-for-byte, MSB-first.**

Reasons, in order of strength:

1. The shipping kernel module `fpga_load.ko` already does exactly that (given as established; independently corroborated below), and the product works.
2. The first 0x8D bytes are a plain metadata block, and the last byte of the file is the last byte of a repeating filler word — there is no trailer, length, or alignment requirement that a caller could honour.
3. No transformation is applied to the file: the ASCII strings in the header are intact readable ASCII, which rules out a global bit-reversal or nibble-swap encoding (§5c).
4. The header contains **no** length field, checksum, or device-ID field that a loader would have to interpret.

There **is** a header, it is 141 bytes, and it is *inside* the bit stream. It is tolerant only because the FPGA's configuration port ignores leading bytes it has no framing for — see §7 "Uncertainties".

---

## 1. Byte layout

| Offset | Size | Content |
|---|---|---|
| `0x000000`–`0x00008C` | 141 | Header block: fixed preamble + vendor string + 6 TLV ASCII records (§2) |
| `0x00008D`–`0x000660` | 1,492 | **100 % `0x00`** — padding/idle |
| `0x000661`–`0x000663` | 3 | `20 0b 5c` — unexplained |
| `0x000664`–`0x0007F3` | 400 | **all `0xFF`** |
| `0x0007F4`–`0x0007FB` | 8 | `00 00 00 aa 08 10 00 20` — unexplained |
| `0x0007FC`–`0x000823` | 40 | **all `0xFF`** |
| `0x000824`–`0x0008BF` | 156 | 32-bit command/operand block (§4) |
| `0x0008C0`–`0x000937` | 120 | `a0 00 00 00` fill ×30 |
| `0x000938`–`0x00094F` | 24 | 32-bit command/operand block |
| `0x000950`–`0x001AA83B` | ~1,653,000 | fabric bit-stream, 4–16 % ones density (§6) |
| `0x001AA840`–`0x001FD63F` | 339,456 | **100 % `0x00`** (16.27 % of the file) |
| `0x001FD640`–`0x001FD6C7` | 136 | 20 fill words + 7 command/operand pairs (trailer, §4.3) |
| `0x001FD6C8`–`0x001FD857` | 396 | `a0 00 00 00` fill ×99, running to EOF |

`0x000661` is the **first non-zero byte after the header**; `0x1FD854` is the last non-zero byte (the `a0` of the final fill word), leaving exactly 3 trailing `0x00` bytes.

---

## 2. The header (`0x000000`–`0x00008C`)

```
00000000  00 09 0f f0 0f f0 0f f0 0f f0 00 50 41 4e 47 4f  |...........PANGO|
00000010  20 4d 49 43 52 4f 53 59 53 54 45 4d 53 2c 20 49  | MICROSYSTEMS, I|
00000020  4e 43 2e 00 01 61 00 09 46 54 54 52 5f 54 4f 50  |NC...a..FTTR_TOP|
00000030  00 62 00 17 4c 6f 67 6f 73 2d 50 47 4c 35 30 48  |.b..Logos-PGL50H|
00000040  2d 2d 36 2d 46 42 47 34 38 34 00 63 00 0b 31 31  |--6-FBG484.c..11|
00000050  2f 30 34 2f 32 30 32 34 00 64 00 09 32 30 3a 34  |/04/2024.d..20:4|
00000060  31 3a 31 38 00 65 00 10 46 61 62 72 69 63 20 43  |1:18.e..Fabric C|
00000070  6f 6d 70 69 6c 65 72 00 66 00 0f 32 30 32 32 2e  |ompiler.f..2022.|
00000080  32 3c 31 31 37 31 32 30 3e 00 67 68 69 00 00 00  |2<117120>.ghi...|
```

### 2.1 Where the ASCII string ends

`"PANGO MICROSYSTEMS, INC."` occupies `0x0B`–`0x22` (24 bytes) and is NUL-terminated at `0x23`.
It is preceded by an 11-byte fixed preamble and followed by a one-byte gap, then a TLV record list.

### 2.2 Record format — `tag:u8`, `len:u16 BE`, `value[len]` (len **includes** the terminating NUL)

Verified by 6 consecutive records that chain exactly end-to-end with no slack:

| Record start | tag | len | value | next record | check |
|---|---|---|---|---|---|
| `0x025` | `0x61` | 9 | `"FTTR_TOP\0"` | `0x031` | 1+2+9 = 12, `0x25+12 = 0x31` ✓ |
| `0x031` | `0x62` | 23 | `"Logos-PGL50H--6-FBG484\0"` | `0x04B` | 1+2+23 = 26, `0x31+26 = 0x4B` ✓ |
| `0x04B` | `0x63` | 11 | `"11/04/2024\0"` | `0x059` | 1+2+11 = 14, `0x4B+14 = 0x59` ✓ |
| `0x059` | `0x64` | 9 | `"20:41:18\0"` | `0x065` | 1+2+9 = 12, `0x59+12 = 0x65` ✓ |
| `0x065` | `0x65` | 16 | `"Fabric Compiler\0"` | `0x078` | 1+2+16 = 19, `0x65+19 = 0x78` ✓ |
| `0x078` | `0x66` | 15 | `"2022.2<117120>\0"` | `0x08A` | 1+2+15 = 18, `0x78+18 = 0x8A` ✓ |

The tags are the consecutive ASCII letters `'a'`–`'f'` (`0x61`–`0x66`).

### 2.3 What is *not* in the header

There is **no** length field, no bit count, no checksum, no CRC, and no numeric device ID. The only
machine-readable content is the six ASCII strings. A loader therefore has nothing it could validate
or act on.

### 2.4 Header items I could **not** explain (stated as unknown, not guessed)

* `0x000000`–`0x00000A`: `00 09 0f f0 0f f0 0f f0 0f f0 00`. As 16-bit big-endian words this is `0x0009` followed by `0x0FF0` four times. The 8-byte run `0f f0 0f f0 0f f0 0f f0` occurs **exactly once in the entire 2,087,000-byte file** (at `0x02`); `0f f0` occurs only 64 times overall, median spacing 13,785 bytes. So this is a unique fixed magic/preamble, not a recurring sync word. **Its meaning is not determinable from a single sample — unverified.**
* `0x000024`: a lone `0x01` between the vendor-string NUL and the first TLV tag.
* `0x00008A`–`0x00008C`: `67 68 69`. `0x67` would be the next tag (`'g'`), but the following two bytes read as a length of `0x6869` = 26,729 — larger than every structural boundary in the file (`0x8D + 26729 = 0x68F6`, which is inside dense fabric data and is not a record boundary). A parse as `tag='g'`, `len=0x68`, value at `0x8C` also fails (value would start `69 00 00 …`, not ASCII). **These 3 bytes are unexplained.**

**Practical consequence:** whether the header block is 0x8A, 0x8D, or 0x90 bytes long is *immaterial*,
because `0x8D`–`0x660` is 1,492 bytes of pure `0x00` and nothing needs to be stripped (§0).

---

## 3. Verification of the driver premise (corroborating, not re-derived)

The brief gives the bit-banging behaviour as established. What I independently checked on
`D:\H3C\bak\mtd3_rootfs\lib\modules\fpga_load.ko` (12,024 bytes):

* ELF64, `e_machine = 183` (AArch64); `vermagic=5.4.55 SMP mod_unload aarch64`.
* Contains the literal string `/lib/firmware/FTTR_TOP.sbit`.
* `.text` (0x398) and `.text.unlikely` (0x464) relocate against `GET_GPIO_DATA`, `g_gpio_base`
  and `__ndelay`, i.e. a GPIO-polling loop with hand-timed delays — consistent with a
  bit-banged configuration port.

I did **not** re-derive the MSB-first bit order from the disassembly; that remains per the brief.

---

## 4. Payload word framing

### 4.1 A 32-bit big-endian word stream, aligned at offset ≡ 0 (mod 4)

The filler word `a0 00 00 00` occurs at 4-byte-aligned offsets far more often than chance:

| `offset % 4` | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| occurrences of `a0 00 00 00` | **3,446** | 236 | 263 | 231 |

Peak/floor ratio **14.9×**. The same word occurs 4,176 times in total, so the bulk of them are
4-aligned. Controls: the byte-reversed form `00 00 00 a0` occurs 4,107 times — the same runs read
one byte later, not a second alignment; the bit-reversed form `05 00 00 00` occurs 1,323 times and
the nibble-swapped form `0a 00 00 00` 723 times, both as unstructured background.

### 4.2 Command words — 8-byte units `aX ?? 00 0[01]` + 32-bit operand

Across the file there are 886 words matching `(b0 & 0xF0) == 0xA0 and b2 == 0x00 and b3 in {0,1}`
(excluding the `a0 00 00 00` filler). Their distribution over the two 4-aligned phases of an 8-byte
granule:

| | `offset % 8 == 0` | `offset % 8 == 4` |
|---|---|---|
| command words | **628** | 258 |
| 50:50 expectation | 443 | 443 |

70.9 % : 29.1 %, i.e. **≈ 12σ** from an even split. Control: shuffling all 2,087,000 bytes with a
fixed seed yields 876 : 862 (50.4 % : 49.6 %) — no alignment. (The *absolute* rate of such words is
not itself anomalous: 886 observed versus 1,738 under the shuffled control, i.e. the sparse payload
contains fewer of them than random data would. **Only the alignment is the signal.**)

Raw dump of the whole block at `0x000824`–`0x0008BF`:

```
00000824  01 33 2d 94 ae c0 00 01 03 60 00 00 ab 00 00 01  |.....3-......`..|
00000830  00 00 00 0b a0 00 00 00 a0 00 00 00 a0 00 00 00  |................|
00000840  a0 00 00 00 a0 00 00 00 a0 00 00 00 a0 00 00 00  |................|
00000850  a0 00 00 00 a0 00 00 00 a0 00 00 00 a0 00 00 00  |................|
00000860  ab c0 00 01 00 00 00 00 ac 00 00 01 00 00 00 00  |................|
00000870  a8 80 00 01 00 00 00 00 a8 80 00 01 00 00 00 01  |................|
00000880  a8 40 00 01 00 52 18 99 ac 40 00 01 3f ff ff ff  |.@...R...@..?...|
00000890  ad c0 00 01 ff ff ff ff a8 c0 00 01 00 00 00 00  |................|
000008a0  ae 40 00 01 00 0d a0 80 ae 80 00 01 00 00 00 00  |.@..............|
000008b0  ae 00 00 01 00 00 01 00 a8 80 00 01 00 00 00 02  |................|
```

Each command occupies 8 bytes and every one starts at a multiple of 8 (`0x828, 0x830, 0x860, 0x868,
0x870, 0x878, 0x880, 0x888, 0x890, 0x898, 0x8A0, 0x8A8, 0x8B0, 0x8B8`). Visible above:
`a0 00 00 00` is a **filler/NOP word**, and the operands take register-like values
(`0x03600000`, `11`, `0x00521899`, `0x3FFFFFFF`, `0xFFFFFFFF`, `0x000DA080`, `0x00000100`, `2`).

One opcode recurs with what look like 32-bit addresses whose top byte is `0x48`:
`a9 40 00 00` paired with `48 00 04 40` (`0x948`), `48 01 4B 80` (`0x1AA838`), `48 00 00 88`
(`0x1F40`), `48 00 57 EC` (`0x21C8`). **Reading these as addresses is an inference, not a verified fact.**

### 4.3 Trailer block at `0x001FD690`–`0x001FD6C7`

```
001fd690  a8 00 00 01 df b2 a2 50 ad c0 00 01 ff ff ff ff
001fd6a0  a9 00 00 01 00 00 00 10 a8 80 00 01 00 00 00 09
001fd6b0  a8 80 00 01 00 00 00 07 a8 00 00 01 08 49 9d 06
001fd6c0  a8 80 00 01 00 00 00 0b a0 00 00 00 a0 00 00 00
```

Seven command/operand pairs with operands `0xDFB2A250`, `0xFFFFFFFF`, `0x00000010`, `0x00000009`,
`0x00000007`, `0x08499D06`, `0x0000000B`, followed by filler to EOF. `0xDFB2A250` and `0x08499D06`
have the shape of checksums/CRCs and the sequence of small counts and an all-ones word is the shape
of an end-of-configuration descriptor. **This is a plausible reading, not a verified one.**

---

## 5. Hypothesis tests (the four options in the brief)

### (a) Plain bytes, MSB-first — **SUPPORTED**

* The vendor and driver premise (whole file, verbatim, MSB-first).
* The payload is a coherent 4/8-byte word stream (§4) with no evidence of any per-byte transform.
* Section 5(c) below shows the two candidate transforms cannot have been applied at all.

### (b) Each byte = 1 data bit + padding — **FALSIFIED**

* All 256 byte values occur (58.39 % are `0x00`; `0xFF` occurs 6,345 times, i.e. 6,345 whole bytes
  of eight set bits). A 1-bit-per-byte encoding restricts bytes to a 2-element set; a 1-bit-per-nibble
  encoding to 4.
* 49.7 % of payload bytes are non-zero.
* Popcount distribution is wildly non-i.i.d. in the *opposite* direction: against an i.i.d. model with
  the same mean bit density, popcount 4 is 5.6× over-represented, 5 is 19.8×, 6 is 192×, 7 is 5,610×,
  8 is 262,000×. That is a run-structured bit stream, not a bit-plus-padding code.

### (c) Nibble-swapped / bit-reversed — **FALSIFIED (decisively, for the whole file)**

A global transform would also apply to the header, which contains intact printable ASCII:
`"PANGO MICROSYSTEMS, INC."`, `"Logos-PGL50H--6-FBG484"`, `"11/04/2024"`, `"20:41:18"`,
`"Fabric Compiler"`, `"2022.2<117120>"`.
`'P'` = `0x50` → bit-reversed `0x0A` (not printable) and nibble-swapped `0x05` (not printable).
Since the strings are readable in the file as stored, **no global bit-reversal and no global
nibble-swap was applied.**

Weaker corroboration in the payload: the fill word `a0 00 00 00` is 14.9× phase-enriched, whereas
its bit-reversed (`05 00 00 00`, 1,323×) and nibble-swapped (`0a 00 00 00`, 723×) images show no
phase structure. This does not by itself exclude a payload-only transform, but the header argument
already excludes a file-level transform, and there is no independent evidence for a payload-only one.

### (d) `0x0F` nibbles are sync words — **FALSIFIED as a framing device**

* `0f f0` occurs only **64 times** in 2,087,000 bytes; median spacing 13,785 bytes, max 148,764.
* `f0 0f` occurs **3 times**, all within the first 8 bytes (`0x03`, `0x05`, `0x07`).
* The 8-byte run `0f f0 0f f0 0f f0 0f f0` occurs **exactly once**, at `0x02`.
* There is no fixed record size implied by any of them.

The `0x00 09 0f f0 0f f0 0f f0 0f f0 00` prefix is therefore a **unique fixed file magic**, not a
recurring frame marker. What it *means* is unverified.

---

## 6. Marker and macro structure

### 6.1 Recurring patterns

| Pattern | Count | First offsets | Spacing (min/med/max) |
|---|---|---|---|
| `0f f0` | 64 | `0x2 0x4 0x6 0x8 0x7b2b …` | 2 / 13,785 / 148,764 |
| `0f f0 ×4` (8 B) | 1 | `0x2` | — |
| `00 09` | 3,234 | `0x0 0x26 0x5a 0xfbb …` | 2 / 268 / 342,381 |
| `a0 00 00 00` | 4,176 | `0x838 0x83c 0x840 …` | 4 / 4 / 339,484 |
| `ff ff ff ff` | 436 | `0x664 0x665 …` | 1 / 1 / 2,084,360 |

The `ff ff ff ff` count is explained entirely by the two long `0xFF` runs (397 overlapping windows in
the 400-byte run, 37 in the 40-byte run, plus 2 isolated 4-byte runs at `0x894` and `0x1FD69C`).
All four `0xFF` runs start at offsets ≡ 0 (mod 4). With only four samples this is weak evidence
(p ≈ 1/64 by chance); the strong alignment evidence is the fill word in §4.1.

### 6.2 Long runs of a single byte value

`0x00` runs ≥ 64 bytes: 1,300 of them. Largest:

| Offset range | Length | Note |
|---|---|---|
| `0x1AA840`–`0x1FD63F` | 339,456 | 16.27 % of the file |
| `0x00008D`–`0x000660` | 1,492 | the post-header gap |
| `0x1765E1`–`0x176777` | 407 | |
| `0x11C851`–`0x11C99F` | 335 | |
| `0x00192F`–`0x001A4F` | 289 | |
| `0x08F46F`–`0x08F58F` | 289 | |

`0xFF` runs ≥ 4 bytes: exactly **4** — `0x664` (400 B), `0x7FC` (40 B), `0x894` (4 B), `0x1FD69C` (4 B).

Zero-run length histogram (whole file): 153,019 runs of 1, 61,969 of 2, 34,080 of 3, … 2,874 runs of
21 or more. The heavy 1-byte spike at length 1 versus length 2 is not geometric (ratio 2.47), so the
zeros are not a homogeneous i.i.d. run process — the file mixes near-empty regions with a sparse
but structured bit stream.

### 6.3 Macro map (per 64 KiB)

```
                range     size   zeros%   0xff%  bitdens%  distinct
  0x000000-0x00ffff    65536    54.01   0.844    11.421       256
  0x010000-0x01ffff    65536    52.08   0.183    11.162       256
  0x020000-0x02ffff    65536    57.81   0.223    10.034       256
  0x030000-0x03ffff    65536    80.80   0.221     4.944       253
  0x040000-0x04ffff    65536    55.03   0.380    11.535       256
  0x050000-0x05ffff    65536    53.00   0.217    11.538       256
  0x060000-0x06ffff    65536    39.62   0.644    15.732       256
  0x070000-0x07ffff    65536    51.93   0.658    11.963       254
  0x080000-0x08ffff    65536    61.57   0.359     9.284       254
  0x090000-0x09ffff    65536    59.66   0.143     8.910       254
  0x0a0000-0x0affff    65536    48.97   0.391    11.927       255
  0x0b0000-0x0bffff    65536    44.97   0.499    13.638       256
  0x0c0000-0x0cffff    65536    59.65   0.281    10.181       256
  0x0d0000-0x0dffff    65536    35.55   0.421    16.104       256
  0x0e0000-0x0effff    65536    35.88   0.354    16.134       256
  0x0f0000-0x0fffff    65536    37.55   0.266    15.090       256
  0x100000-0x10ffff    65536    47.41   0.203    12.149       255
  0x110000-0x11ffff    65536    64.52   0.075     7.906       255
  0x120000-0x12ffff    65536    66.73   0.272     7.459       253
  0x130000-0x13ffff    65536    49.05   0.253    12.422       254
  0x140000-0x14ffff    65536    43.12   0.372    14.432       256
  0x150000-0x15ffff    65536    37.72   0.539    15.972       256
  0x160000-0x16ffff    65536    37.25   0.540    16.003       256
  0x170000-0x17ffff    65536    38.19   0.549    15.881       256
  0x180000-0x18ffff    65536    38.03   0.420    15.524       255
  0x190000-0x19ffff    65536    47.15   0.357    12.447       255
  0x1a0000-0x1affff    65536    77.84   0.014     4.596       219
  0x1b0000-0x1bffff    65536   100.00   0.000     0.000         1
  0x1c0000-0x1cffff    65536   100.00   0.000     0.000         1
  0x1d0000-0x1dffff    65536   100.00   0.000     0.000         1
  0x1e0000-0x1effff    65536   100.00   0.000     0.000         1
  0x1f0000-0x1fd857    55384    99.72   0.007     0.078        21
```

Whole-file statistics: 58.388 % zeros, 0.304 % `0xFF`, **bit density 10.19 %**; payload region
(`0x661`–`0x1AA840`) bit density **12.18 %**. Byte entropy 3.458 bits/byte; all 256 values present.

### 6.4 Reproducible period-9 byte structure (observation, cause unverified)

Byte autocorrelation shows a local maximum at lag 9 in three disjoint 256 KiB windows:

| window | lag 8 | **lag 9** | lag 10 | lag 18 | lag 27 |
|---|---|---|---|---|---|
| `0x000000`–`0x040000` | +0.280 | **+0.340** | +0.250 | +0.279 | +0.247 |
| `0x080000`–`0x0C0000` | +0.198 | **+0.264** | +0.172 | +0.234 | +0.202 |
| `0x100000`–`0x140000` | +0.203 | **+0.276** | +0.174 | +0.240 | +0.205 |

There is a real period of 9 bytes (72 bits) in the payload's byte sequence. **What produces it is not
determined by this analysis.** It is not a sync marker (§5d) and it does not align with the 4/8-byte
word framing (§4).

---

## 7. Size plausibility

* File: **16,696,000 bits ≈ 16.7 Mbit**; payload-only (`0x661` onward) 16,682,936 bits.
* The device named in the file, `Logos-PGL50H--6-FBG484`, is a real part: Pango's own Logos selection
  guide lists **PGL50H, 42,800 LUTs / 51,360 logic cells, FBG484 package, 4× HSST, 1× PCIe Gen2×4**
  ([pangomicro.com Logos Family](https://www.pangomicro.com/en/product/logos_family/1797.html), fetched).
* Arithmetic, not a device spec: 16,696,000 bits ÷ 42,800 LUTs ≈ **390 bit/LUT**; ÷ 51,360 logic
  cells ≈ **325 bit/cell**. That ratio sits in the normal band for LUT-based FPGAs of this class, so
  the file size is **consistent with** a ~50 k-LUT device and is not obviously a truncation or a
  concatenation of two images.
* The file size 2,087,000 = 2³ · 5³ · 2087 (2087 is prime) is not a round binary number (`0x1FD858`), which is what one
  expects from "header + content + padding to whatever the tool produced", not from a padded
  to-device-size blob.

**Unverified:** I could **not** find a published Pango figure for the PGL50H configuration bit count.
Pango's *Logos Family FPGAs Configuration User Guide (UG020005, V2.3)* is listed on their site but the
download link is JavaScript-only and my attempts to fetch the PDF by guessed URL returned HTTP 404.
Treat "consistent with PGL50H" as a size-plausibility argument, **not** as a matched device ID.

---

## 8. Web research

### 8.1 What the tooling landscape actually contains

* **openFPGALoader has no Pango backend.** `https://api.github.com/repos/trabucayre/openFPGALoader/contents/src`
  (fetched) lists backends for Altera, Anlogic, Cologne Chip, Efinix, Gowin, iCE40 and Xilinx —
  there is no `pango*.cpp`. Direct fetch of `https://raw.githubusercontent.com/trabucayre/openFPGALoader/master/src/pango.cpp`
  returned **HTTP 404**.
* **No prjtrellis/prjoxide-style Pango bitstream project exists on GitHub.**
  `https://api.github.com/search/repositories?q=pango+fpga+bitstream` returned `total_count: 0`.
  A broader query for Pango-related repositories returned 8 results, all of them *design* projects
  (Verilog/SystemVerilog competition and dev-board projects) plus `fxzjshm/Pango_JTAG`, whose README
  (fetched) describes only **JTAG upload** for a `PG2T390H` device and makes no claim about the
  `.sbit` container format.
* **Pango's own site** ([pangomicro.com](https://www.pangomicro.com/en/product/logos_family/1797.html),
  fetched) confirms the Logos family and the PGL50H/FBG484 part, and lists device-selection and
  user-guide documents (Data Sheet DS02001; Configuration User Guide UG020005 V2.3) — but the
  documents themselves are behind JavaScript links I could not resolve.

### 8.2 What matches my structural findings

Nothing in the public sources *contradicts* the analysis, but **no public source confirms any of the
byte-level findings in §2–§6.** In particular I found no reference anywhere describing:

* the `00 09 0f f0 0f f0 0f f0 0f f0 00` preamble,
* the `"PANGO MICROSYSTEMS, INC."` + `tag/len/value` header record list,
* the `aX ?? 00 0[01]` command-word + operand structure, or
* the `a0 00 00 00` filler word.

### 8.3 Explicitly **not** verified

* The difference between PDS output types `.sbit`, `.bit` and `.fs` — **not verified**. I found no
  documentation for any of them.
* Whether the `.sbit` container format is documented by Pango at all — **not verified**.
* Whether the 8-byte `aX …`/operand units are executed as instructions by the FPGA rather than merely
  being recognisable byte patterns — **not verified** (no reverse-engineered instruction set exists
  publicly).
* The trailer operands as checksums — **not verified**.

### 8.4 Research limitation (disclosed)

The `web_search` tool was unavailable for this session (`HTTP 402 Insufficient Balance` from the
configured search endpoint). Only direct URL fetches worked. Bing-via-fetch returned unrelated or
filtered results for the format queries, and DuckDuckGo/grep.app/jina reader were blocked. The web
coverage in this section is therefore **narrow and negative** (evidence of absence in the projects I
could enumerate) rather than a thorough literature search.

---

## 9. Unverified claims — consolidated

| Claim | Status |
|---|---|
| Meaning of the 11-byte preamble `00 09 0f f0 0f f0 0f f0 0f f0 00` | **Unverified** — unique magic; one sample only |
| Purpose of byte `0x24` (`01`) and bytes `0x8A`–`0x8C` (`67 68 69`) | **Unverified** — do not fit the record format |
| The `aX ?? 00 0[01]` + operand units are *executed* as configuration instructions | **Inferred, unverified** — the byte structure and 8-byte alignment are measured facts |
| `0xDFB2A250` / `0x08499D06` in the trailer are checksums | **Unverified inference** |
| The `a9 40 00 00` operands are 32-bit addresses | **Unverified inference** |
| PGL50H configuration bit count | **Not found** — size consistency argument only |
| Cause of the period-9 byte structure | **Unverified** — reproducible measurement |
| `.sbit` vs `.bit` vs `.fs` semantics | **Not verified** |
| MSB-first bit order of the driver loop | **Given as established**; corroborated only indirectly (§3) |

---

## 10. Reproducing this analysis

```
python sbit_analyze.py "D:\H3C\bak\mtd3_rootfs\lib\firmware\FTTR_TOP.sbit"
python sbit_analyze.py <file> --section header,tlv,align,map
python sbit_analyze.py <file> --dump-bytes 512
```

Sections: `overview, header, tlv, stats, runs, markers, align, map, auto`. Standard library only
(numpy is used opportunistically to accelerate the autocorrelation section). The script takes any
path, so it can be pointed at other Pango `.sbit` files to test whether the header record format and
the `aX` command structure generalise — which is the most direct way to close the unverified items
in §9.
