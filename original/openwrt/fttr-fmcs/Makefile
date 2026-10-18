#
# H3C FMCS (FTTR M-OLT) FPGA driver
#
# Builds the driver from the local driver/ directory of this feed, following the
# pattern zh-volt uses: there is no PKG_SOURCE_URL, the feed checkout is the
# source.
#
include $(TOPDIR)/rules.mk
include $(INCLUDE_DIR)/kernel.mk

PKG_NAME:=fttr-fmcs
PKG_RELEASE:=1
PKG_LICENSE:=GPL-2.0-only
PKG_MAINTAINER:=H3C HM2004-DU FTTR port

FTTR_FMCS_SOURCE_DIR:=$(abspath $(dir $(lastword $(MAKEFILE_LIST)))../..)
FTTR_FMCS_VERSION:=$(shell sed -n 's/^#define FMCS_DRV_VERSION[[:space:]]*"\(.*\)"/\1/p' \
	$(FTTR_FMCS_SOURCE_DIR)/driver/fmcs.h 2>/dev/null || echo unknown)

PKG_VERSION:=$(FTTR_FMCS_VERSION)

include $(INCLUDE_DIR)/package.mk

define Package/fttr-fmcs/Default
  SECTION:=kernel
  CATEGORY:=Kernel modules
  URL:=https://github.com/qwe3017/ponwrt
endef

define KernelPackage/fttr-fmcs
  $(call Package/fttr-fmcs/Default)
  SUBMENU:=Other modules
  TITLE:=H3C FMCS FTTR M-OLT FPGA support
  DEPENDS:=@TARGET_airoha +kmod-spi-bitbang
  FILES:=$(PKG_BUILD_DIR)/fttr-fmcs.ko
  AUTOLOAD:=$(call AutoProbe,fttr-fmcs)
  KCONFIG:=CONFIG_FTTR_FMCS=m CONFIG_FTTR_FMCS_LOAD_AT_PROBE=y
endef

define KernelPackage/fttr-fmcs/description
  Driver for the FMCS downlink FPGA that provides the FTTR master-OLT function
  on the H3C HM2004-DU.  Publishes /dev/fmcs_mci with the vendor ioctl ABI, the
  molt_ploam and molt_omci control net devices, and the genl_* event families
  the stock PLOAM and OMCI stacks use.

  Requires a device tree node described by dts/h3c-fmcs.dtsi.
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) $(FTTR_FMCS_SOURCE_DIR)/driver/* $(PKG_BUILD_DIR)/
endef

define Build/Compile
	$(MAKE) -C "$(LINUX_DIR)" \
		$(KERNEL_MAKE_FLAGS) \
		M="$(PKG_BUILD_DIR)" \
		modules
endef

$(eval $(call KernelPackage,fttr-fmcs))
