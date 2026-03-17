# x86 Direct Kernel Boot Investigation

**Goal:** Determine if RouterOS CHR x86_64 can boot via QEMU `-kernel` (direct
kernel load) instead of firmware (SeaBIOS or UEFI), and document how the existing
boot paths work.

**Status:** Concluded — direct kernel boot is not viable.  MikroTik's kernel
requires firmware services during early boot.  Both SeaBIOS and UEFI paths work.

## Background

The question arose from the aarch64 `check-installation` investigation.  On ARM64,
UEFI generates an empty DTB which causes the capability-file checker to fail.
Skipping UEFI entirely with `-kernel` was explored as a potential workaround.  The
x86 side was tested first since it's simpler (no DTB complications).

Apple Virtualization.framework on Intel uses UEFI internally and requires a proper
FAT EFI system partition — this is handled by `tikoci/fat-chr` which reformats the
MikroTik image.

## Key Findings

### 1. MikroTik's EFI partition is NOT standard FAT

The CHR image's GPT partition 1 ("RouterOS Boot", 32 MiB) has a boot-sector JMP
(`eb 66`) and `0xaa55` signature, but **no FAT BPB** — the OEM name, bytes/sector,
sectors/cluster fields are all zero. This is a proprietary boot partition layout.

- `mdir` and `mtools` cannot read it
- OVMF/UEFI cannot find a filesystem on it → drops to EFI shell
- The kernel (bzImage) is stored at a raw offset (0x80000) within this partition

### 2. x86 CHR boots via SeaBIOS (legacy BIOS), not UEFI

UTM's `config.plist` for `chr.x86_64.qemu` has **`UEFIBoot: false`** — it uses
QEMU's default SeaBIOS firmware.  MikroTik's MBR + custom boot-sector chain loads
the kernel from the proprietary partition layout.

### 3. fat-chr creates a proper FAT16 EFI partition

The `tikoci/fat-chr` tool:
- Extracts the kernel from the raw offset in the boot partition
- Creates a standard FAT16 filesystem (`mkfs.fat` OEM signature)
- Places the kernel as `EFI/BOOT/BOOTX64.EFI`
- Includes a `map` file (sector-number mapping table, 60 KiB)
- Preserves the ext4 root partition (partition 2) unchanged

This reformatted image boots via OVMF UEFI and Apple Virtualization.framework.

### 4. The kernel IS the EFI binary (EFI stub)

`BOOTX64.EFI` and the bzImage are identical — the Linux kernel is built as an EFI
stub (PE/COFF executable with a standard bzImage header).

```
file: Linux kernel x86 boot executable bzImage, version 5.6.3-64
size: 4,020,448 bytes (3.8 MiB)
PE sections: .setup (13280B), .reloc (32B), .text (4006624B), .bss (22MB virtual)
XLF flags: KERNEL_64, CAN_BE_LOADED_ABOVE_4G, EFI_HANDOVER_32, EFI_HANDOVER_64, EFI_KEXEC
```

### 5. Direct kernel boot does NOT work

| Method | Result | Serial output |
|---|---|---|
| `-kernel bzImage` (no firmware) | Hangs after real-mode setup | `early console in setup code` then silence |
| `-kernel bzImage` + `console=ttyS0 root=/dev/vda2` | Same hang | Same |
| `-kernel` + OVMF (EFI handover) | Crash `#UD Invalid Opcode` | OVMF hits compressed data at entry point |
| `-kernel` + OVMF + `-cpu max` | Same crash | Same offset (0x3B00C0 from image base) |

**Root cause:** The kernel's 16-bit real-mode setup code depends on BIOS INT services
that aren't present when QEMU loads via the Linux boot protocol.  The EFI handover
entry point (offset 0x190) lands in compressed kernel data, not executable code —
the EFI handover protocol as implemented by QEMU/OVMF doesn't match what this
kernel expects.

### 6. Working boot paths

| Path | Firmware | Image | check-installation |
|---|---|---|---|
| SeaBIOS (default) | QEMU SeaBIOS | `chr-7.22.img` (original) | **"installation is ok"** |
| OVMF UEFI | `edk2-x86_64-code.fd` | `chr-efi.img` (fat-chr) | **"installation is ok"** |
| Apple VZ (Intel) | Built-in UEFI | `chr-efi.img` (fat-chr) | Not tested here |

## Kernel Analysis Details

### bzImage header
```
Setup sectors: 26 (13,824 bytes)
Protocol version: 0x020f
Syssize: 0x3d22e = 4,006,624 bytes (3.8 MiB)
Payload: XZ compressed, 3.7 MiB
Decompressor: only 940 bytes
No embedded command line, no initrd
```

### Strings in uncompressed portion
Present: `earlyprintk`, `ttyS`, `uart`
Missing: `console=`, `EFI stub`, `Kernel panic`, `root=`, `VFS: Cannot open root`

These strings are all in the compressed kernel proper — the uncompressed setup code
and decompressor are minimal.

## Relevance to aarch64

On ARM64, the kernel is `BOOTAA64.EFI` — also an EFI stub (ARM64 Image format with
PE/COFF headers, 11.8 MiB).  QEMU's `-kernel` with ARM64 Image format works
differently from x86 — QEMU loads it at a fixed address and enters in 64-bit mode
(no 16-bit real mode), so the hang issue wouldn't apply.  However, the ARM64 EFI
stub still expects EFI boot services (memory map, runtime services, etc.), and
without them the kernel would crash early.

Apple Virtualization.framework's `VZLinuxBootLoader` takes a kernel path and passes
it through their own boot protocol — this is designed for standard Linux kernels
with initramfs, not MikroTik's firmware-dependent boot chain.

## Conclusion

RouterOS CHR's kernel is tightly coupled to firmware boot services.  There is no
viable path to skip UEFI/BIOS on either architecture:

- **x86_64:** SeaBIOS works perfectly and is the simplest path. OVMF + fat-chr also
  works and is required for Apple Virtualization.framework.
- **aarch64:** Must use UEFI (EDK2 firmware).  The empty-DTB → capability-file issue
  from aarch64/NOTES.md is inherent to the ARM checker binary and cannot be solved by
  boot method changes.
- **`VZLinuxBootLoader`:** Not suitable — RouterOS has no initramfs and the kernel
  requires EFI boot services.

## Files

| File | Purpose |
|---|---|
| `NOTES.md` | This document |
| `boot-tests.sh` | Script to reproduce all tested configurations |
