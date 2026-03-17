# aarch64 QEMU Boot Investigation — RouterOS CHR ARM64

## Summary

RouterOS CHR ARM64 boots in QEMU (HTTP 200 from WebFig) but always fails
`/system/check-installation` with:

```json
{"detail": "damaged system package: bad image", "error": 400, "message": "Bad Request"}
```

This failure is **reproducible on UTM (macOS)** and is NOT caused by CI configuration.
It is an inherent RouterOS CHR ARM64 limitation in QEMU virtual environments.

---

## Disk Image Analysis

### Image layout (`chr-7.22-arm64.img`, 128 MiB)

Hybrid GPT+MBR disk:
- **MBR**: Two type-0x83 (Linux) entries — "hybrid MBR" that enables legacy boot
- **GPT**:
  - Partition 1: `RouterOS-Boot` — 33 MiB EFI System Partition (GPT type `c12a7328-...`)
  - Partition 2: `RouterOS`      — 92 MiB Linux ext4 root filesystem

### EFI Partition Contents

The EFI SP contains exactly one file:
```
/EFI/BOOT/BOOTAA64.EFI  (11.8 MiB)
```

Critically, **BOOTAA64.EFI is a Linux kernel** (ARM64 EFI stub/Image), not a standard
EFI application:
```
$ file BOOTAA64.EFI
Linux kernel ARM64 boot executable Image, little-endian, 4K pages
```
MZ header at offset 0 (for EFI compatibility), ARM64 PE magic at offset 0x40.

### VDI vs RAW

`chr-7.22-arm64.vdi` and `chr-7.22-arm64.img` have **identical MD5 hash** after
`qemu-img convert`. VDI is a sparse container of the same 128 MiB content.
**Switching to VDI will not change boot behavior.**

---

## Boot Chain

```
UEFI (EDK2/QEMU_EFI.fd or AAVMF_CODE.fd)
  └─> loads EFI/BOOT/BOOTAA64.EFI = Linux kernel (EFI stub)
        └─> RouterOS userspace starts
              └─> RouterOS init tries kexec(BOOTAA64.EFI)  ← FAILS
                    └─> "Invalid 2nd device tree" / "load failed"
                    └─> RouterOS continues booting anyway
              └─> HTTP server starts → WebFig HTTP 200 ✓
              └─> /system/check-installation → HTTP 400 "bad image" ✗
```

---

## Root Cause: kexec Device Tree Mismatch

RouterOS ARM64 init script does a **kexec self-reload** as part of initialization
(common in embedded Linux: reload kernel with correct device tree for updates/checks).

Serial console output during boot:
```
Starting...
kexec: Invalid 2nd device tree.
kexec: load failed.
Cannot load /flash/boot/EFI/BOOT/BOOTAA64.EFI
Starting services...
```

QEMU `virt` machine generates a dynamic device tree:
```
model = "linux,dummy-virt";
compatible = "linux,dummy-virt";
```

RouterOS's kexec provides its own internal DTB (the "2nd device tree") which describes
specific ARM64 hardware. This does NOT match the generic `linux,dummy-virt` QEMU machine,
causing kexec to fail.

**check-installation detects that the kexec/EFI boot path failed and reports "bad image".**

### Why x86_64 passes check-installation

x86_64 Linux does not require a device tree for kexec (DTB is an ARM concept).
RouterOS x86_64 kexec likely does a simple kernel reload without DTB constraints.

### Is this fixable?

Potentially, but complex:
- RouterOS's internal DTB is not exposed/configurable
- QEMU `virt` machine type generates DTBs dynamically
- Would require either RouterOS to ship a QEMU-compatible DTB, or a very specific
  QEMU machine configuration that matches RouterOS's internal DTB expectations
- MikroTik may view this as a valid limitation (CHR ARM64 intended for real ARM HW)

**CI should report this failure** — it's the real status of CHR ARM64 in virtualized env.

---

## UEFI Firmware Notes

### On ubuntu-24.04-arm (native ARM64 runner)

`qemu-efi-aarch64` package provides:
- `/usr/share/qemu-efi-aarch64/QEMU_EFI.fd` — **2 MiB** compact firmware
- `/usr/share/AAVMF/AAVMF_CODE.fd` — **64 MiB** full AAVMF firmware (preferred)
- `/usr/share/AAVMF/AAVMF_VARS.fd` — **64 MiB** AAVMF vars (paired with AAVMF_CODE)

**Use AAVMF_CODE.fd + AAVMF_VARS.fd (matched 64 MiB pair).** The compact 2 MiB
`QEMU_EFI.fd` may not provide enough NVRAM space for UEFI to complete initialization.

### On macOS (Homebrew QEMU)

- `/usr/local/share/qemu/edk2-aarch64-code.fd` — 64 MiB
- `/usr/local/share/qemu/edk2-arm-vars.fd` — 64 MiB (properly paired)

Both 64 MiB; pflash configuration works correctly.

---

## Verified Working QEMU Command (macOS)

```bash
cp /usr/local/share/qemu/edk2-arm-vars.fd /tmp/test-vars.fd
qemu-system-aarch64 \
  -cpu cortex-a710 \
  -M virt \
  -m 1024 \
  -smp 2 \
  -display none \
  -monitor none \
  -chardev socket,id=serial0,path=/tmp/serial.sock,server=on,wait=off \
  -serial chardev:serial0 \
  -drive if=pflash,format=raw,readonly=on,unit=0,file=/usr/local/share/qemu/edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,unit=1,file=/tmp/test-vars.fd \
  -drive file=Lab/qemu-arm64/RAW/chr-7.22-arm64.img,format=raw,if=none,id=drive1 \
  -device virtio-blk-pci,drive=drive1,bootindex=0 \
  -netdev user,id=net0,hostfwd=tcp::9180-:80 \
  -device virtio-net-pci,netdev=net0 \
  -accel tcg,tb-size=256 \
  -daemonize -pidfile /tmp/qemu-chr.pid
```

Results:
- HTTP 200: `curl http://localhost:9180/` ✓
- REST identity: `curl http://admin:@localhost:9180/rest/system/identity` → `{"name":"MikroTik"}` ✓
- check-installation: HTTP 400 "damaged system package: bad image" ✗ (expected)

### CRITICAL: Do NOT use `-nographic`

`-nographic` redirects serial to stdio → **blocks indefinitely** when QEMU is
backgrounded (`&`) with no interactive terminal. QEMU starts (pid created) but
consumes 0% CPU — the process is frozen, not executing any instructions.

Use instead: `-display none -monitor none -chardev socket,... -serial chardev:...`

---

## Lab Scripts

See `boot-test.sh` for a complete local boot test.
