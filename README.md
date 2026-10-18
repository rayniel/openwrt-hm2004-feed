# OpenWrt HM2004 FTTR feed

OpenWrt package feed for experimental H3C HM2004-DU FTTR/FMCS components.
This repository packages the existing driver, `miniolt` utility, and LuCI
application; it is not a complete or verified FTTR firmware port.

## Packages

| Package | OpenWrt package name | Purpose |
| --- | --- | --- |
| `package/fttr-fmcs/` | `kmod-fttr-fmcs` | FMCS kernel driver |
| `package/fttr-tools/` | `fttr-tools` | `miniolt` command-line utility |
| `package/hm2004-fttr-firmware/` | `hm2004-fttr-firmware` | Optional FTTR FPGA bitstream |
| `luci/luci-app-h3c-fttr/` | `luci-app-h3c-fttr` | LuCI status/control page |

The driver and userspace package recipes stage their sources from `original/`.
The LuCI app is copied into the conventional `luci/` feed subtree. The
`original/` directory is retained as the supplied port snapshot and includes
reverse-engineering notes and static checks.

## Add the feed to OpenWrt

Replace the URL with the Git remote for this repository and add one line to
`feeds.conf` (or `feeds.conf.default`):

```text
src-git hm2004 https://github.com/<owner>/openwrt-hm2004-feed.git
```

Then install the package definitions:

```sh
./scripts/feeds update hm2004
./scripts/feeds install -p hm2004 fttr-fmcs fttr-tools \
  hm2004-fttr-firmware luci-app-h3c-fttr
make menuconfig
```

Select `kmod-fttr-fmcs` under Kernel modules, `fttr-tools` under Utilities,
`hm2004-fttr-firmware` under Firmware, and `luci-app-h3c-fttr` under LuCI
applications. The LuCI package requires the OpenWrt LuCI feed to be enabled
and installed.

For a local checkout, use a `src-link` entry instead:

```text
src-link hm2004 /path/to/openwrt-hm2004-feed
```

## Important integration gaps

The package recipes make the components available to OpenWrt's package
selection and build system. They do not make the hardware support complete:

- The FMCS register transport still needs a validated device-tree connection.
  The stock SPI controller is owned by SPI-NAND, and the GPIO transport pins
  are not identified in the stock device tree. Do not enable the FMCS node or
  apply `original/patches/0001-arm64-dts-airoha-hm2004-du-enable-fmcs.patch`
  until the transport wiring is resolved for the target kernel and board.
- `FTTR_TOP.sbit` is installed by the separate, opt-in
  `hm2004-fttr-firmware` package from `original/driver/bin/`. The package is
  marked proprietary; its presence does not establish redistribution rights.
  Review those rights before publishing or distributing builds containing it.
- The full stock M-OLT daemon and the HM2004 FTTR Ethernet data-path hooks are
  not provided by these packages. A successful package build does not mean
  that sub-ONU management or traffic forwarding works.
- The package has not yet been built against a pinned OpenWrt commit and
  target configuration. Validate it on the intended Airoha/OpenWrt tree
  before deployment.

See [`docs/INTEGRATION.md`](docs/INTEGRATION.md) and the reference dossier in
[`original/docs/`](original/docs/) for current technical findings.
