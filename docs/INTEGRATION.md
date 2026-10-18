# OpenWrt integration status

## What this feed packages

- `kmod-fttr-fmcs`: out-of-tree kernel module, built against the selected
  OpenWrt kernel headers and target configuration.
- `fttr-tools`: cross-compiled `miniolt` userspace utility.
- `hm2004-fttr-firmware`: optional package for `FTTR_TOP.sbit`.
- `luci-app-h3c-fttr`: LuCI app and rpcd shim.

The kernel and userspace recipes use source from `original/`. The LuCI package
is placed in the conventional `luci/` feed subtree so the `luci.mk` build
system can stage its `htdocs/` and `root/` files.

## Device-tree work is not automatic

An external package feed cannot by itself modify and rebuild a board's device
tree. The DTS patch under `original/patches/` is a reference, not an automatic
OpenWrt patch hook. It also does not provide a proven register transport:

- The current kernel tree reserves the relevant controller for SPI-NAND.
- The alternate GPIO bit-bang path requires four physical FPGA SPI pins that
  are not identified in the stock device tree.
- The supplied DTS fragment documents both directions, but the actual wiring
  and pin multiplexing must be established before enabling the node.

Until that work is complete, the FMCS module may compile as a package but
cannot be considered operational on the HM2004-DU.

## Firmware

The driver asks the kernel firmware loader for
`/lib/firmware/FTTR_TOP.sbit` when `CONFIG_FTTR_FMCS_LOAD_AT_PROBE` is enabled.
The optional `hm2004-fttr-firmware` package installs the extracted file from
`original/driver/bin/FTTR_TOP.sbit`. It is not a dependency of the kernel
module, so builds can omit this proprietary artifact. Its presence in the feed
does not establish redistribution rights; review those rights before
publishing or distributing a build that includes it.

The driver logs a warning and continues if loading the bitstream fails, but
FPGA register access still requires a compatible bitstream already loaded and
a working transport.

## Suggested next engineering steps

1. Pin the intended OpenWrt source and Airoha target revision; build the feed
   packages in that tree and fix any kernel API or packaging errors.
2. Resolve and validate the FPGA register transport on hardware, including the
   SPI controller ownership or measured GPIO pin mapping. Keep the FMCS device
   tree node disabled until then.
3. Package the bitstream separately only after deciding how it can be
   redistributed and verifying the file against the target board.
4. Test basic FPGA register reads and IRQ behavior before working on the
   missing Ethernet FTTR hooks or M-OLT daemon.
