# QEMU Guest Agent (QGA) on MikroTik RouterOS CHR — Investigation Notes

## Summary

RouterOS CHR 7.22 includes a **native QEMU Guest Agent** implementation that works
over the standard `org.qemu.guest_agent.0` virtio-serial channel. It is functional
on **x86_64 only**. On aarch64, the virtio-serial device is present in QEMU but
**RouterOS never opens the guest-side port** — the QGA service does not appear to
run on the aarch64 build.

The agent reports version **2.10.50** and supports **21 commands**, which is
significantly more than some online references suggest. Key capabilities include
script execution (`guest-exec`), file transfer (`guest-file-*`), network interface
enumeration, OS info, hostname, time, timezone, filesystem freeze/thaw, and
shutdown.

## Test Environment

- **Host**: Linux x86_64 (SteamDeck, Zen 2 APU)
- **QEMU**: 9.2.0
- **RouterOS**: 7.22 (stable)
- **x86_64 machine**: `chr.x86_64.qemu.7.22` — q35, KVM, SeaBIOS
- **aarch64 machine**: `chr.aarch64.qemu.7.22` — virt, TCG (cross-arch)

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

## aarch64 Results — QGA NOT Functional

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

### Implications

- **QGA is x86_64-only** in practice for RouterOS 7.22
- If future aarch64 support is needed, MikroTik would need to ship the
  guest agent in the ARM64 build
- Apple VZ has its own "Rosetta" integration path which is separate from QGA
- For aarch64 management, continue using REST API over HTTP or serial console

## Command Support Matrix

| Command | x86_64 | aarch64 | Notes |
|---|---|---|---|
| `guest-sync-delimited` | ✅ | ❌ port closed | Protocol handshake |
| `guest-sync` | ✅ | ❌ | Alternate sync |
| `guest-info` | ✅ | ❌ | Lists all commands |
| `guest-ping` | ✅ | ❌ | Liveness check |
| `guest-get-host-name` | ✅ | ❌ | Returns RouterOS identity |
| `guest-get-osinfo` | ✅ | ❌ | OS name, version, kernel, arch |
| `guest-get-time` | ✅ | ❌ | Epoch nanoseconds |
| `guest-get-timezone` | ✅ | ❌ | UTC offset |
| `guest-set-time` | ✅ (listed) | ❌ | Not tested (destructive) |
| `guest-network-get-interfaces` | ✅ | ❌ | NIC names, MACs, IPs |
| `guest-exec` (input-data) | ✅ | ❌ | RouterOS script execution |
| `guest-exec` (path) | ❌ | ❌ | Not implemented |
| `guest-exec-status` | ✅ | ❌ | Poll async exec |
| `guest-file-open` | ✅* | ❌ | *Flat filenames only |
| `guest-file-write` | ✅ | ❌ | base64 data |
| `guest-file-read` | ✅ | ❌ | base64 data |
| `guest-file-close` | ✅† | ❌ | †Empty response (timeout in strict parsing) |
| `guest-file-flush` | ❓ | ❌ | Timeout — may not be implemented |
| `guest-file-seek` | ❓ | ❌ | Timeout — may not be implemented |
| `guest-fsfreeze-freeze` | ✅ | ❌ | Filesystem quiesce |
| `guest-fsfreeze-thaw` | ✅ | ❌ | Unfreeze |
| `guest-fsfreeze-status` | ✅ | ❌ | Freeze state |
| `guest-shutdown` | ✅ ⚠️ | ❌ | **Destructive** — stops VM |
| `guest-get-users` | ❌ | ❌ | Not supported |
| `guest-get-memory-blocks` | ❌ | ❌ | Not supported |
| `guest-get-memory-block-info` | ❌ | ❌ | Not supported |
| `guest-get-vcpus` | ❌ | ❌ | Not supported |
| `guest-get-fsinfo` | ❌ | ❌ | Not supported |
| `guest-get-disks` | ❌ | ❌ | Command not found |
| `guest-set-user-password` | ❌ (not listed) | ❌ | Not in guest-info |
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
| `qga-test.py` | Full QGA test suite — all commands, JSON output |
| `qga-file-test.py` | Detailed file operations and path format testing |
| `stop-qga-test.sh` | Stop a machine launched for QGA testing |

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
