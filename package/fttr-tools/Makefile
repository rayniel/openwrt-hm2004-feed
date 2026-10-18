FTTR_SOURCE_ROOT:=$(TOPDIR)/feeds/hm2004/original

include $(TOPDIR)/rules.mk

PKG_NAME:=fttr-tools
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_LICENSE:=GPL-2.0-only
PKG_MAINTAINER:=HM2004 FTTR maintainers

include $(INCLUDE_DIR)/package.mk

define Package/fttr-tools
  SECTION:=utils
  CATEGORY:=Utilities
  TITLE:=HM2004-DU FMCS FTTR command-line tools
  DEPENDS:=+kmod-fttr-fmcs
endef

define Package/fttr-tools/description
  miniolt command-line utility for accessing the FMCS FPGA through the
  /dev/fmcs_mci device provided by kmod-fttr-fmcs.
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) $(FTTR_SOURCE_ROOT)/userspace/* $(PKG_BUILD_DIR)/
	$(CP) $(FTTR_SOURCE_ROOT)/driver/fmcs_uapi.h $(PKG_BUILD_DIR)/
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
