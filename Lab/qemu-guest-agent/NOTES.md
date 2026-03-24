# QEMU Guest Agent (QGA) on MikroTik RouterOS CHR — Investigation Notes

## Summary

RouterOS CHR includes a **native QEMU Guest Agent** implementation that works
over the standard `org.qemu.guest_agent.0` virtio-serial channel. It is functional
on **x86_64 only**. On aarch64, the virtio-serial device is present in QEMU but
**RouterOS never opens the guest-side port** — the QGA service does not appear to
run on the aarch64 build.

**Tested on aarch64 with:**
- RouterOS 7.22 (stable) — QGA not functional
- RouterOS 7.23_ab650 (development, MikroTik test build) — QGA **still not functional**
- Also tested `chr.provision_channel` (MikroTik-specific) — **also not functional**

Both aarch64 builds show identical behavior: the virtio-serial PCI device is
enumerated and the kernel driver binds (IRQs allocated), but no userspace QGA
daemon opens the `org.qemu.guest_agent.0` port.  Neither does the MikroTik-specific
`chr.provision_channel` respond.  The issue is at the packaging level — the guest
agent/provisioning services are not included in the ARM64 routeros build.

**This is MikroTik's own QGA implementation** (not stock `qemu-ga`): version
"2.10.50" matches no QEMU release, `guest-exec` only accepts `input-data`
(RouterOS script), `guest-file-open` uses flat RouterOS filenames, and
`guest-get-osinfo` returns `"id": "routeros"`.  The additional
`chr.provision_channel` is entirely MikroTik-specific.

The agent reports version **2.10.50** and supports **21 commands**, which is
significantly more than some online references suggest. Key capabilities include
script execution (`guest-exec`), file transfer (`guest-file-*`), network interface
enumeration, OS info, hostname, time, timezone, filesystem freeze/thaw, and
shutdown.

## Test Environment

### Original test (RouterOS 7.22)

- **Host**: Linux x86_64 (SteamDeck, Zen 2 APU)
- **QEMU**: 9.2.0
- **RouterOS**: 7.22 (stable)
- **x86_64 machine**: `chr.x86_64.qemu.7.22` — q35, KVM, SeaBIOS
- **aarch64 machine**: `chr.aarch64.qemu.7.22` — virt, TCG (cross-arch)

### Retest (RouterOS 7.23_ab650 development build)

- **Host**: macOS x86_64 (Intel)
- **QEMU**: 10.2.2
- **RouterOS**: 7.23_ab650 (development), built 2026-03-23 10:22:36
- **Image**: `chr-7.23_ab650-arm64.img` (128 MiB, custom build from MikroTik)
- **aarch64 machine**: `virt`, `cortex-a710`, 1024M, 2 CPUs, TCG (cross-arch)
- **UEFI firmware**: edk2-aarch64-code.fd + edk2-arm-vars.fd (64 MiB each)

## QEMU Setup for Guest Agent

The standard mikropkl qemu.cfg does **not** include virtio-serial. To enable QGA,
add these devices via `QEMU_EXTRA` (or modify qemu.cfg):

```sh
export QEMU_EXTRA=" \
  -device virtio-serial-pci,id=virtio-serial-qga \
  -chardev socket,id=qga0,path=/tmp/qga-<machine>.sock,server=on,wait=off \
  -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0,id=qga-port0"
```

Then launch normally via `qemu.sh --background`. The QGA Unix socket appears
immediately; RouterOS opens the guest side within a few seconds of boot.

### Hot-add: NOT possible on q35

Attempted to hot-add `virtio-serial-pci` via QEMU monitor:
```
(qemu) device_add virtio-serial-pci,id=virtio-serial0
Error: Bus 'pcie.0' does not support hotplugging
```
The device must be present at VM creation time.

## x86_64 Results — Full Test (RouterOS 7.22)

### guest-info

Agent version: **2.10.50**

21 supported commands:
- `guest-exec`
- `guest-exec-status`
- `guest-file-close`
- `guest-file-flush`
- `guest-file-open`
- `guest-file-read`
- `guest-file-write`
- `guest-fsfreeze-freeze`
- `guest-fsfreeze-status`
- `guest-fsfreeze-thaw`
- `guest-get-host-name`
- `guest-get-osinfo`
- `guest-get-time`
- `guest-get-timezone`
- `guest-info`
- `guest-network-get-interfaces`
- `guest-ping`
- `guest-set-time`
- `guest-shutdown`
- `guest-sync`
- `guest-sync-delimited`

### guest-network-get-interfaces

Returns RouterOS interface names, MAC addresses, and IP assignments:
```
ether1: 0e:61:47:d8:43:2a  10.0.2.15/24
```
Works immediately after boot. Reports DHCP-assigned addresses.

### guest-exec (input-data mode)

**Works.** The `input-data` field accepts base64-encoded RouterOS script syntax.
Execution is asynchronous — poll `guest-exec-status` with the returned PID.

Test: `:put "qga-test-ok"`
Result: stdout=`qga-test-ok\r\n`, exitcode=0

Confirmed working RouterOS commands via guest-exec:

| Script | Result |
|---|---|
| `:put [/system identity get name]` | `MikroTik` |
| `:put [/system resource get version]` | `7.22 (stable)` |
| `:put [/system resource get uptime]` | `00:06:48` |
| `:put [/system resource get architecture-name]` | `x86_64` |
| `:put [/system resource get cpu-count]` | `2` |
| `:put [/system resource get total-memory]` | `1073741824` |
| `:put [/system resource get free-memory]` | `839286784` |
| `/ip address print terse` | `0 D address=10.0.2.15/24 network=10.0.2.0 ...` |
| `/interface print terse` | ether1 + lo details |
| `:put [/system license get level]` | `free` |
| `:put [/system routerboard get serial-number]` | exit=-1 (CHR has no routerboard) |

### guest-exec (path mode)

**Does NOT work.** Sending `{"path": "/system/script", "arg": ["print"]}` returns
an error. RouterOS only supports the `input-data` field for script execution.

### guest-file-* operations

**Work with caveats on path format.**

#### Path format rules

RouterOS uses its own filesystem model (not Unix paths). Accepted paths:

| Path | Accepted | Notes |
|---|---|---|
| `test-qga.txt` | ✓ | Simple filename in root |
| `./test-qga.txt` | ✓ | Relative with dot |
| `test qga.txt` | ✓ | Spaces OK |
| `qga-test-123.rsc` | ✓ | .rsc extension (RouterOS script) |
| `/tmp/test.txt` | ✗ | Unix absolute paths rejected |
| `/etc/test.txt` | ✗ | Unix system paths rejected |
| `disk1/test-qga.txt` | ✗ | RouterOS disk prefix rejected |
| `flash/test-qga.txt` | ✗ | RouterOS flash prefix rejected |
| `test-dir/test-qga.txt` | ✗ | Subdirectory paths rejected |

**Key insight:** Only flat filenames in the RouterOS root directory work.
No subdirectories, no disk prefixes, no Unix-style paths. Files created
via QGA are visible in RouterOS `/file print`.

#### File roundtrip

Write + read roundtrip works correctly:
- `guest-file-open` returns a handle (integer)
- `guest-file-write` with `buf-b64` (base64) writes data
- `guest-file-read` with `count` reads back correctly
- **Roundtrip verified:** data matches exactly

#### File flush and seek

`guest-file-flush` and `guest-file-seek` return timeouts (empty responses).
These may not be fully implemented — the file data appears to be committed
on `guest-file-close` regardless. Flush/seek are non-critical since
write-then-close works fine.

#### File close behavior

`guest-file-close` returns an empty response (b'') which causes a timeout
in strict response parsing. This is a protocol quirk — the close succeeds
(subsequent reads work) but produces no JSON response body. The test script
handles this gracefully.

#### Script file workflow

**Confirmed working end-to-end:**
1. Write `.rsc` file via `guest-file-write` → `qga-test-script.rsc`
2. Execute via `guest-exec` with `/import qga-test-script.rsc`
3. Output: `executed-via-file-api\r\nScript file loaded and executed successfully`

This enables a powerful pattern: upload RouterOS scripts via QGA file API,
then execute them via `guest-exec /import`.

### guest-fsfreeze-*

**All work:**
- `guest-fsfreeze-freeze` — freezes filesystem (for consistent snapshots)
- `guest-fsfreeze-thaw` — unfreezes filesystem
- `guest-fsfreeze-status` — returns freeze state

### guest-shutdown

**WORKS — DESTRUCTIVE.** Sends a shutdown command that exits the VM.
The QEMU process terminates cleanly. The reference document stated
"No `guest-shutdown`" but RouterOS 7.22 **does** implement it.

After sending `guest-shutdown`, the QEMU process exits within seconds
(confirmed: `/proc/<pid>` disappears, PID file becomes stale).

### guest-ping

**Works.** Returns `{}`. Simple liveness check.

### guest-get-host-name

**Works.** Returns `{"host-name": "MikroTik"}` (default identity).

### guest-get-osinfo

**Works.** Returns:
```json
{
  "id": "routeros",
  "kernel-release": "5.6.3-64",
  "machine": "x86_64",
  "name": "RouterOS",
  "pretty-name": "RouterOS 7.22"
}
```

### guest-get-time

**Works.** Returns nanoseconds since epoch: `1774041353160410000`

### guest-get-timezone

**Works.** Returns `{"offset": 0}` (UTC default).

### Confirmed NOT supported (x86_64)

These commands return `"Command not supported"` or `"command not found"`:

| Command | Error |
|---|---|
| `guest-get-users` | Command not supported |
| `guest-get-memory-blocks` | Command not supported |
| `guest-get-memory-block-info` | Command not supported |
| `guest-get-vcpus` | Command not supported |
| `guest-get-fsinfo` | Command not supported |
| `guest-get-disks` | The command 'guest-get-disks' was not found |

### Not tested (destructive/state-changing)

| Command | Reason not tested |
|---|---|
| `guest-set-user-password` | Would change auth |
| `guest-set-vcpus` | Would change CPU count |
| `guest-set-time` | Would change system clock |
| `guest-suspend-ram` | Would suspend VM |
| `guest-suspend-disk` | Would hibernate VM |
| `guest-suspend-hybrid` | Would suspend VM |
| `guest-fstrim` | Would trim filesystem |

## aarch64 Results — QGA NOT Functional (RouterOS 7.22)

### Observed behavior

- Machine boots fully under TCG (~2-3 min on SteamDeck, ~20s on CI runners)
- RouterOS login prompt appears on serial console
- **virtio-serial-pci device IS present** in QEMU device tree
- **Guest port stays `off`**: `port 1, guest off, host off`
- Compare x86_64: `port 1, guest on, host off`
- All QGA commands time out with empty responses

### Analysis

The virtio-serial PCI device is enumerated by QEMU and visible in `info qtree`.
RouterOS aarch64 boots successfully (kernel 5.6.3, HTTP on port 80 works).
But the guest OS never opens the `org.qemu.guest_agent.0` serial port.

This suggests the **QGA agent binary/service is not present in the aarch64
RouterOS build**, or is not configured to start on that architecture. The
virtio_pci module is loaded (we know this from virtio-blk-pci working for
the disk), so the PCI transport layer is functional — it's specifically the
guest agent daemon that's absent.

This is consistent with RouterOS CHR's history: QGA was originally developed
for x86 hypervisors (KVM/Proxmox/libvirt), and aarch64 CHR is a newer
addition primarily targeting Apple VZ (which uses its own Rosetta/VZ guest
tools, not QGA).

### Implications (7.22)

- **QGA is x86_64-only** in practice for RouterOS 7.22
- If future aarch64 support is needed, MikroTik would need to ship the
  guest agent in the ARM64 build
- Apple VZ has its own "Rosetta" integration path which is separate from QGA
- For aarch64 management, continue using REST API over HTTP or serial console

## aarch64 Retest — MikroTik Development Build (7.23_ab650)

MikroTik provided a custom ARM64 development build (`chr-7.23_ab650-arm64.img`,
built 2026-03-23 10:22:36) for retesting QGA support.  This build was tested
on the same host environment with QEMU 10.2.2.

### Test Environment

- **Host**: macOS x86_64 (Intel)
- **QEMU**: 10.2.2
- **RouterOS**: 7.23_ab650 (development)
- **Machine config**: `virt`, `cortex-a710`, 1024 MiB RAM, 2 CPUs, TCG (cross-arch)
- **UEFI firmware**: edk2-aarch64-code.fd + edk2-arm-vars.fd (both 64 MiB)
- **Disk**: `chr-7.23_ab650-arm64.img` (128 MiB, explicit `virtio-blk-pci`)
- **QGA channel**: `virtio-serial-pci` + `virtserialport` with `org.qemu.guest_agent.0`

### Confirmed working (via REST API)

RouterOS boots successfully, HTTP 200 on WebFig, REST API fully functional:

```
Version:      7.23_ab650 (development)
Architecture: arm64
Board:        CHR QEMU QEMU Virtual Machine
CPU:          ARM64
Build:        2026-03-23 10:22:36
```

### PCI device enumeration

The virtio-serial-pci device **IS present** and recognized by the kernel:

```
0000:00:00.0: QEMU PCIe Host bridge (rev: 0) [Host bridge]
0000:00:01.0: Virtio block device (rev: 0) [SCSI storage controller]
0000:00:02.0: Virtio network device (rev: 0) [Ethernet controller]
0000:00:03.0: Virtio console (rev: 0) [Communication controller]   ← virtio-serial
serial0:  [serial]
```

IRQ assignments confirm the kernel bound the PCI device:
- `virtio2-config` (IRQ 43) — virtio-serial config interrupt
- `virtio2-virtqueues` (IRQ 44, count: 4) — virtio-serial data queues

### QGA result: still NOT functional

Despite the virtio-serial device being present and the PCI driver bound,
the **guest agent daemon still does not run** on this development build.

- QGA socket connected to QEMU chardev successfully
- Sent `guest-sync-delimited` — waited 30 seconds
- **No response** — guest never opened `org.qemu.guest_agent.0`
- Serial console works fine (RouterOS login prompt visible)

The behavior is identical to the 7.22 stable release:
- The virtio-serial PCI device is enumerated and driver-bound
- But no userspace process opens the virtio serial port
- The QGA daemon binary is simply not present or not started in the ARM64 build

### Conclusion

The `7.23_ab650` development build did **not** add QGA support to the
aarch64 RouterOS CHR image.  The behavior is unchanged from 7.22:

| Aspect | 7.22 (stable) | 7.23_ab650 (dev) |
|---|---|---|
| virtio-serial-pci detected | ✅ | ✅ |
| Kernel driver bound (IRQs) | ✅ | ✅ |
| Guest agent port opened | ❌ | ❌ |
| QGA commands respond | ❌ | ❌ |
| HTTP/REST API works | ✅ | ✅ |
| Serial console works | ✅ | ✅ |

The issue remains at the userspace level — the QGA daemon needs to be
compiled for ARM64 and included in the routeros package.  This is a
MikroTik packaging decision, not a kernel or driver issue.

## chr.provision_channel Test (aarch64 7.23_ab650)

MikroTik's CHR documentation mentions a second virtio-serial channel:
`chr.provision_channel` (in addition to the standard `org.qemu.guest_agent.0`).
Hypothesis: maybe the ARM64 build uses the provision channel instead of the
standard QGA channel name.

### Test setup

Launched QEMU with **both** channels on a single `virtio-serial-pci` device:
- `org.qemu.guest_agent.0` → `/tmp/qga-dual-test.sock`
- `chr.provision_channel` → `/tmp/chr-provision-test.sock`

Same image, same QEMU config as the aarch64 retest above.

### Result: NEITHER channel responds

```
org.qemu.guest_agent.0:  NO RESPONSE (connected, sent sync, 15s timeout)
chr.provision_channel:   NO RESPONSE (connected, sent sync, 15s timeout)
```

Both sockets connected to the QEMU chardev (host-side virtio-serial is fine),
but the guest never opened either port.  This confirms:

1. **Not a naming issue** — ARM64 RouterOS doesn't listen on the provision
   channel either
2. **No virtio-serial userspace service at all** on ARM64 — neither the QGA
   service nor the provisioning service is present in the ARM64 build
3. The `chr.provision_channel` is likely another MikroTik-specific service
   (possibly VMware-style provisioning adapted for KVM) that is also
   x86_64-only in the current builds

### MikroTik's own implementation

The QGA in RouterOS is **MikroTik's own implementation**, not stock `qemu-ga`:

- **Version "2.10.50"** — does not match any QEMU release version
- **`guest-exec`** only works via `input-data` (RouterOS script), not `path`
  (standard `qemu-ga` would execute a binary path)
- **`guest-file-open`** only accepts flat filenames (RouterOS filesystem model)
- **`guest-get-osinfo`** returns `"id": "routeros"` — stock `qemu-ga` reads
  `/etc/os-release`
- **`chr.provision_channel`** is entirely MikroTik-specific
- This follows MikroTik's pattern of implementing protocols natively rather
  than bundling third-party tools (same as their TLS implementation)

This means the fix must come from MikroTik — they need to compile and enable
their guest agent service in the ARM64 routeros build.  The kernel/driver
infrastructure is already working on ARM64 (PCI device detected, IRQs bound).

## Command Support Matrix

| Command | x86_64 (7.22) | aarch64 (7.22) | aarch64 (7.23_ab650) | Notes |
|---|---|---|---|---|
| `guest-sync-delimited` | ✅ | ❌ port closed | ❌ port closed | Protocol handshake |
| `guest-sync` | ✅ | ❌ | ❌ | Alternate sync |
| `guest-info` | ✅ | ❌ | ❌ | Lists all commands |
| `guest-ping` | ✅ | ❌ | ❌ | Liveness check |
| `guest-get-host-name` | ✅ | ❌ | ❌ | Returns RouterOS identity |
| `guest-get-osinfo` | ✅ | ❌ | ❌ | OS name, version, kernel, arch |
| `guest-get-time` | ✅ | ❌ | ❌ | Epoch nanoseconds |
| `guest-get-timezone` | ✅ | ❌ | ❌ | UTC offset |
| `guest-set-time` | ✅ (listed) | ❌ | ❌ | Not tested (destructive) |
| `guest-network-get-interfaces` | ✅ | ❌ | ❌ | NIC names, MACs, IPs |
| `guest-exec` (input-data) | ✅ | ❌ | ❌ | RouterOS script execution |
| `guest-exec` (path) | ❌ | ❌ | ❌ | Not implemented |
| `guest-exec-status` | ✅ | ❌ | ❌ | Poll async exec |
| `guest-file-open` | ✅* | ❌ | ❌ | *Flat filenames only |
| `guest-file-write` | ✅ | ❌ | ❌ | base64 data |
| `guest-file-read` | ✅ | ❌ | ❌ | base64 data |
| `guest-file-close` | ✅† | ❌ | ❌ | †Empty response (timeout in strict parsing) |
| `guest-file-flush` | ❓ | ❌ | ❌ | Timeout — may not be implemented |
| `guest-file-seek` | ❓ | ❌ | ❌ | Timeout — may not be implemented |
| `guest-fsfreeze-freeze` | ✅ | ❌ | ❌ | Filesystem quiesce |
| `guest-fsfreeze-thaw` | ✅ | ❌ | ❌ | Unfreeze |
| `guest-fsfreeze-status` | ✅ | ❌ | ❌ | Freeze state |
| `guest-shutdown` | ✅ ⚠️ | ❌ | ❌ | **Destructive** — stops VM |
| `guest-get-users` | ❌ | ❌ | ❌ | Not supported |
| `guest-get-memory-blocks` | ❌ | ❌ | ❌ | Not supported |
| `guest-get-memory-block-info` | ❌ | ❌ | ❌ | Not supported |
| `guest-get-vcpus` | ❌ | ❌ | ❌ | Not supported |
| `guest-get-fsinfo` | ❌ | ❌ | ❌ | Not supported |
| `guest-get-disks` | ❌ | ❌ | ❌ | Command not found |
| `guest-set-user-password` | ❌ (not listed) | ❌ | ❌ | Not in guest-info |
| `guest-suspend-*` | ❌ (not listed) | ❌ | ❌ | Not in guest-info |
| `guest-fstrim` | ❌ (not listed) | ❌ | ❌ | Not in guest-info |
| `guest-suspend-*` | ❌ (not listed) | ❌ | Not in guest-info |
| `guest-fstrim` | ❌ (not listed) | ❌ | Not in guest-info |

## Corrections to Reference Material

The user-provided reference document (based on MikroTik docs) had several
discrepancies vs. actual testing on 7.22:

1. **`guest-shutdown`**: Documented as "not supported" → **Actually works and
   shuts down the VM**
2. **`guest-get-host-name`**: Not mentioned → **Works, returns system identity**
3. **`guest-get-osinfo`**: Not mentioned → **Works, returns full OS info**
4. **`guest-get-time`**: Not mentioned → **Works**
5. **`guest-get-timezone`**: Not mentioned → **Works**
6. **`guest-set-time`**: Not mentioned → **Listed as supported**
7. **`guest-ping`**: Not mentioned → **Works**
8. **`guest-file-seek`**: Documented as supported → **Unclear, times out**
9. **`guest-exec` path field**: Documented as viable → **Does not work**
10. **`guest-file-open` paths**: Not documented → **Flat filenames only
    (no Unix paths, no subdirectories)**

## Use Cases for mikropkl

### Viable via QGA (x86_64 only)

1. **Post-boot configuration**: Upload config scripts via file API, execute
   via `guest-exec /import`
2. **Health monitoring**: `guest-ping` for liveness, `guest-get-osinfo` for
   version verification
3. **Identity/version checking**: `guest-get-host-name`, `guest-get-osinfo`
4. **Network discovery**: `guest-network-get-interfaces` for IP address
   detection (no need to poll HTTP)
5. **Snapshot preparation**: `guest-fsfreeze-freeze` before disk snapshot,
   `guest-fsfreeze-thaw` after
6. **Script execution**: Any RouterOS command via `guest-exec` with
   `input-data` (base64-encoded)
7. **File transfer**: Upload/download files to RouterOS filesystem
8. **Graceful shutdown**: `guest-shutdown` for clean poweroff

### QGA vs REST API vs Serial

| Aspect | QGA | REST API (port 80) | Serial Console |
|---|---|---|---|
| Auth required | No | Yes (admin:) | No (after login prompt) |
| Network needed | No (virtio-serial) | Yes (TCP port forward) | No (chardev socket) |
| Script execution | Yes (input-data) | Limited (/rest endpoints) | Yes (interactive) |
| File transfer | Yes (flat files) | No | No |
| Structured JSON | Yes (all responses) | Yes (/rest/* endpoints) | No (text parsing) |
| Architecture | x86_64 only | Both | Both |
| Boot-time avail. | After boot | After HTTP service up | After boot |
| Overhead | Minimal | HTTP stack | Human-oriented |

**Recommendation**: QGA is most useful for **out-of-band operations** that
don't require network: post-boot config, snapshot quiescing, and graceful
shutdown. For routine monitoring and management, REST API is more portable
(works on both architectures) and more featureful.

## QEMU Device Configuration

### Minimal QGA config for qemu.cfg (INI format)

```ini
[device "virtio-serial-qga"]
  driver = "virtio-serial-pci"

[chardev "qga0"]
  backend = "socket"
  path = "/tmp/qga-MACHINE.sock"
  server = "on"
  wait = "off"

[device "qga-port0"]
  driver = "virtserialport"
  chardev = "qga0"
  name = "org.qemu.guest_agent.0"
```

### QEMU CLI equivalent

```
-device virtio-serial-pci,id=virtio-serial-qga \
-chardev socket,id=qga0,path=/tmp/qga.sock,server=on,wait=off \
-device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0
```

### UTM / config.plist

UTM doesn't expose virtio-serial configuration in the GUI. For UTM QEMU
backend, users would need to add custom QEMU arguments. For Apple VZ backend,
QGA is not relevant (different guest tools model).

## Interaction Example

```python
import json, socket, base64, time

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect("/tmp/qga-chr.x86_64.qemu.7.22.sock")
sock.settimeout(10)

# Sync
sock.sendall(b'{"execute":"guest-sync-delimited","arguments":{"id":1}}\n')
resp = sock.recv(65536).replace(b'\xff', b'')
print(json.loads(resp))  # {"return": 1}

# Get OS info
sock.sendall(b'{"execute":"guest-get-osinfo"}\n')
resp = sock.recv(65536)
info = json.loads(resp)
print(info["return"]["pretty-name"])  # "RouterOS 7.22"

# Execute RouterOS script
script = ':put [/system resource get version]'
encoded = base64.b64encode(script.encode()).decode()
sock.sendall(json.dumps({
    "execute": "guest-exec",
    "arguments": {"input-data": encoded, "capture-output": True}
}).encode() + b'\n')
resp = json.loads(sock.recv(65536))
pid = resp["return"]["pid"]

# Poll for result
time.sleep(1)
sock.sendall(json.dumps({
    "execute": "guest-exec-status",
    "arguments": {"pid": pid}
}).encode() + b'\n')
status = json.loads(sock.recv(65536))
print(base64.b64decode(status["return"]["out-data"]).decode())
# "7.22 (stable)\r\n"

sock.close()
```

## Test Scripts

| Script | Purpose |
|---|---|
| `launch-with-qga.sh` | Wraps existing qemu.sh with QGA channel injection |
| `launch-arm64-qga-test.sh` | Standalone aarch64 QEMU launcher with QGA (for retest) |
| `qga-test.py` | Full QGA test suite — all commands, JSON output |
| `qga-file-test.py` | Detailed file operations and path format testing |
| `arm64-clean-test.py` | aarch64 QGA connection test with boot wait and timeout |
| `test-provision-channel.py` | Tests both `org.qemu.guest_agent.0` and `chr.provision_channel` |
| `stop-qga-test.sh` | Stop a machine launched for QGA testing |
| `shutdown-rest.py` | Graceful RouterOS shutdown via REST API |

### Running tests

```sh
# Stop existing instance (if running)
Machines/chr.x86_64.qemu.7.22.utm/qemu.sh --stop

# Set QGA channel
export QEMU_EXTRA="-device virtio-serial-pci,id=virtio-serial-qga \
  -chardev socket,id=qga0,path=/tmp/qga-chr.x86_64.qemu.7.22.sock,server=on,wait=off \
  -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0,id=qga-port0"

# Launch (use different port to avoid conflict with normal instances)
Machines/chr.x86_64.qemu.7.22.utm/qemu.sh --background --port 9190

# Wait for boot (~10s with KVM, ~30-60s with TCG)
sleep 15

# Run full test suite
python3 Lab/qemu-guest-agent/qga-test.py /tmp/qga-chr.x86_64.qemu.7.22.sock

# Run detailed file tests
python3 Lab/qemu-guest-agent/qga-file-test.py /tmp/qga-chr.x86_64.qemu.7.22.sock

# Run single command
python3 Lab/qemu-guest-agent/qga-test.py /tmp/qga-chr.x86_64.qemu.7.22.sock \
  --command guest-get-osinfo

# Execute RouterOS script
python3 Lab/qemu-guest-agent/qga-test.py /tmp/qga-chr.x86_64.qemu.7.22.sock \
  --exec ':put [/system identity get name]'

# Clean up
unset QEMU_EXTRA
Machines/chr.x86_64.qemu.7.22.utm/qemu.sh --stop
```

## SPICE Agent

UTM is documented as using SPICE for display. The SPICE agent (vdagent) would
handle clipboard sharing, display resolution, and mouse integration. However:

- RouterOS CHR is a **headless network appliance** — it has no GUI, no X11,
  no desktop environment
- SPICE agent features (clipboard, resolution, file drag-drop) are irrelevant
  for a router OS
- UTM's SPICE usage is for the **display rendering** (console viewer), not for
  guest services
- RouterOS does not implement a SPICE agent (vdagent)

The QEMU Guest Agent (virtio-serial) is the only relevant bidirectional
control channel. SPICE is display-layer only for this use case.

## VMware Tools (for reference)

RouterOS also implements VMware Tools natively for ESXi guests. This is a
completely separate code path from QGA, supporting:
- Time synchronization
- Lifecycle scripts (poweron/poweroff/suspend/resume hooks)
- Guest info reporting
- Filesystem quiescing

VMware Tools are irrelevant to QEMU/KVM deployments. Mentioned here only for
completeness since the user noted prior VMware experience.

## CI Workflow

`.github/workflows/qga-test.yaml` ("Test: QEMU Guest Agent") automates QGA
verification against any RouterOS version, on both x86_64 and aarch64 runners.

- **Dispatch inputs**: `rosver` (RouterOS version) and `pklversion`
- **Build job**: builds machine bundles with `make` (same as `qemu-test.yaml`)
- **Test job**: matrix of `ubuntu-latest` (x86_64) and `ubuntu-24.04-arm` (aarch64)
- **Machines tested**: `chr.*.qemu.*` (q35/virt) and `chr.*.apple.*` (pc/virt)
- **No cross-arch**: each runner tests only native-arch machines
- **ROSE variants skipped**: same CHR image, same QGA behavior

The workflow boots each machine with a QGA virtio-serial channel injected via
`QEMU_EXTRA`, waits for HTTP (boot confirmation), then runs the embedded
`qga-verify.py` script which:
1. Syncs with the guest agent
2. Lists supported commands (compares against 7.22 baseline)
3. Tests key commands: ping, hostname, osinfo, time, timezone, network, exec,
   file roundtrip, fsfreeze cycle

**Exit logic**: x86_64 fails if QGA is absent or tests fail; aarch64 passes
regardless (QGA absence is expected, presence is a positive note).

**Locally confirmed**: QGA works identically on q35 (qemu style) and pc (apple
style) — same agent v2.10.50, same 21 commands, all tests pass on both.

## Future Work

1. **Test on older RouterOS versions** — QGA was introduced in 6.42; command
   set may differ between 6.x and 7.x
2. **Test `guest-set-time`** — reportedly supported but not tested (clock change is recoverable)
3. **Test `guest-suspend-*`** — may work for VM pause/resume workflows
4. **Integrate QGA channel into QemuCfg.pkl** — optional `qemuGuestAgent`
   flag in pkl config that adds the virtio-serial device to qemu.cfg
5. **Post-boot automation** — use QGA file+exec pipeline for initial config
   (set identity, add users, configure interfaces)
6. **Monitor aarch64 support** — check if future RouterOS versions enable
   QGA on ARM64
