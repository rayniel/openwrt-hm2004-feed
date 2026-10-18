# Capture the feed path before including OpenWrt makefiles.
FTTR_SOURCE_ROOT:=$(TOPDIR)/feeds/hm2004/original

include $(TOPDIR)/rules.mk
include $(INCLUDE_DIR)/kernel.mk

PKG_NAME:=fttr-fmcs
PKG_VERSION:=$(shell sed -n 's/^#define FMCS_DRV_VERSION[[:space:]]*"\(.*\)"/\1/p' \
	$(FTTR_SOURCE_ROOT)/driver/fmcs.h)
PKG_RELEASE:=1
PKG_LICENSE:=GPL-2.0-only
PKG_MAINTAINER:=HM2004 FTTR maintainers

include $(INCLUDE_DIR)/package.mk

define KernelPackage/fttr-fmcs
  SUBMENU:=Other modules
  TITLE:=H3C HM2004-DU FTTR FMCS driver
  DEPENDS:=@TARGET_airoha
  FILES:=$(PKG_BUILD_DIR)/fttr-fmcs.ko
  AUTOLOAD:=$(call AutoProbe,fttr-fmcs)
  KCONFIG:=CONFIG_FTTR_FMCS=m CONFIG_FTTR_FMCS_LOAD_AT_PROBE=y
endef

define KernelPackage/fttr-fmcs/description
  Experimental driver for the H3C HM2004-DU FTTR master-OLT FPGA.
  A matching device-tree node and a working SPI or GPIO transport are required.
  The optional FPGA bitstream is not included in this feed.
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) $(FTTR_SOURCE_ROOT)/driver/* $(PKG_BUILD_DIR)/
endef

define Build/Compile
	$(MAKE) -C "$(LINUX_DIR)" \
		$(KERNEL_MAKE_FLAGS) \
		M="$(PKG_BUILD_DIR)" \
		modules
endef

$(eval $(call KernelPackage,fttr-fmcs))
