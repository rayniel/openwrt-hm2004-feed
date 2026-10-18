"""Type-check the userspace sources with clang against a generated stub libc.

No Linux or libc headers are available on this host, so the checker writes a
minimal but accurate stub include tree into a scratch directory and compiles:

  * tools/abi_static_assert.c - compile-time proof that the reconstructed ioctl
    constants in driver/fmcs_uapi.h equal the literals recovered from fmcs.ko;
  * userspace/miniolt.c       - the command line tool.

The stubs only need to be accurate enough for the compiler to check the real
code: declarations must match their real signatures, but the bodies never run.
Anything the real headers declare differently would be a stub defect, not a
defect the checker is meant to find.

Run:  python tools/check_c.py
Exit: 0 when everything compiles, 1 otherwise.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CLANG_CANDIDATES = [
    r"C:\Program Files\AMD\ROCm\7.1\bin\clang.exe",
    "clang",
    "cc",
    "gcc",
]

# ---------------------------------------------------------------------------
# Stub headers
# ---------------------------------------------------------------------------

STUBS = {
    "linux/types.h": """
#ifndef _STUB_LINUX_TYPES_H
#define _STUB_LINUX_TYPES_H
typedef unsigned char __u8;
typedef signed char __s8;
typedef unsigned short __u16;
typedef signed short __s16;
typedef unsigned int __u32;
typedef signed int __s32;
typedef unsigned long long __u64;
typedef signed long long __s64;
typedef __u16 __le16;
typedef __u16 __be16;
typedef __u32 __be32;
#endif
""",
    # Transcribed from include/uapi/asm-generic/ioctl.h.
    "linux/ioctl.h": """
#ifndef _STUB_LINUX_IOCTL_H
#define _STUB_LINUX_IOCTL_H
#define _IOC_NRBITS 8
#define _IOC_TYPEBITS 8
#define _IOC_SIZEBITS 14
#define _IOC_DIRBITS 2
#define _IOC_NRSHIFT 0
#define _IOC_TYPESHIFT (_IOC_NRSHIFT + _IOC_NRBITS)
#define _IOC_SIZESHIFT (_IOC_TYPESHIFT + _IOC_TYPEBITS)
#define _IOC_DIRSHIFT (_IOC_SIZESHIFT + _IOC_SIZEBITS)
#define _IOC_NONE 0U
#define _IOC_WRITE 1U
#define _IOC_READ 2U
#define _IOC(dir,type,nr,size) \\
    (((dir) << _IOC_DIRSHIFT) | ((type) << _IOC_TYPESHIFT) | \\
     ((nr) << _IOC_NRSHIFT) | ((size) << _IOC_SIZESHIFT))
#define _IOC_TYPECHECK(t) (sizeof(t))
#define _IO(type,nr) _IOC(_IOC_NONE,(type),(nr),0)
#define _IOR(type,nr,size) _IOC(_IOC_READ,(type),(nr),(_IOC_TYPECHECK(size)))
#define _IOW(type,nr,size) _IOC(_IOC_WRITE,(type),(nr),(_IOC_TYPECHECK(size)))
#define _IOWR(type,nr,size) _IOC(_IOC_READ|_IOC_WRITE,(type),(nr),(_IOC_TYPECHECK(size)))
#define _IOC_DIR(nr) (((nr) >> _IOC_DIRSHIFT) & ((1U << _IOC_DIRBITS)-1))
#define _IOC_TYPE(nr) (((nr) >> _IOC_TYPESHIFT) & ((1U << _IOC_TYPEBITS)-1))
#define _IOC_NR(nr) (((nr) >> _IOC_NRSHIFT) & ((1U << _IOC_NRBITS)-1))
#define _IOC_SIZE(nr) (((nr) >> _IOC_SIZESHIFT) & ((1U << _IOC_SIZEBITS)-1))
#endif
""",
    "stdbool.h": """
#ifndef _STUB_STDBOOL_H
#define _STUB_STDBOOL_H
#define bool _Bool
#define true 1
#define false 0
#endif
""",
    "stdint.h": """
#ifndef _STUB_STDINT_H
#define _STUB_STDINT_H
typedef unsigned char uint8_t;
typedef unsigned short uint16_t;
typedef unsigned int uint32_t;
typedef unsigned long long uint64_t;
typedef signed char int8_t;
typedef signed int int32_t;
#endif
""",
    "stddef.h": """
#ifndef _STUB_STDDEF_H
#define _STUB_STDDEF_H
typedef unsigned long size_t;
typedef long ssize_t;
#define NULL ((void *)0)
#endif
""",
    "stdio.h": """
#ifndef _STUB_STDIO_H
#define _STUB_STDIO_H
#include <stddef.h>
typedef struct _stub_FILE FILE;
extern FILE *stderr;
int printf(const char *fmt, ...);
int fprintf(FILE *stream, const char *fmt, ...);
int puts(const char *s);
#endif
""",
    "stdlib.h": """
#ifndef _STUB_STDLIB_H
#define _STUB_STDLIB_H
#include <stddef.h>
unsigned long strtoul(const char *nptr, char **endptr, int base);
long strtol(const char *nptr, char **endptr, int base);
#endif
""",
    "string.h": """
#ifndef _STUB_STRING_H
#define _STUB_STRING_H
#include <stddef.h>
void *memcpy(void *dest, const void *src, size_t n);
void *memset(void *s, int c, size_t n);
int strcmp(const char *s1, const char *s2);
int strncmp(const char *s1, const char *s2, size_t n);
size_t strlen(const char *s);
char *strncpy(char *dest, const char *src, size_t n);
char *strerror(int errnum);
#endif
""",
    "unistd.h": """
#ifndef _STUB_UNISTD_H
#define _STUB_UNISTD_H
#include <stddef.h>
#include <sys/types.h>
unsigned int sleep(unsigned int seconds);
int close(int fd);
ssize_t write(int fd, const void *buf, size_t count);
#endif
""",
    "errno.h": """
#ifndef _STUB_ERRNO_H
#define _STUB_ERRNO_H
extern int errno;
#endif
""",
    "fcntl.h": """
#ifndef _STUB_FCNTL_H
#define _STUB_FCNTL_H
#define O_RDONLY 0
#define O_WRONLY 1
#define O_RDWR 2
int open(const char *pathname, int flags, ...);
#endif
""",
    "sys/types.h": """
#ifndef _STUB_SYS_TYPES_H
#define _STUB_SYS_TYPES_H
typedef long ssize_t;
typedef unsigned int mode_t;
typedef unsigned int socklen_t;
#endif
""",
    "sys/ioctl.h": """
#ifndef _STUB_SYS_IOCTL_H
#define _STUB_SYS_IOCTL_H
#define SIOCGIFINDEX 0x8933
int ioctl(int fd, unsigned long request, ...);
#endif
""",
    "sys/socket.h": """
#ifndef _STUB_SYS_SOCKET_H
#define _STUB_SYS_SOCKET_H
#include <stddef.h>
#include <sys/types.h>
typedef unsigned short sa_family_t;
struct sockaddr { sa_family_t sa_family; char sa_data[14]; };
int socket(int domain, int type, int protocol);
int bind(int sockfd, const struct sockaddr *addr, socklen_t addrlen);
ssize_t sendto(int sockfd, const void *buf, size_t len, int flags,
               const struct sockaddr *dest_addr, socklen_t addrlen);
#endif
""",
    "arpa/inet.h": """
#ifndef _STUB_ARPA_INET_H
#define _STUB_ARPA_INET_H
unsigned short htons(unsigned short hostshort);
#endif
""",
    "net/if.h": """
#ifndef _STUB_NET_IF_H
#define _STUB_NET_IF_H
#define IFNAMSIZ 16
struct ifreq {
    char ifr_name[IFNAMSIZ];
    union { int ifr_ifindex; } ifr_ifru;
};
#define ifr_ifindex ifr_ifru.ifr_ifindex
unsigned int if_nametoindex(const char *ifname);
#endif
""",
    "netpacket/packet.h": """
#ifndef _STUB_NETPACKET_PACKET_H
#define _STUB_NETPACKET_PACKET_H
#include <sys/socket.h>
#define AF_PACKET 17
#define SOCK_RAW 3
#define ETH_P_ALL 0x0003
#define ETH_ALEN 6
struct sockaddr_ll {
    unsigned short sll_family;
    unsigned short sll_protocol;
    int sll_ifindex;
    unsigned short sll_hatype;
    unsigned char sll_pkttype;
    unsigned char sll_halen;
    unsigned char sll_addr[8];
};
#endif
""",
}


def find_clang():
    for candidate in CLANG_CANDIDATES:
        path = shutil.which(candidate)
        if path:
            return path
        if Path(candidate).exists():
            return candidate
    return None


def main():
    clang = find_clang()
    if not clang:
        print("no C compiler found; tried: %s" % ", ".join(CLANG_CANDIDATES))
        return 1

    print("compiler: %s" % clang)

    scratch = Path(tempfile.mkdtemp(prefix="fmcs-stubinc-"))
    try:
        for rel, body in STUBS.items():
            dest = scratch / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(body, encoding="utf8")

        jobs = [
            ("ABI static assertions", ROOT / "tools" / "abi_static_assert.c"),
            ("miniolt", ROOT / "userspace" / "miniolt.c"),
        ]

        failed = []
        for label, source in jobs:
            cmd = [
                clang, "-fsyntax-only", "-std=gnu11",
                # Check against the actual deployment target, not the host.
                # On the host's default MSVC target size_t is `unsigned long
                # long`, which conflicts with the stub tree and mis-sizes
                # unsigned long in pointer arithmetic.
                "--target=aarch64-linux-gnu",
                "-Wall", "-Wextra", "-Werror",
                "-nostdinc",
                "-I", str(scratch),
                "-I", str(ROOT / "driver"),
                "-I", str(ROOT / "userspace"),
                str(source),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            ok = proc.returncode == 0
            print("  %-5s %s" % ("PASS" if ok else "FAIL", label))
            if not ok:
                failed.append(label)
                for line in (proc.stderr or "").splitlines()[:40]:
                    print("        " + line)

        if failed:
            print("FAILED: %s" % ", ".join(failed))
            return 1

        print("All sources type-check.")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
