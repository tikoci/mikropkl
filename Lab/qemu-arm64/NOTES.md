# aarch64 QEMU Boot Investigation — RouterOS CHR ARM64

## Summary

RouterOS CHR ARM64 boots in QEMU (HTTP 200 from WebFig) but always fails
`/system/check-installation` with:

```json
{"detail": "damaged system package: bad image", "error": 400, "message": "Bad Request"}
```

This failure is **reproducible on UTM (macOS) and QEMU (Linux CI)** and is NOT caused
by CI configuration. It is an inherent RouterOS CHR ARM64 limitation in QEMU virtual
environments.

**Root cause (confirmed via x86/ARM binary comparison):** The ARM32 checker binary
(`bin/bash` from the system NPK) has stricter verification logic than the x86 checker.
When `/ram/` exists but contains no capability files (magic `0xbad0f11e`), the ARM
checker returns a non-zero exit code, which RouterOS reports as "damaged system package:
bad image." The x86 checker always succeeds — it has `/bin/milo` as a fallback that
runs unconditionally. The ARM checker lacks this fallback.

On QEMU with `acpi=on`, the EFI stub generates an empty DTB → RouterOS init creates
`/ram/` (tmpfs) but has no hardware info to populate capability files → ARM checker
finds empty `/ram/` → failure.

**Bottom line — this cannot be fixed with QEMU flag tuning alone. Requires either:**
1. MikroTik aligning the ARM checker binary's behavior with x86 (always succeed for CHR)
2. A QEMU machine that RouterOS's `Marvell Armada7040` drivers can drive (does not exist)
3. Or MikroTik shipping a QEMU-compatible capability-file generator for CHR ARM64

**CPU model does NOT matter** — tested: cortex-a53, cortex-a72, neoverse-n1 all fail identically.

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

## Root Cause: Deep Analysis

### Phase 1 — Serial Console (full boot trace)

Complete serial console output during boot (captured with `-serial file:`):
```
UEFI firmware (version edk2-stable202408-prebuilt.qemu.org ...)
ArmTrngLib could not be correctly initialized.
Error: Image at 0007FDB6000 start failed: 00000001
Error: Image at 0007FD6D000 start failed: Not Found
...
Image type X64 can't be loaded on AARCH64 UEFI system.
BdsDxe: loading Boot0001 "UEFI Misc Device" from PciRoot(0x0)/Pci(0x1,0x0)
BdsDxe: starting Boot0001 "UEFI Misc Device" from PciRoot(0x0)/Pci(0x1,0x0)
EFI stub: Booting Linux Kernel...
EFI stub: Generating empty DTB          ← KEY: no hardware DTB available
EFI stub: Exiting boot services and installing virtual address map...
Starting...
kexec: Error: No device tree available.  ← kexec needs DTB, finds none
kexec: load failed.
Cannot load /flash/boot/EFI/BOOT/BOOTAA64.EFI
Starting services...                     ← Falls back to direct service start
MikroTik 7.22 (stable)
MikroTik Login:
```

QEMU `virt` machine generates:
```
model = "linux,dummy-virt";
compatible = "linux,dummy-virt";
```

RouterOS kexec carries its own internal DTB (embedded in `boot/kernel` ELF in the system
NPK) for `marvell,armada7040` — this does NOT match the QEMU virt machine, so kexec fails.

### Phase 2 — Binary Reverse Engineering (the real mechanism)

**check-installation endpoint (REST API POST)** triggers `/bin/bash` from the NPK
verification section. This is NOT real bash — it is a RouterOS-specific **hardware checker
binary** (ARM32 ELF, 29,619 bytes, runs in ARM64's AArch32 compatibility mode).

**Note:** The error string "damaged system package: bad image" comes from **RouterOS
itself**, not from the checker binary. Neither the ARM nor x86 checker contains this
text. RouterOS interprets the checker's non-zero exit code as the error.

#### What `bin/bash` (ARM checker) does — disassembly summary

`main()` at `0x1040c` calls `check_function(ptr_to_"/ram")`:

```
check_function(0x153cc):         ; arg includes "/ram", "/var/pckg/", "installed first stage"
  open("/ram", O_RDONLY|O_DIRECTORY)     ; 0x84000 flags
  if open fails:
    → print "installed first stage" → return 0 (SUCCESS)
  loop: getdents64(fd, buf, 2048)        ; ARM32 syscall #217
    for each directory entry in /ram/:
      stat(entry)
      if not S_IFREG: skip
      open("/ram/<entry>")
      read(fd, buf, 4)
      if buf[0..3] == { 0x1e, 0xf1, 0xd0, 0xba }:  ; magic = 0xbad0f11e LE
        → copy capability file to /var/pckg/ → mark success
      else: skip
  if no magic files found:
    → return non-zero → RouterOS reports "damaged system package: bad image"
```

**Magic bytes `0x1e 0xf1 0xd0 0xba`** (= uint32_t `0xbad0f11e` little-endian) are a
RouterOS proprietary header used by hardware capability files. These files are created in
`/ram/` by RouterOS init at boot based on DTB hardware info.

**Note on magic comparison:** The magic is compared byte-by-byte at `0x10500`–`0x1052c`,
NOT stored as a 32-bit constant in .rodata. Each byte is `ldrb` + `cmp` separately:
`0x1e`, `0xf1` (as -0xf = 0xf1), `0xd0` (as -0x30), `0xba` (as -0x46).

#### x86 checker binary — critical difference

The x86 checker (`bin/bash` from x86_64 CHR NPK, 16,972 bytes, 32-bit x86 ELF) has
**fundamentally different logic**:

```
x86 check_function:
  open("/ram", O_RDONLY|O_DIRECTORY)
  if open fails:
    → fall through to exec /bin/milo → return 0 (SUCCESS)
  loop: scan /ram/ for magic files
    if found: copy to /var/pckg/
  → fall through to exec /bin/milo → return 0 (SUCCESS)  ← ALWAYS succeeds!
```

**The x86 checker has NO failure path.** After scanning `/ram/` (whether it exists or
not, whether magic files are found or not), it always execs `/bin/milo` and returns
success.

**String comparison:**

| String | ARM checker | x86 checker |
|--------|:-----------:|:-----------:|
| `/ram/syscap/` | ✅ 0x153bc | ✅ 0x804b000 |
| `/ram` | ✅ 0x153cc | ✅ 0x804b00d |
| `/var/pckg/` | ✅ 0x153d4 | ✅ 0x804b012 |
| `/bin/milo` | ❌ MISSING | ✅ 0x804b01d |
| `installed first stage` | ✅ 0x153e0 | ✅ 0x804b027 |
| binary size | 29,619 bytes | 16,972 bytes |

The ARM checker is almost twice the size of x86, with the extra code implementing the
strict verification path that produces the failure. The x86 checker's `/bin/milo`
fallback makes it always succeed.

#### What populates `/ram/` on real hardware

RouterOS init parses the DTB and creates capability/hardware-descriptor files in `/ram/`
with the magic header `0xbad0f11e`. On real Marvell Armada7040 hardware (or compatible
DTB), these files exist. On QEMU `virt` with `acpi=on` (default), RouterOS kernel generates
an **empty DTB** (EDK2 reports: _"EFI stub: Generating empty DTB"_), so init has no
hardware info → `/ram/` has no capability files → checker finds no magic → fails.

### Phase 3 — Why `acpi=off` doesn't help either

Testing with `-machine virt,acpi=off`:
- EDK2 reports: _"EFI stub: Using DTB from configuration table"_ ← DTB found!
- But RouterOS then reports: _"ERROR: could not find disk!"_
- **Root cause**: RouterOS's kernel lacks the `pci-host-ecam-generic` driver (confirmed:
  string not present in BOOTAA64.EFI). Without DTB-based generic PCIe, RouterOS cannot
  find the `virtio-blk-pci` disk on the QEMU virt PCIe bus.
- RouterOS only supports PCIe via ACPI (for x86/QEMU) or native Marvell PCIe (for ARM64 HW)

#### MMIO transport also fails with acpi=off

Tested with `-device virtio-blk-device` and `-device virtio-net-device` (MMIO transport)
instead of PCI, combined with `acpi=off`:
- EFI stub reports: _"Using DTB from configuration table"_ ← DTB found
- Kernel exits boot services successfully
- But then **stalls completely** — no serial output after "Exiting boot services"
- RouterOS kernel lacks `virtio-mmio` driver (confirmed: not present in BOOTAA64.EFI)

**This creates an unresolvable dilemma:**
- `acpi=on` → disk works via ACPI-discovered PCI, but DTB empty → no `/ram/` capability files → check fails
- `acpi=off` + PCI → DTB present, but no `pci-host-ecam-generic` → disk not found
- `acpi=off` + MMIO → DTB present, but no `virtio-mmio` driver → kernel stalls

### Phase 4 — RouterOS kernel capabilities (confirmed)

From binary analysis of BOOTAA64.EFI (11.8 MiB, Linux kernel 5.6.3):

| Feature | Present? | Notes |
|---|---|---|
| `marvell,armada7040` | ✅ Yes | Compiled for Armada7040 platform |
| `pci-host-ecam-generic` | ❌ No | No DTB-based generic PCIe |
| `virtio_pci` | ✅ Yes | ACPI-based virtio (QEMU default) |
| `virtio_mmio` | ❌ No | No MMIO virtio |
| AArch32 compat | ✅ Yes | Can run ARM32 `bin/bash` checker |
| kexec / kexec_file | ✅ Yes | kexec_file_load present |

### Phase 5 — CPU model doesn't matter

Tested CPUs (all fail identically):
- `cortex-a53` — boot OK, check-installation: "bad image"
- `cortex-a72` — boot OK (faster), check-installation: "bad image"  
  (Armada7040 uses Cortex-A72; `MIDR_EL1` is NOT what the check reads)
- `neoverse-n1` — boot OK, check-installation: "bad image" (expected)

The check reads `/ram/` files with magic `0xbad0f11e`, not CPU registers.

### Why x86_64 passes check-installation

The x86_64 checker binary (`bin/bash` from x86 system NPK) has **fundamentally different
logic**: it always succeeds regardless of `/ram/` state. After scanning `/ram/` for
capability files (same magic `0xbad0f11e`), the x86 checker unconditionally falls through
to executing `/bin/milo` and returns success.

The ARM32 checker binary lacks the `/bin/milo` fallback. When `/ram/` exists but contains
no capability files, it returns non-zero, causing RouterOS to report "bad image."

This is a MikroTik design decision (possibly related to ARM hardware licensing verification)
and unrelated to ACPI vs DTB. Both architectures scan `/ram/` the same way; only the
failure handling differs.

### Additional approaches tested (all negative)

| Approach | Result | Why it failed |
|---|---|---|
| SMBIOS injection (`-smbios type=1,manufacturer=MikroTik`) | board-name changed but check still fails | Checker reads `/ram/` files, not SMBIOS |
| Custom DTB with Marvell compatible strings (`-dtb`) | Kernel ignores DTB when ACPI present | "EFI stub: Generating empty DTB" still emitted |
| qcow2 format instead of raw | No difference | Disk format irrelevant to capability files |
| Different CPU models (cortex-a53/72, neoverse-n1) | All fail identically | Checker doesn't read CPU registers |

### Is this fixable?

**No, not with standard QEMU `virt` machine and RouterOS CHR ARM64 as shipped.**

The most realistic fix paths:
1. **MikroTik aligns ARM checker with x86** — make the ARM `bin/bash` checker always
   succeed for CHR, like the x86 version does (add `/bin/milo` fallback or similar)
2. **MikroTik adds `pci-host-ecam-generic` driver** — would allow `acpi=off` + real DTB
3. **QEMU adds Marvell Armada7040 machine type** — extremely unlikely/impractical

**CI should treat ARM64 check-installation as an expected failure**, testing only HTTP 200
as the health check for ARM64 machines.

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

## Lab Scripts and Tools

### Test scripts in `Lab/qemu-arm64/`

- `boot-test.sh` — complete local boot test
- `cpu-test.sh` — multi-CPU test loop (cortex-a53, a72, etc.)
- `single-cpu-test.sh` — single CPU model test with port argument
- `patch-dtb.py` — DTB patcher (experimental, not proved helpful)

### Important files extracted to `/tmp/` during investigation

These are NOT committed (disk images/blobs are gitignored), re-extract as needed:

| File | Description | How to recreate |
|---|---|---|
| `/tmp/system-pkg.npk` | System NPK (13.7 MiB) from ext4 partition | `debugfs -R "dump var/pdb/system/image /tmp/system-pkg.npk" /tmp/ros-root.ext4` |
| `/tmp/npk-bin-bash-arm32.elf` | ARM32 checker binary (29,619 bytes) | Run `python3 Lab/qemu-arm64/extract-bash.py` |
| `/tmp/virt-qemu.dtb` | QEMU virt machine DTB dump | `qemu-system-aarch64 -machine virt,dumpdtb=/tmp/virt-qemu.dtb -cpu cortex-a53 -m 256` |
| `/tmp/ros-squash-root/` | RouterOS squashfs extracted | `unsquashfs -d /tmp/ros-squash-root /tmp/ros-system.image` |
| `/tmp/ros-root.ext4` | Ext4 second partition (92 MiB) | `dd if=chr-7.22-arm64.img bs=512 skip=68608 of=/tmp/ros-root.ext4` |
| `/tmp/ros-efi/EFI/BOOT/BOOTAA64.EFI` | RouterOS kernel (11.8 MiB) | Mount EFI partition (offset 2048 * 512) |
| `/tmp/x86-chr/chr-7.22.img` | x86_64 CHR image (128 MiB) | `wget https://download.mikrotik.com/routeros/7.22/chr-7.22.img.zip` |
| `/tmp/x86-chr/x86-checker.elf` | x86 checker binary (16,972 bytes) | Extracted from x86 system NPK at offset 0x057d303a in ext4 |

### Analysis scripts in `/tmp/` (recreate from disassembly notes above)

| Script | Purpose |
|---|---|
| `extract-bash.py` | Extracts ARM32 `bin/bash` from NPK verification section |
| `analyze-bash-elf.py` | Maps ELF virtual addresses, finds string locations |
| `analyze-check-arg.py` | Dumps bytes at key addresses in checker binary |
| `disasm-main.py` | Disassembly analysis of main() and key functions |

### Disassembly tools used

```bash
# ARM32 disassembly (LLVM must be installed: brew install llvm)
/usr/local/opt/llvm/bin/llvm-objdump -d --arch-name=arm /tmp/npk-bin-bash-arm32.elf

# DTB decompile (requires dtc: brew install dtc)
dtc -I dtb -O dts /tmp/virt-qemu.dtb

# Debugfs (requires e2fsprogs: brew install e2fsprogs)
/usr/local/Cellar/e2fsprogs/*/sbin/debugfs -R "ls var/pdb/system" /tmp/ros-root.ext4
```
