# x86_64 Cross-Architecture Boot on ARM64 — Investigation Notes

## Problem

x86_64 QEMU machines (SeaBIOS) fail to boot within 300s when running
under TCG on an ARM64 host.  Zero serial output, ~199% CPU, QEMU debug
logs empty.  SeaBIOS never prints its banner — stuck in early real-mode
initialization.

## Root Cause

SeaBIOS starts in 16-bit real mode and uses x86 I/O port instructions
(`in`/`out`) extensively during PCIe enumeration and device probing.
ARM64 has no hardware equivalent for I/O ports — every port access
requires TCG to emulate the full x86 I/O port address space via software.
The overhead multiplier is estimated 20–50x compared to native execution.

The reverse direction (aarch64 on x86_64) works fine (~20s) because
EDK2/UEFI starts in 64-bit mode with MMIO, which x86 TCG handles
efficiently.

## Attempted Mitigations (all insufficient)

| Config | Native x86_64 TCG | Cross-arch ARM64→x86 |
|--------|-------------------|----------------------|
| q35 baseline | ~28s | >300s (timeout) |
| pc + -nodefaults | ~28s | >300s (timeout) |
| pc + -nodefaults + 1 CPU | ~28s | untested |
| tb-size=512 | ~21s | untested on ARM |
| one-insn-per-tb | timeout | N/A |

Conclusion: `pc` + `-nodefaults` don't measurably help — the bottleneck
is the fundamental cost of I/O port emulation, not PCIe topology or
device count.

## Solution: OVMF + fat-chr image

OVMF (x86_64 UEFI firmware) starts in 64-bit protected mode with MMIO,
completely bypassing SeaBIOS's 16-bit real-mode I/O port storm.

The standard MikroTik CHR x86_64 image has a proprietary boot partition
that OVMF cannot read.  The `tikoci/fat-chr` reformatted image
(`chr-efi.img`) has a proper FAT16 EFI partition with
`EFI/BOOT/BOOTX64.EFI` — OVMF loads this successfully.

### Test result (macOS Intel, native TCG)

```
OVMF + fat-chr (q35, virtio): HTTP OK in ~5s (HVF), ~25s (TCG)
```

### Implementation

Rather than modifying the `.qemu.` machines (which must match their
config.plist / UTM spec including SeaBIOS), an `qemu.cfg` + `qemu.sh`
pair is generated for the `chr.x86_64.apple` machine:

- `qemu.cfg`: q35 machine, `if=virtio` drive referencing `chr-efi.img`
- `qemu.sh`: OVMF pflash (edk2-x86_64-code.fd + edk2-i386-vars.fd)
- No cross-arch workaround needed (OVMF is 64-bit from the start)

The apple machine already downloads the fat-chr image.  Adding qemu.cfg
+ qemu.sh means the CI test workflow automatically picks it up.

### OVMF firmware paths

| Platform | Code ROM | Vars |
|----------|----------|------|
| macOS Homebrew (Intel) | `/usr/local/share/qemu/edk2-x86_64-code.fd` | `edk2-i386-vars.fd` |
| macOS Homebrew (ARM) | `/opt/homebrew/share/qemu/edk2-x86_64-code.fd` | `edk2-i386-vars.fd` |
| Ubuntu (ovmf package) | `/usr/share/OVMF/OVMF_CODE.fd` | `OVMF_VARS.fd` |

## Test Scripts

- `boot-test.sh` — single config boot test (pc + nodefaults + TCG)
- `compare-configs.sh` — comparative timing of 7 QEMU configurations
- `test-ovmf.sh` — OVMF with standard CHR image (fails: proprietary boot)
- `test-ovmf-fatchr.sh` — OVMF with fat-chr image (succeeds)
