#!/usr/bin/env python3
"""Detailed trace of checker binary control flow around syscalls"""
import struct

with open('/tmp/npk-bin-bash-arm32.elf', 'rb') as f:
    elf_data = f.read()

e_phoff = struct.unpack_from('<I', elf_data, 28)[0]
e_phnum = struct.unpack_from('<H', elf_data, 44)[0]
e_phentsize = struct.unpack_from('<H', elf_data, 42)[0]
e_entry = struct.unpack_from('<I', elf_data, 24)[0]

segments = []
for i in range(e_phnum):
    offset = e_phoff + i * e_phentsize
    p_type = struct.unpack_from('<I', elf_data, offset)[0]
    p_offset = struct.unpack_from('<I', elf_data, offset + 4)[0]
    p_vaddr = struct.unpack_from('<I', elf_data, offset + 8)[0]
    p_filesz = struct.unpack_from('<I', elf_data, offset + 16)[0]
    p_memsz = struct.unpack_from('<I', elf_data, offset + 20)[0]
    if p_type == 1:
        segments.append((p_vaddr, p_offset, p_filesz, p_memsz))

def vaddr_to_offset(vaddr):
    for seg_vaddr, seg_offset, seg_filesz, seg_memsz in segments:
        if seg_vaddr <= vaddr < seg_vaddr + seg_memsz:
            return vaddr - seg_vaddr + seg_offset
    return None

def read_bytes(vaddr, n):
    off = vaddr_to_offset(vaddr)
    if off is None:
        return None
    return elf_data[off:off+n]

def read_cstring(vaddr):
    off = vaddr_to_offset(vaddr)
    if off is None:
        return f"<invalid 0x{vaddr:x}>"
    end = elf_data.find(b'\x00', off)
    if end == -1 or end - off > 200:
        return f"<long>"
    return elf_data[off:end].decode('latin-1', errors='replace')

# Parse key data addresses from the rodata section
# The main function at 0x1040c loads addresses from PC-relative pools
# Let me find all LDR from PC-relative addresses in the main section

print("=== Disassembly around syscall sites ===\n")

import subprocess
result = subprocess.run(
    ['/usr/local/opt/llvm/bin/llvm-objdump', '-d', '--arch-name=arm',
     '/tmp/npk-bin-bash-arm32.elf'],
    capture_output=True, text=True
)
lines = result.stdout.split('\n')

# Find the main function - entry calls __libc_start_main which calls main
# Entry is 0x10128, which eventually calls the real main
# Let me look at the disassembly from the entry point

# First, let me find all function calls (bl instructions) from the 0x10400-10600 range
# which is likely the main check function
print("=== Main check function (0x10400 - 0x10600) ===")
for line in lines:
    stripped = line.strip()
    # Look for addresses in range
    if stripped and ':' in stripped:
        try:
            addr_str = stripped.split(':')[0].strip()
            addr = int(addr_str, 16)
            if 0x10400 <= addr <= 0x10600:
                print(stripped)
        except ValueError:
            continue

print("\n=== Mount area (around 0x10a30) ===")
for line in lines:
    stripped = line.strip()
    if stripped and ':' in stripped:
        try:
            addr_str = stripped.split(':')[0].strip()
            addr = int(addr_str, 16)
            if 0x10a00 <= addr <= 0x10a60:
                print(stripped)
        except ValueError:
            continue

print("\n=== Umount area (around 0x10a48) ===")
for line in lines:
    stripped = line.strip()
    if stripped and ':' in stripped:
        try:
            addr_str = stripped.split(':')[0].strip()
            addr = int(addr_str, 16)
            if 0x10a38 <= addr <= 0x10a60:
                print(stripped)
        except ValueError:
            continue

print("\n=== Open file area (around 0x10854) ===")
for line in lines:
    stripped = line.strip()
    if stripped and ':' in stripped:
        try:
            addr_str = stripped.split(':')[0].strip()
            addr = int(addr_str, 16)
            if 0x10810 <= addr <= 0x10870:
                print(stripped)
        except ValueError:
            continue

print("\n=== getdents64 area (around 0x106f8) ===")
for line in lines:
    stripped = line.strip()
    if stripped and ':' in stripped:
        try:
            addr_str = stripped.split(':')[0].strip()
            addr = int(addr_str, 16)
            if 0x106d0 <= addr <= 0x10770:
                print(stripped)
        except ValueError:
            continue

# Also find the read syscall - look for mov r7,#3
print("\n=== Searching for read() syscall ===")
for line in lines:
    stripped = line.strip()
    if 'mov\tr7, #3' in stripped or 'mov\tr7, #0x3' in stripped:
        print(f"Found: {stripped}")

# ioctl area
print("\n=== ioctl area (around 0x13c4c) ===")
for line in lines:
    stripped = line.strip()
    if stripped and ':' in stripped:
        try:
            addr_str = stripped.split(':')[0].strip()
            addr = int(addr_str, 16)
            if 0x13c20 <= addr <= 0x13c60:
                print(stripped)
        except ValueError:
            continue

# The function that's called from main - let's trace bl calls from main
print("\n=== Tracing function calls from main (0x1040c area) ===")
for line in lines:
    stripped = line.strip()
    if stripped and ':' in stripped and 'bl\t' in stripped:
        try:
            addr_str = stripped.split(':')[0].strip()
            addr = int(addr_str, 16)
            if 0x10400 <= addr <= 0x10600:
                print(stripped)
        except ValueError:
            continue

# Check data at key addresses referenced in main
print("\n=== Data references analysis ===")
# The main function uses movw/movt to construct addresses
# Let me look for movw+movt pairs (Thumb2 or ARM)
# ARM: movw = e30Xnnnn, movt = e34Xnnnn
for i, line in enumerate(lines):
    stripped = line.strip()
    if not stripped or ':' not in stripped:
        continue
    try:
        addr_str = stripped.split(':')[0].strip()
        addr = int(addr_str, 16)
    except ValueError:
        continue
    if 0x10400 <= addr <= 0x10600:
        # Check for instructions that might load addresses
        parts = stripped.split('\t')
        if len(parts) >= 2:
            instr_hex = parts[0].split(':')[1].strip() if ':' in parts[0] else ""
            # Check for movw, movt, ldr pc-relative
            if '<unknown>' in stripped:
                # movw/movt instructions show as <unknown> in llvm-objdump with --arch-name=arm
                # Parse the instruction word
                try:
                    instr_bytes = bytes.fromhex(instr_hex.replace(' ',''))
                    if len(instr_bytes) == 4:
                        word = struct.unpack('<I', instr_bytes)[0]
                        if (word & 0x0ff00000) == 0x03000000:  # movw
                            rd = (word >> 12) & 0xf
                            imm = ((word >> 4) & 0xf000) | (word & 0xfff)
                            print(f"  0x{addr:05x}: movw r{rd}, #0x{imm:04x}")
                        elif (word & 0x0ff00000) == 0x03400000:  # movt
                            rd = (word >> 12) & 0xf
                            imm = ((word >> 4) & 0xf000) | (word & 0xfff)
                            print(f"  0x{addr:05x}: movt r{rd}, #0x{imm:04x}")
                except:
                    pass
