include $(TOPDIR)/rules.mk

PKG_NAME:=hm2004-fttr-firmware
PKG_VERSION:=1
PKG_RELEASE:=1
PKG_LICENSE:=Proprietary
PKG_FLAGS:=nonshared
PKGARCH:=all
PKG_MAINTAINER:=HM2004 FTTR contributors

include $(INCLUDE_DIR)/package.mk

define Package/hm2004-fttr-firmware
  SECTION:=firmware
  CATEGORY:=Firmware
  TITLE:=H3C HM2004-DU FTTR FPGA bitstream
  DEPENDS:=@TARGET_airoha
endef

define Package/hm2004-fttr-firmware/description
  Installs the locally supplied FTTR_TOP.sbit FPGA configuration file used by
  the H3C HM2004-DU FMCS driver. Redistribution rights are not established.
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) $(TOPDIR)/feeds/hm2004/original/driver/bin/FTTR_TOP.sbit \
		$(PKG_BUILD_DIR)/FTTR_TOP.sbit
endef

define Build/Compile
endef

define Package/hm2004-fttr-firmware/install
	$(INSTALL_DIR) $(1)/lib/firmware
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/FTTR_TOP.sbit \
		$(1)/lib/firmware/FTTR_TOP.sbit
endef

$(eval $(call BuildPackage,hm2004-fttr-firmware))
