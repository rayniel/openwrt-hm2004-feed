// SPDX-License-Identifier: GPL-2.0-only
/*
 * Compile-time check that the reconstructed FMCS ioctl ABI matches the numbers
 * the vendor module fmcs.ko actually dispatches on.
 *
 * The expected values are not copied from fmcs_uapi.h -- they are the literals
 * recovered from the compare chain in FmcsMciIoctl(), each materialised there as
 * a mov/movk pair.  If the header and the binary ever drift apart this file
 * stops compiling.
 *
 * tools/check_c.py builds this together with the userspace tool.
 */
#include "fmcs_uapi.h"

#define FMCS_CHECK(expr)	_Static_assert((expr), #expr)

/* 0x4008a500: FmcsMciIoctl case for a 32-bit FPGA register write. */
FMCS_CHECK(FMCS_IOC_WR_FPGA_REG == 0x4008a500);
/* 0xc008a501: read back; the vendor copies in and out, hence _IOWR. */
FMCS_CHECK(FMCS_IOC_RD_FPGA_REG == 0xc008a501);
/* 0x4008a502 / 0xc008a503: the BOSA window, same opcodes, different address. */
FMCS_CHECK(FMCS_IOC_WR_BOSA_REG == 0x4008a502);
FMCS_CHECK(FMCS_IOC_RD_BOSA_REG == 0xc008a503);
/* 0x4008a504 / 0x8008a505: the size field is 8, not the 13-byte payload. */
FMCS_CHECK(FMCS_IOC_SEND_PLOAM == 0x4008a504);
FMCS_CHECK(FMCS_IOC_RECV_PLOAM == 0x8008a505);
/* 0x4001a506: the argument is a repetition count, not a pointer. */
FMCS_CHECK(FMCS_IOC_SEND_HSGMII == 0x4001a506);

/* The dispatcher rejects any other type byte before it takes its mutex. */
FMCS_CHECK(FMCS_IOCTL_MAGIC == 0xa5);

/* Argument layouts. */
FMCS_CHECK(sizeof(struct fmcs_reg) == 8);
FMCS_CHECK(sizeof(struct fmcs_ioctl_size_quirk) == 8);
FMCS_CHECK(FMCS_PLOAM_LEN == 13);

/* The two PLOAM commands must keep their eight-byte size field. */
FMCS_CHECK(_IOC_SIZE(FMCS_IOC_SEND_PLOAM) == 8);
FMCS_CHECK(_IOC_SIZE(FMCS_IOC_RECV_PLOAM) == 8);

/* Directions: writes carry a struct in, the read commands carry it back out. */
FMCS_CHECK(_IOC_DIR(FMCS_IOC_WR_FPGA_REG) == _IOC_WRITE);
FMCS_CHECK(_IOC_DIR(FMCS_IOC_RD_FPGA_REG) == (_IOC_READ | _IOC_WRITE));
FMCS_CHECK(_IOC_DIR(FMCS_IOC_RECV_PLOAM) == _IOC_READ);

int fmcs_abi_static_assert_anchor;
