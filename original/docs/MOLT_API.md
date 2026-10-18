# H3C FTTR M-OLT service API — recovered reference

The vendor's FTTR management layer is a service plugin, `libminiolt_svc.so`,
loaded into the `moltd` daemon. It exposes a fixed command catalogue and a set
of typed get/set calls whose output formats are **already JSON**, because the
stock web UI (`sta-fttr_molt.asp`, `sta-fttr_onu.asp`) consumes them.

Everything below was recovered from `libminiolt_svc.so` and `moltdbg` in
`D:\H3C\bak\mtd3_rootfs`. The JSON field lists are not paraphrased: they are the
literal `printf`/`snprintf` format strings from the library's `.rodata`, so a
replacement daemon can emit byte-identical output and the existing front end
keeps working.

This file is the specification for the LuCI application in `luci/` and for any
replacement daemon.

---

## 1. Command catalogue

`miniolt_func_list` in `.data` at `0x21498` is an array of 40-byte records —
`{ u32 id; char *name; u64 reserved[2]; u32 flags_hi; u32 flags_lo; }` — holding
the complete service command set. Recovered verbatim:

| id | name | flags hi/lo |
| --- | --- | --- |
| 1 | `molt_init` | `0000`/`0001` |
| 2 | `molt_moduleInfo_get` | `0001`/`0000` |
| 3 | `molt_mgm_link_state_get` | `0001`/`0001` |
| 4 | `molt_log_level_set` | `0000`/`0001` |
| 5 | `molt_reset` | `0000`/`0000` |
| 6 | `molt_module_ver_upgrade` | `0000`/`0001` |
| 7 | `molt_deactive_subdevice` | `0000`/`0001` |
| 8 | `molt_pon_tx_set` | `0000`/`0001` |
| 9 | `molt_subdevice_tx_set` | `0000`/`0001` |
| 10 | `molt_rogue_subdevice_detect_set` | `0000`/`0001` |
| 11 | `molt_optical_info_get` | `0001`/`0001` |
| 12 | `molt_subdevice_optical_info_get` | `0001`/`0001` |
| 13 | `molt_subdevice_state_get` | `0001`/`0001` |
| 14 | `molt_bw_profile_set` | `0000`/`0001` |
| 15 | `molt_tcont_set` | `0000`/`0001` |
| 16 | `molt_uc_subinterface_set` | `0000`/`0001` |
| 17 | `molt_mc_subinterface_set` | `0000`/`0001` |
| 18 | `molt_subdevice_uni_vlanmode_set` | `0000`/`0001` |
| 19 | `molt_subdevice_uni_tag_mode_vlan_set` | `0000`/`0001` |
| 20 | `molt_subdevice_remote_gemport_vlan_map_set` | `0000`/`0001` |
| 21 | `molt_uplink_port_stats_get` | `0001`/`0000` |
| 22 | `molt_pon_port_stats_get` | `0001`/`0001` |
| 23 | `molt_mc_subinterface_stats_get` | `0001`/`0001` |
| 24 | `molt_subdevice_stats_get` | `0001`/`0001` |
| 27 | `miniolt_dbglevel_set` | `0000`/`0001` |

Ids 25 and 26 are absent from the shipped table — the vendor removed them
without renumbering. Do not renumber a replacement either: the ids are the wire
identity of the commands.

**The `flags_lo` bit is the read/write distinction** for a UI: every command
with `flags_lo == 0` is read-only (`molt_reset`, `molt_moduleInfo_get`,
`molt_uplink_port_stats_get`), and everything else mutates the OLT. Treat bit 0
of the low word as "read-only" and refuse to run the others without an explicit
confirmation, in the same spirit as zh-volt's `CommandRisk` gate.

## 2. Status / read-back calls

### 2.1 `molt_optical_info_get` — OLT optical module

Dump (`%.2f` throughout):

```
MOLT_OPTICAL_INFO:
  txState                 = %s
  txOpticalPwr            = %.2f dBm
  biasCurrent             = %.2f mA
  voltage                 = %.2f volt
  temprature              = %.2f degree C
```

JSON, exactly as the stock web UI receives it:

```json
{"biasCurrent":"%.2f","voltage":"%.2f","temprature":"%.2f",
 "txOpticalPwr":"%.2f","rxOpticalPwr":"%.2f","oltRxOpticalPwr":"%.2f",
 "upstreamOptAtten":"%.2f","downstreamOptAtten":"%.2f"}
```

Note the vendor's spelling: **`temprature`**, not `temperature`. A replacement
must keep it or the existing front end loses the field.

### 2.2 `molt_subdevice_state_get` — one sub-ONU

Dump field names are the struct member names:

```
MOLT_SUBDEVICE_STATE:
  subDeviceIdState        = %s        Used | Empty
  onuId                   = %u
  sn                      = %c%c%c%c%02X%02X%02X%02X
  snPassword              = %s[%02X × 10]
  loid                    = %s
  loidPassword            = %s
  regState                = %s
  omciState               = %s
  offlineReason           = %s
  lastOnlineTime          = %lu
  lastOfflineTime         = %lu
  lastPowerOffTime        = %lu
  totalOnlinePeriod       = %d
  distance                = %d m
  equipmentId             = %s
  softVer                 = %s
  hwVer                   = %s
```

JSON:

```json
{"subDeviceIdState":"%s","onuId":"%u","sn":"%c%c%c%c%02X%02X%02X%02X",
 "snPassword":"%s","loid":"%s","loidPassword":"%s","regState":"%s",
 "omciState":"%s","offlineReason":"%s","lastOnlineTime":"%lu",
 "lastOfflineTime":"%lu","lastPowerOffTime":"%lu","totalOnlinePeriod":"%d",
 "distance":"%d","equipmentId":"%s","softVer":"%s","hwVer":"%s"}
```

The serial number format is GPON-conventional: four ASCII bytes followed by
four raw bytes rendered as hex.

### 2.3 `molt_subdevice_optical_info_get` — one sub-ONU optics

```
MOLT_SUBDEVICE_OPTICAL_INFO:
  rxOpticalPwr            = %.2f dBm
  oltRxOpticalPwr         = %.2f dBm
  upstreamOptAtten        = %.2f dB
  downstreamOptAtten      = %.2f dB
```

### 2.4 `molt_moduleInfo_get` — module identity and health

```
fwMac, fwIpAddr, cpuUsage, memUsage, memUsedKbytes, partNo, ponType,
optiPwrType, splitType, endType, moduleSn, moduleVer, fwVer, moduleMac,
temperature
```

### 2.5 `molt_mgm_link_state_get` — management link

```
inbandMgmLinkState = %s     Running | Stoped | Down
i2cLinkState       = %s     Running | Stoped | Down
```

### 2.6 Port statistics

`molt_uplink_port_stats_get`:
`rxPkts, rxOctetsLow32, rxOctetsHigh32, rxUcPkts, rxBcPkts, rxMcPkts,
rxCrcErrPkts, txPkts, txOctetsLow32, txOctetsHigh32, txUcPkts, txBcPkts,
txMcPkts`

`molt_mc_subinterface_stats_get`:
`rxOctetsHigh28` plus the shared counter block below.

`molt_pon_port_stats_get` and `molt_subdevice_stats_get` share one JSON
template:

```json
{"rxPkts":"%u","rxOctetsLow32":"%u","rxOctetsHigh32":"%u","rxCrcErrPkts":"%u",
 "rxBipErr":"%u","rxBursts":"%u","rxGemFrms":"%u","txPkts":"%u",
 "txOctetsLow32":"%u","txOctetsHigh32":"%u","txGemFrms":"%u"}
```

## 3. Enumerations

`miniolt_getOfflineReason()` indexes a seven-entry table at `.data 0x218c0`:

| Value | Name |
| --- | --- |
| 0 | `POWEROFF` |
| 1 | `RANGING_FAIL` |
| 2 | `OMCI_SYNC_TIMEOUT` |
| 3 | `DISABLE_AFTER_ABNOMAL_TX` |
| 4 | `OPTICAL_LINK_ALARM` |
| 5 | `DEACTIVE_OPERATED` |
| 6 | `REBOOT_OPERATED` |

`miniolt_getOmciStateName()` (table at `.data 0x218f8`):

| Value | Name |
| --- | --- |
| 0 | `NOT_SYNC` |
| 1 | `SYNCING` |
| 2 | `SYNC_FINISH` |

`miniolt_getRegStateName()` (table at `.data 0x21910`):

| Value | Name |
| --- | --- |
| 0 | `OFFLINE` |
| 1 | `REGISTERING` |
| 2 | `REGISTED` |

`miniolt_getAlarmClass()` is a switch rather than a table, which means the
alarm ids are wire values that must not be renumbered:

| Value | Name |
| --- | --- |
| 0x00 | `PON_LOS` |
| 0x01 | `PON_TX_PWR_TOO_LOW` |
| 0x02 | `PON_RX_ABNORMAL_LIGHT` |
| 0x03 | `INBAND_MGM_LINK_BROKEN` |
| 0x04 | `I2C_LINK_BROKEN` |
| 0x64 | `SUBDEVICE_PON_LOSi` |
| 0x65 | `SUBDEVICE_DGi` |
| 0x68 | `SUBDEVICE_PON_TX_ABNORMAL_LIGHT` |
| 0x69 | `SUBDEVICE_PON_LOFi` |
| 0x6a | `SUBDEVICE_REMOTE_TX_PWR_TOO_LOW` |
| 0x6b | `SUBDEVICE_REMOTE_TX_PWR_TOO_HIGH` |
| 0x6c | `SUBDEVICE_REMOTE_RX_PWR_TOO_LOW` |
| 0x6d | `SUBDEVICE_REMOTE_RX_PWR_TOO_HIGH` |

The 0x64..0x6d block is per-sub-ONU and is offset from the OLT-wide 0x00..0x04
block by a deliberate gap; the `i` suffix marks the alarm as per-index.

Other strings, exact:

* `subDeviceIdState`: `Used` / `Empty`
* `inbandMgmLinkState`, `i2cLinkState`: `Running` / `Stoped` / `Down`
* module upgrade: `Running`, `VER_UPGRADE_FAIL`, `VER_UPGRADE_ALREADY_NEW`,
  `UpgradeProgress` rendered as `%d%%`
* `reportMode`: `Restore` / `Generate`
* log levels: `TRACE`, `INFO`, `ERROR`, `CRITICAL`, `CLOSE`
* amplification state: `Enabled` / `Disabled`

## 4. Asynchronous notifications

Two callbacks are registered through `molt_init`: `notifyReportCb` and
`alarmReportCb` (both visible as exported objects at `.data 0x21930`/`0x21938`).

Notification classes (`MOLT_NOTIFY_REPORTING`):

| Class | Payload |
| --- | --- |
| `ONLINE` | `subDeviceId`, `sn`, `snPassword`, `loid`, `loidPassword` |
| `OFFLINE` | `subDeviceId`, `offlineReason` |
| `REGISTERING` | `subDeviceId`, `sn`, `loid` |
| `MIB_SYNCING` | `subDeviceId` |
| `MODULE_VER_UPGRADE_OK` | — |
| `VER_UPGRADE_FAIL` | — |
| `VER_UPGRADE_ALREADY_NEW` | — |
| `MODULE_VER_UPGRADE_PROGRESS` | `progress` as `%d%%` |

Alarm reports (`MOLT_ALARM_REPORTING`) carry `alarmClassId`, `reportMode`,
`oltId`, `subDeviceId`, `alarmInfo1`, `alarmInfo2`, and five thresholds:
`oltTxPwrTooLow`, `subDevRmtTxPwrTooLow`, `subDevRmtTxPwrTooHigh`,
`subDevRmtRxPwrTooLow`, `subDevRmtRxPwrTooHigh`.

The module also bridges to the platform event bus:

```
ecnt_event_send ECNT_EVENT_DBUS, ECNT_EVENT_DBUS_SUBDEVICE_STATUS_UPDATE=online
ecnt_event_send ECNT_EVENT_DBUS, ECNT_EVENT_DBUS_SUBDEVICE_STATUS_UPDATE=offline
```

On every Online/Offline transition it drives the front-panel LED through shell
helpers — `/usr/script/led_ctl auto &`, `led_ctl off molt &`,
`led_ctl blink molt /tmp/molt.err &` — with `/tmp/molt.err` as the
out-of-band error channel.

## 5. Configuration surface (`molt_init`)

```
MOLT_INIT_PARA:
  -----GLOBAL CFG--------
  fwPath, mdPath, i2cMode, logPath, logFileSize, logLevel,
  alarmReportCb, notifyReportCb
  -----OLT CFG------------
  i2cDev, inBandMgmPduVlanid, inBandMgmPduCos, inBandMgmPduInfName,
  module_mac_addr
```

Defaults pulled from the library's own `.data`: `fwPath` `/userfs/bin`,
`mdPath` `/tmp`, `logPath` `/var/log/molt`, `i2cDev` **`/dev/bdi2c`**,
`inBandMgmPduInfName` **`molt`**.

## 6. Bringing the management path up

`molt_init` shells out to stand the management VLAN up on the SoC MAC:

```sh
brctl delif br0 eth1 > /dev/null 2>&1
ip link add link eth1 molt type vlan id %d > /dev/null 2>&1
ifconfig molt up
cat /proc/tc3162/hsgmii_usb_lan_link_status
```

The VLAN id comes from `inBandMgmPduVlanid`. A port must reproduce this: the
`molt` interface is the in-band management carrier for the sub-ONUs, and it is
created on **`eth1`** — the same interface the FMCS driver resolves at load
time (see `docs/REVERSE_ENGINEERING.md` section 5).

A replacement should also honour the teardown path, which the vendor ships as a
one-liner and which is easy to get wrong:

```sh
ps|grep moltd|grep -v grep |awk '{print $1}'|xargs kill -9
rm -f /var/run/moltd.pid
ifconfig molt down
vconfig rem molt
```

## 7. Debug CLI (`moltdbg`)

`moltdbg` groups raw diagnostic verbs, useful when bringing a board up:

| Group | Verbs |
| --- | --- |
| `fpga` | error-collection dump, upstream and downstream error info, `bandwidth`, `burst`, `bip`, `omci`, upstream/downstream usage |
| `genl` | `ploam`, `omci0`..`omci3`, `port`, `handshake`, `loadfile`, `loadfirm`, `autoloadfirm` |

Two things here matter for the port:

* `DbgReadFpgaRegVal` reports `READ FPGA: addr<0x%08x> val<0x%08x>`, so the
  debug CLI reaches FPGA registers directly — through the same FMCS ioctl the
  port already implements.
* The `genl` verbs `loadfile`, `loadfirm` and `autoloadfirm` are **not** present
  as separate genetlink families in `fmcs.ko`; they look like sub-commands of a
  single `genl_FPGA` operation. This suggests an FPGA firmware load path over
  genetlink that the `fmcs.ko` symbol table does not obviously show, and it is
  worth recovering before concluding that `fpga_load.ko` is the only loader.

  It also matches `moltdbg`'s own hint:

  ```
  check interrupt count, FPGA use interrupts to let fmcs driver know when to
  read ploam data: cat /proc/interrupts | grep fmcs
  ```

## 8. What a LuCI application can show today

The data model above is fully recovered, but the daemon that produces it is
not: `moltd` needs the FMCS driver to reach the FPGA. So the LuCI application in
this tree is deliberately staged:

* **Stage 1 (shipped):** driver and device state, plus a raw FPGA/BOSA register
  console. This works as soon as the register transport exists, and it is the
  tool used to keep probing the FPGA.
* **Stage 2 (specified here, not yet wired):** the M-OLT panels — OLT optical
  values, the sub-ONU list with registration and OMCI state, per-ONU optics and
  statistics — using the exact JSON field names in sections 2 and 3, so that the
  vendor's own front end and this one can share a daemon.

Stage 2 needs a daemon that speaks this API. `libminiolt_svc.so` is that
daemon's plugin, and it reaches the hardware through `moltd`; reimplementing it
means either running the vendor binary against the ported driver or writing a
replacement against the recovered catalogue.
