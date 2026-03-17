#!/usr/bin/env python3
"""Deep analysis of the RouterOS check-installation ARM32 checker binary"""
import struct
import re

with open('/tmp/npk-bin-bash-arm32.elf', 'rb') as f:
    elf_data = f.read()

# Parse ELF segments
e_phoff = struct.unpack_from('<I', elf_data, 28)[0]
e_phnum = struct.unpack_from('<H', elf_data, 44)[0]
e_phentsize = struct.unpack_from('<H', elf_data, 42)[0]
e_entry = struct.unpack_from('<I', elf_data, 24)[0]
print(f"Entry point: 0x{e_entry:x}")

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
        print(f"  LOAD: vaddr=0x{p_vaddr:x} offset=0x{p_offset:x} filesz=0x{p_filesz:x} memsz=0x{p_memsz:x}")


def vaddr_to_offset(vaddr):
    for seg_vaddr, seg_offset, seg_filesz, seg_memsz in segments:
        if seg_vaddr <= vaddr < seg_vaddr + seg_memsz:
            return vaddr - seg_vaddr + seg_offset
    return None


# Find ALL printable strings >= 4 chars
print("\n=== ALL strings in binary ===")
for seg_vaddr, seg_offset, seg_filesz, _ in segments:
    seg_data = elf_data[seg_offset:seg_offset + seg_filesz]
    for m in re.finditer(rb'[\x20-\x7e]{4,}', seg_data):
        vaddr = seg_vaddr + m.start()
        s = m.group().decode('ascii', errors='replace')
        print(f"  0x{vaddr:05x}: {s}")

# Find all syscall (svc #0) instructions
print("\n=== All SVC (syscall) instructions ===")
syscall_names = {
    1: 'exit', 3: 'read', 4: 'write', 5: 'open', 6: 'close',
    11: 'execve', 20: 'getpid', 54: 'ioctl', 91: 'munmap', 106: 'stat',
    125: 'mprotect', 140: '_llseek', 192: 'mmap2', 195: 'stat64',
    197: 'fstat64', 217: 'getdents64', 248: 'exit_group',
    347: 'openat', 352: 'kexec_file_load', 355: 'getrandom',
    384: 'renameat2',
}

for seg_vaddr, seg_offset, seg_filesz, _ in segments:
    seg_data = elf_data[seg_offset:seg_offset + seg_filesz]
    for i in range(0, len(seg_data) - 3, 4):
        instr = struct.unpack_from('<I', seg_data, i)[0]
        if instr == 0xef000000:  # svc #0
            vaddr = seg_vaddr + i
            # Look for the r7 value (syscall number) - search backwards
            r7_val = None
            for j in range(i - 4, max(i - 60, 0), -4):
                prev = struct.unpack_from('<I', seg_data, j)[0]
                # mov r7, #imm (e3a07xxx)
                if (prev & 0xfff0f000) == 0xe3a07000:
                    r7_val = prev & 0xfff
                    break
            name = syscall_names.get(r7_val, f"?{r7_val}") if r7_val is not None else "?"
            print(f"  0x{vaddr:05x}: svc #0  (r7={r7_val} = {name})")

# Look for kexec_file_load syscall specifically (ARM32: 382)
print("\n=== Searching for kexec_file_load (syscall 382 on ARM32) ===")
for seg_vaddr, seg_offset, seg_filesz, _ in segments:
    seg_data = elf_data[seg_offset:seg_offset + seg_filesz]
    for i in range(0, len(seg_data) - 3, 4):
        instr = struct.unpack_from('<I', seg_data, i)[0]
        # mov r7, #382 = 0x17e
        # ARM encoding: e3a0717e or could be split
        if (prev := instr) and (instr & 0xfffff000) == 0xe3a07000:
            imm = instr & 0xfff
            if imm in (382, 380, 381, 383, 384, 352, 347):
                vaddr = seg_vaddr + i
                name = syscall_names.get(imm, f"?{imm}")
                print(f"  0x{vaddr:05x}: mov r7, #{imm} ({name})")

# Find magic value 0xbad0f11e
print("\n=== Searching for magic 0xbad0f11e ===")
magic_le = struct.pack('<I', 0xbad0f11e)  # \x1e\xf1\xd0\xba
magic_be = struct.pack('>I', 0xbad0f11e)  # \xba\xd0\xf1\x1e
for label, magic in [("LE", magic_le), ("BE", magic_be)]:
    idx = 0
    while True:
        idx = elf_data.find(magic, idx)
        if idx == -1:
            break
        print(f"  Found {label} magic at file offset 0x{idx:x}")
        # Show context
        ctx = elf_data[max(0, idx-8):idx+12]
        print(f"    context: {ctx.hex()}")
        idx += 1
