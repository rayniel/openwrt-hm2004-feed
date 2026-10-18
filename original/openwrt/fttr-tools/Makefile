#
# miniolt - command line access to the FMCS FTTR M-OLT FPGA registers
#
include $(TOPDIR)/rules.mk

PKG_NAME:=fttr-tools
PKG_RELEASE:=1
PKG_LICENSE:=GPL-2.0-only
PKG_MAINTAINER:=H3C HM2004-DU FTTR port

FTTR_TOOLS_SOURCE_DIR:=$(abspath $(dir $(lastword $(MAKEFILE_LIST)))../..)

include $(INCLUDE_DIR)/package.mk

define Package/fttr-tools
  SECTION:=utils
  CATEGORY:=Utilities
  TITLE:=miniolt - FMCS FTTR M-OLT register and PLOAM tool
  DEPENDS:=+fttr-fmcs
endef

define Package/fttr-tools/description
  Source port of the stock miniolt utility.  Reads and writes FPGA and BOSA
  registers through /dev/fmcs_mci and injects PLOAM and OMCI frames on the
  molt_omci net device.
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) $(FTTR_TOOLS_SOURCE_DIR)/userspace/* $(PKG_BUILD_DIR)/
	$(CP) $(FTTR_TOOLS_SOURCE_DIR)/driver/fmcs_uapi.h $(PKG_BUILD_DIR)/
endef

define Build/Compile
	$(MAKE) -C $(PKG_BUILD_DIR) \
		$(TARGET_CONFIGURE_OPTS) \
		CPPFLAGS="-I$(PKG_BUILD_DIR)" \
		CFLAGS="$(TARGET_CFLAGS) -Wall -Wextra"
endef

define Package/fttr-tools/install
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/miniolt $(1)/usr/bin/miniolt
endef

$(eval $(call BuildPackage,fttr-tools))
