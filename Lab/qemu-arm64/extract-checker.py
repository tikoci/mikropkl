#!/usr/bin/env python3
"""
extract-checker.py — Extract the RouterOS hardware checker binary from a system NPK.

The system NPK's verification section contains two ELF binaries:
  1. bin/bash  — ARM32 ELF (~29 KB): the hardware checker (NOT real bash)
  2. boot/kernel — ARM64 ELF (~3.5 MB): contains embedded marvell,armada7040 DTB

The checker (bin/bash ARM32) is what RouterOS executes when you call:
  POST /rest/system/check-installation

It scans /ram/ for regular files with magic header 0xbad0f11e LE (bytes: 1e f1 d0 ba).
These capability files are created at boot by RouterOS init from DTB hardware info.
On QEMU virt with empty DTB, no capability files exist → "bad image" error.

Usage:
  # First extract the system NPK from ext4:
  DB=/usr/local/Cellar/e2fsprogs/*/sbin/debugfs
  $DB -R "dump var/pdb/system/image /tmp/system-pkg.npk" /tmp/ros-root.ext4

  # Then extract the checker binary:
  python3 extract-checker.py [/tmp/system-pkg.npk]

Outputs:
  /tmp/npk-bin-bash-arm32.elf  — the ARM32 checker ELF
  /tmp/npk-boot-kernel.elf     — the ARM64 boot/kernel ELF (with embedded Armada7040 DTB)
"""
import struct, sys, subprocess

npk_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/system-pkg.npk'

with open(npk_path, 'rb') as f:
    npk = f.read()

print(f"NPK size: {len(npk):,} bytes ({len(npk)/(1024*1024):.1f} MiB)")

# Find ELF magic bytes 0x7f 'E' 'L' 'F' in the NPK
elf_offsets = []
search_from = 0
while True:
    idx = npk.find(b'\x7fELF', search_from)
    if idx == -1:
        break
    ei_class = npk[idx + 4]   # 1=32-bit, 2=64-bit
    ei_machine = struct.unpack_from('<H', npk, idx + 18)[0]  # 40=ARM32, 183=ARM64
    elf_offsets.append((idx, ei_class, ei_machine))
    search_from = idx + 1

print(f"\nFound {len(elf_offsets)} ELF headers in NPK:")
for off, cls, mach in elf_offsets:
    arch = {(1, 40): 'ARM32', (2, 183): 'ARM64'}.get((cls, mach), f'class={cls} mach={mach}')
    size_hint = ''
    if len(elf_offsets) > 1:
        next_elf = next((o for o, _, _ in elf_offsets if o > off), len(npk))
        size_hint = f' (~{next_elf - off:,} bytes to next ELF)'
    print(f"  0x{off:x}: {arch}{size_hint}")

if len(elf_offsets) < 2:
    print("Expected at least 2 ELF binaries (ARM32 checker + ARM64 boot/kernel). Check NPK.")
    sys.exit(1)

# Extract each ELF
for i, (off, cls, mach) in enumerate(elf_offsets):
    end = elf_offsets[i + 1][0] if i + 1 < len(elf_offsets) else len(npk)
    arch = {(1, 40): 'ARM32', (2, 183): 'ARM64'}.get((cls, mach), 'unknown')
    data = npk[off:end]

    if cls == 1 and mach == 40:  # ARM32 = checker binary
        out = '/tmp/npk-bin-bash-arm32.elf'
        label = 'ARM32 checker (bin/bash — NOT real bash)'
    elif cls == 2 and mach == 183:  # ARM64 = boot/kernel
        out = '/tmp/npk-boot-kernel.elf'
        label = 'ARM64 boot/kernel (contains marvell,armada7040 DTB + XZ kernel)'
    else:
        out = f'/tmp/npk-elf-{i}.bin'
        label = f'unknown ({arch})'

    with open(out, 'wb') as f:
        f.write(data)
    print(f"\nExtracted [{label}]")
    print(f"  Source offset: 0x{off:x}, size: {len(data):,} bytes")
    print(f"  Output: {out}")

print("\n\nKey strings in ARM32 checker binary:")
arm32_path = '/tmp/npk-bin-bash-arm32.elf'
result = subprocess.run(['strings', '-n', '6', arm32_path], capture_output=True, text=True)
interesting = [s for s in result.stdout.splitlines()
               if any(k in s for k in ['/ram', '/var/pckg', 'installed', '/boot', 'rootfs', '/dev/null'])]
for s in interesting:
    print(f"  {s!r}")

print("""
ANALYSIS SUMMARY:
  The checker (ARM32 bin/bash) at main() 0x1040c calls check_function("/ram"):
    - Opens /ram as directory (O_RDONLY|O_DIRECTORY, flags=0x84000)
    - getdents64() to enumerate entries (ARM32 syscall #217)
    - For each regular file: reads first 4 bytes
    - Checks magic 0xbad0f11e (bytes: 1e f1 d0 ba)
    - If found: proceeds to kexec boot/kernel ELF (success)
    - If none found: returns "damaged system package: bad image"

  On QEMU virt with acpi=on: empty DTB → no /ram/ capability files → FAIL
  On QEMU virt with acpi=off: DTB present but no pci-host-ecam-generic driver → disk not found → FAIL
  On real Armada7040 hardware: DTB parsed → /ram/ populated with 0xbad0f11e files → PASS

  To disassemble the checker:
    /usr/local/opt/llvm/bin/llvm-objdump -d --arch-name=arm /tmp/npk-bin-bash-arm32.elf
""")
