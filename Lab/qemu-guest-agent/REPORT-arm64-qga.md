# QEMU Guest Agent Not Functional on ARM64 CHR — Test Report

## Issue

The QEMU Guest Agent (QGA) is **not functional on aarch64 CHR** builds.
On x86_64 CHR, the agent works correctly over the standard
`org.qemu.guest_agent.0` virtio-serial channel (21 commands, version 2.10.50).
On aarch64, the virtio-serial PCI device is enumerated and the kernel driver
binds, but **no userspace daemon opens either the `org.qemu.guest_agent.0` or
`chr.provision_channel` port**.

Tested on two builds:
- RouterOS **7.22** (stable) — QGA not functional on aarch64
- RouterOS **7.23_ab650** (development build, 2026-03-23) — QGA **still not functional** on aarch64

## x86_64 — Working (Baseline)

QGA confirmed working on x86_64 CHR 7.22 with the standard channel name.

### QEMU command (x86_64)

```sh
qemu-system-x86_64 -M q35 -m 1024 -smp 2 -accel kvm \
  -drive file=chr-7.22.img,format=raw,if=virtio \
  -netdev user,id=net0,hostfwd=tcp::9190-:80 \
  -device virtio-net-pci,netdev=net0 \
  -display none \
  -chardev socket,id=serial0,path=/tmp/serial.sock,server=on,wait=off \
  -serial chardev:serial0 \
  -device virtio-serial-pci,id=virtio-serial-qga \
  -chardev socket,id=qga0,path=/tmp/qga-test.sock,server=on,wait=off \
  -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0,id=qga-port0
```

### x86_64 QGA verification

Connected to `/tmp/qga-test.sock` and sent:

```json
{"execute":"guest-sync-delimited","arguments":{"id":12345}}
```

Response (immediate):

```json
{"return": 12345}
```

Then:

```json
{"execute":"guest-info"}
```

Response:

```json
{
  "return": {
    "version": "2.10.50",
    "supported_commands": [
      {"name": "guest-exec", "enabled": true, "success-response": true},
      {"name": "guest-exec-status", "enabled": true, "success-response": true},
      {"name": "guest-file-close", "enabled": true, "success-response": true},
      {"name": "guest-file-flush", "enabled": true, "success-response": true},
      {"name": "guest-file-open", "enabled": true, "success-response": true},
      {"name": "guest-file-read", "enabled": true, "success-response": true},
      {"name": "guest-file-write", "enabled": true, "success-response": true},
      {"name": "guest-fsfreeze-freeze", "enabled": true, "success-response": true},
      {"name": "guest-fsfreeze-status", "enabled": true, "success-response": true},
      {"name": "guest-fsfreeze-thaw", "enabled": true, "success-response": true},
      {"name": "guest-get-host-name", "enabled": true, "success-response": true},
      {"name": "guest-get-osinfo", "enabled": true, "success-response": true},
      {"name": "guest-get-time", "enabled": true, "success-response": true},
      {"name": "guest-get-timezone", "enabled": true, "success-response": true},
      {"name": "guest-info", "enabled": true, "success-response": true},
      {"name": "guest-network-get-interfaces", "enabled": true, "success-response": true},
      {"name": "guest-ping", "enabled": true, "success-response": true},
      {"name": "guest-set-time", "enabled": true, "success-response": true},
      {"name": "guest-shutdown", "enabled": true, "success-response": true},
      {"name": "guest-sync", "enabled": true, "success-response": true},
      {"name": "guest-sync-delimited", "enabled": true, "success-response": false}
    ]
  }
}
```

OS info confirms the custom implementation:

```json
{"execute":"guest-get-osinfo"}
→ {"return":{"id":"routeros","kernel-release":"5.6.3-64","machine":"x86_64","name":"RouterOS","pretty-name":"RouterOS 7.22"}}
```

## aarch64 — Not Working

### Test 1: Standard QGA channel (7.22 + 7.23_ab650)

#### QEMU command (aarch64)

```sh
qemu-system-aarch64 \
  -M virt -cpu cortex-a710 -m 1024 -smp 2 \
  -accel tcg,tb-size=256 \
  -drive if=pflash,format=raw,readonly=on,unit=0,file=/usr/local/share/qemu/edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,unit=1,file=/tmp/efi-vars-copy.fd \
  -drive file=chr-7.23_ab650-arm64.img,format=raw,if=none,id=drive1 \
  -device virtio-blk-pci,drive=drive1,bootindex=0 \
  -netdev user,id=net0,hostfwd=tcp::9195-:80 \
  -device virtio-net-pci,netdev=net0 \
  -display none -monitor none \
  -chardev socket,id=serial0,path=/tmp/serial.sock,server=on,wait=off \
  -serial chardev:serial0 \
  -device virtio-serial-pci,id=virtio-serial-qga \
  -chardev socket,id=qga0,path=/tmp/qga-test.sock,server=on,wait=off \
  -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0,id=qga-port0
```

The UEFI vars file is a copy of `edk2-arm-vars.fd` (64 MiB, matching the code ROM).
Disk uses explicit `-device virtio-blk-pci` (not `if=virtio`, which resolves to
MMIO on `virt` — RouterOS lacks the `virtio_mmio` driver).

#### Boot confirmed working

RouterOS boots normally. REST API responds:

```sh
$ curl -sf -u admin: http://127.0.0.1:9195/rest/system/resource
```

```json
{
  "architecture-name": "arm64",
  "board-name": "CHR QEMU QEMU Virtual Machine",
  "build-time": "2026-03-23 10:22:36",
  "cpu": "ARM64",
  "cpu-count": "2",
  "version": "7.23_ab650 (development)"
}
```

#### PCI device enumeration (via REST API)

```sh
$ curl -sf -u admin: http://127.0.0.1:9195/rest/system/resource/hardware
```

```
0000:00:00.0: QEMU PCIe Host bridge (rev: 0) [Host bridge]
0000:00:01.0: Virtio block device (rev: 0) [SCSI storage controller]
0000:00:02.0: Virtio network device (rev: 0) [Ethernet controller]
0000:00:03.0: Virtio console (rev: 0) [Communication controller]   ← virtio-serial
serial0:  [serial]
```

#### IRQ assignments (via REST API)

```sh
$ curl -sf -u admin: http://127.0.0.1:9195/rest/system/resource/irq
```

```
virtio2-config      IRQ 43      (count: 1)
virtio2-virtqueues  IRQ 44      (count: 4)
```

The kernel **has bound** the virtio-serial-pci driver — PCI enumerated, IRQs allocated.

#### QGA test

Connected to `/tmp/qga-test.sock` (host-side QEMU chardev — connection succeeds) and sent:

```json
{"execute":"guest-sync-delimited","arguments":{"id":12345}}
```

**No response after 30 seconds.** The guest never opened the virtio-serial port.
The host-side socket connects to QEMU's chardev backend, but no data comes back
because the guest-side port is `off` — no process has opened `/dev/vportNpN` inside
the guest.

Same result on both 7.22 (stable) and 7.23_ab650 (development).

### Test 2: `chr.provision_channel` (7.23_ab650)

MikroTik's CHR documentation mentions `chr.provision_channel` as an additional
virtio-serial channel. Hypothesis: maybe the ARM64 build uses this channel name
instead of the standard `org.qemu.guest_agent.0`.

#### QEMU command (both channels)

```sh
qemu-system-aarch64 \
  -M virt -cpu cortex-a710 -m 1024 -smp 2 \
  -accel tcg,tb-size=256 \
  -drive if=pflash,format=raw,readonly=on,unit=0,file=/usr/local/share/qemu/edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,unit=1,file=/tmp/efi-vars-copy.fd \
  -drive file=chr-7.23_ab650-arm64.img,format=raw,if=none,id=drive1 \
  -device virtio-blk-pci,drive=drive1,bootindex=0 \
  -netdev user,id=net0,hostfwd=tcp::9198-:80 \
  -device virtio-net-pci,netdev=net0 \
  -display none -monitor none \
  -chardev socket,id=serial0,path=/tmp/serial.sock,server=on,wait=off \
  -serial chardev:serial0 \
  -device virtio-serial-pci,id=virtio-serial0 \
  -chardev socket,id=qga0,path=/tmp/qga-dual-test.sock,server=on,wait=off \
  -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0,id=qga-port0 \
  -chardev socket,id=prov0,path=/tmp/chr-provision-test.sock,server=on,wait=off \
  -device virtserialport,chardev=prov0,name=chr.provision_channel,id=prov-port0
```

Both channels are on a single `virtio-serial-pci` controller with separate Unix
domain sockets on the host.

#### Result

After boot confirmed (HTTP 200), probed each socket with `guest-sync-delimited`:

```
org.qemu.guest_agent.0:  NO RESPONSE (connected, sent sync, 15s timeout)
chr.provision_channel:   NO RESPONSE (connected, sent sync, 15s timeout)
```

**Neither channel responded.** This rules out a naming issue — the ARM64 build has
no virtio-serial userspace service at all.

## Test scripts used

All scripts are in `Lab/qemu-guest-agent/` in the [mikropkl](https://github.com/tikoci/mikropkl) repo:

| Script | Purpose |
|---|---|
| `launch-with-qga.sh` | Wrapper — launches any mikropkl machine with QGA channel injected via `QEMU_EXTRA` |
| `qga-test.py` | Full QGA test suite — sends all documented commands, records results (used for x86_64 testing) |
| `qga-file-test.py` | Extended file operation tests (`guest-file-open/read/write/close/flush`) |
| `test-provision-channel.py` | Launches aarch64 QEMU with **both** `org.qemu.guest_agent.0` and `chr.provision_channel`, probes each |

The Python test scripts connect to the QGA Unix socket and send standard QEMU
Guest Agent JSON-RPC commands. The probe sequence is:

```python
import socket, json, time

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect("/tmp/qga-test.sock")
sock.settimeout(15)

# Standard QGA handshake
msg = json.dumps({"execute": "guest-sync-delimited", "arguments": {"id": 12345}})
sock.sendall((msg + "\n").encode())

# Wait for response
data = sock.recv(4096)  # Timeout after 15s — no data received on aarch64
```

## Summary

| | x86_64 (7.22) | aarch64 (7.22) | aarch64 (7.23_ab650) |
|---|---|---|---|
| RouterOS boots | Yes | Yes | Yes |
| HTTP/REST API works | Yes | Yes | Yes |
| virtio-serial-pci in PCI tree | Yes | Yes | Yes |
| Kernel driver bound (IRQs) | Yes | Yes | Yes |
| `org.qemu.guest_agent.0` responds | **Yes** (21 cmds, v2.10.50) | **No** | **No** |
| `chr.provision_channel` responds | (not tested) | — | **No** |

The kernel and driver infrastructure is working on ARM64 — the issue is entirely
at the userspace/packaging level. The QGA daemon binary needs to be compiled for
ARM64 and included in the ARM64 CHR build.

## Environment details

| | x86_64 test | aarch64 test |
|---|---|---|
| Host OS | Linux x86_64 (SteamDeck) | macOS x86_64 (Intel) |
| QEMU version | 9.2.0 | 10.2.2 |
| Accelerator | KVM (native) | TCG (cross-arch emulation) |
| Machine type | q35 | virt |
| CPU model | (host via KVM) | cortex-a710 |
| Firmware | SeaBIOS (QEMU default) | EDK2 UEFI (pflash) |
| Disk interface | `if=virtio` (virtio-blk-pci on q35) | explicit `-device virtio-blk-pci` |
| QEMU EFI code ROM | N/A | edk2-aarch64-code.fd (64 MiB) |
| QEMU EFI vars | N/A | edk2-arm-vars.fd (64 MiB) |
