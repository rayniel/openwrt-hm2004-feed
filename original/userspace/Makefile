# SPDX-License-Identifier: GPL-2.0-only
#
# Userspace tools for the H3C HM2004-DU FMCS FTTR M-OLT FPGA.

CC	?= $(CROSS_COMPILE)gcc
CFLAGS	?= -O2 -Wall -Wextra -Werror
CPPFLAGS += -I../driver

PREFIX	?= /usr
BINDIR	?= $(PREFIX)/bin

PROGRAMS := miniolt

all: $(PROGRAMS)

miniolt: miniolt.c ../driver/fmcs_uapi.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ miniolt.c

install: $(PROGRAMS)
	install -d $(DESTDIR)$(BINDIR)
	install -m 0755 $(PROGRAMS) $(DESTDIR)$(BINDIR)/

clean:
	rm -f $(PROGRAMS)

.PHONY: all install clean
