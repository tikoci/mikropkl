#!/bin/zsh
# inspect-disk.py — parse MBR+GPT partition tables from a raw CHR image
#
# Usage: python3 Lab/qemu-arm64/inspect-disk.py [path/to/img]

import struct, uuid, sys

IMAGE = sys.argv[1] if len(sys.argv) > 1 else 'Lab/qemu-arm64/RAW/chr-7.22-arm64.img'

with open(IMAGE, 'rb') as f:
    f.seek(446)
    print("=== MBR partition table ===")
    for i in range(4):
        data = f.read(16)
        if len(data) < 16:
            break
        type_ = data[4]
        lba_start = struct.unpack_from('<I', data, 8)[0]
        lba_size  = struct.unpack_from('<I', data, 12)[0]
        if lba_size > 0:
            print(f"  Part {i+1}: type=0x{type_:02x} start={lba_start} size={lba_size} "
                  f"({lba_size*512//1024//1024} MiB) offset={lba_start*512}")

    f.seek(512)
    gpt_hdr = f.read(92)
    sig = gpt_hdr[:8]
    print(f"\n=== GPT header at LBA 1 ===")
    print(f"  Signature: {sig}")
    if sig == b'EFI PART':
        part_lba = struct.unpack_from('<Q', gpt_hdr, 72)[0]
        num_parts = struct.unpack_from('<I', gpt_hdr, 80)[0]
        part_size = struct.unpack_from('<I', gpt_hdr, 84)[0]
        print(f"  Partition array: LBA={part_lba}, count={num_parts}, "
              f"entry_size={part_size}")

        f.seek(part_lba * 512)
        print("\n=== GPT partitions ===")
        EFI_SYSTEM  = 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b'
        LINUX_DATA  = '0fc63daf-8483-4772-8e79-3d69d8477de4'
        for i in range(min(num_parts, 16)):
            entry = f.read(part_size)
            if entry[:16] == b'\x00' * 16:
                break
            type_guid = str(uuid.UUID(bytes_le=entry[:16]))
            start_lba = struct.unpack_from('<Q', entry, 32)[0]
            end_lba   = struct.unpack_from('<Q', entry, 40)[0]
            size_mib  = (end_lba - start_lba + 1) * 512 // 1024 // 1024
            name = entry[56:128].decode('utf-16-le').rstrip('\x00')
            ptype = {EFI_SYSTEM: 'EFI-SP', LINUX_DATA: 'Linux'}.get(type_guid, type_guid)
            print(f"  Part {i+1}: [{start_lba}..{end_lba}] {size_mib} MiB "
                  f"offset={start_lba*512} name='{name}' type={ptype}")
