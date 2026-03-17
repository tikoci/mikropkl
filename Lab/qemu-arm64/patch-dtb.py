#!/usr/bin/env python3
"""
Lab/qemu-arm64/patch-dtb.py - Patch QEMU's linux,dummy-virt DTB to look like real ARM64 hardware.

Usage:
    python3 Lab/qemu-arm64/patch-dtb.py <input.dtb> <output.dtb> [--model MODEL] [--compat COMPAT]

Example (Ampere-like):
    python3 Lab/qemu-arm64/patch-dtb.py /tmp/qemu-n1.dtb /tmp/patched.dtb \
        --model "QEMU Virt" --compat "qemu,virt-v8"

The script patches:
  - model property (/ root node)  
  - compatible property (/ root node)

Hardware registers are NOT changed - only the identification strings that
RouterOS's kexec validator may check.
"""
import struct, sys, argparse

def parse_fdt_header(data):
    magic, totalsize, off_dt_struct, off_dt_strings, off_mem_rsvmap = struct.unpack_from('>IIIII', data, 0)
    assert magic == 0xd00dfeed, f"Not an FDT: {magic:#x}"
    return {
        'totalsize': totalsize,
        'off_dt_struct': off_dt_struct,
        'off_dt_strings': off_dt_strings,
    }

def patch_string_in_dtb(data, old_str, new_str):
    """
    Replace a null-terminated string in the FDT strings block.
    If new_str is longer than old_str, append new_str to strings block instead.
    Returns modified DTB bytes.
    """
    old_bytes = old_str.encode('utf-8') + b'\x00'
    new_bytes = new_str.encode('utf-8') + b'\x00'
    
    if old_bytes not in data:
        print(f"  WARNING: '{old_str}' not found in DTB")
        return data
    
    if len(new_bytes) <= len(old_bytes):
        # Replace in-place, pad with nulls
        replacement = new_bytes + b'\x00' * (len(old_bytes) - len(new_bytes))
        data = data.replace(old_bytes, replacement, 1)
    else:
        # Need to extend - grow the strings block
        # Find offset of old string in strings block
        hdr = parse_fdt_header(data)
        strings_start = hdr['off_dt_strings']
        strings_end = strings_start + struct.unpack_from('>I', data, 36)[0]  # off_dt_strings_size at offset 36
        
        old_offset = data.find(old_bytes, strings_start)
        if old_offset == -1:
            print(f"  WARN: '{old_str}' not in strings block, not patching")
            return data
        
        # Replace with pointer to new string appended at end
        print(f"  Extending strings block for '{new_str}'")
        new_offset = strings_end
        # Zero-fill old string location
        data = bytearray(data)
        data[old_offset:old_offset+len(old_bytes)] = b'\x00' * len(old_bytes)
        # Append new string
        data = bytes(data) + new_bytes
        # Update totalsize
        new_total = hdr['totalsize'] + len(new_bytes)
        data = bytearray(data)
        struct.pack_into('>I', data, 4, new_total)
        data = bytes(data)
        
        # Find all references to old string offset and update them
        # (This is complex; for now just warn)
        print(f"  NOTE: Reference patching in struct block not implemented, old string zeroed")
    
    return data

def patch_property_value(data, prop_name, old_val, new_val):
    """
    Patch a specific property's value in the DTB struct block.
    Finds FDT_PROP tokens with the given property name and value.
    """
    # FDT token types
    FDT_NODE_BEGIN = 0x00000001
    FDT_NODE_END   = 0x00000002
    FDT_PROP       = 0x00000003
    FDT_NOP        = 0x00000004
    FDT_END        = 0x00000009
    
    hdr = parse_fdt_header(data)
    struct_offset = hdr['off_dt_struct']
    strings_offset = hdr['off_dt_strings']
    
    old_val_bytes = (old_val.encode('utf-8') + b'\x00') if isinstance(old_val, str) else old_val
    new_val_bytes = (new_val.encode('utf-8') + b'\x00') if isinstance(new_val, str) else new_val
    
    pos = struct_offset
    depth = 0
    patched = 0
    data = bytearray(data)
    
    while pos < len(data):
        token = struct.unpack_from('>I', data, pos)[0]
        pos += 4
        
        if token == FDT_NODE_BEGIN:
            # Skip node name (null-terminated, padded to 4-byte)
            end = data.index(b'\x00', pos)
            pos = end + 1
            pos = (pos + 3) & ~3
            depth += 1
        elif token == FDT_NODE_END:
            depth -= 1
            if depth < 0:
                break
        elif token == FDT_PROP:
            prop_len = struct.unpack_from('>I', data, pos)[0]
            name_off = struct.unpack_from('>I', data, pos + 4)[0]
            val_start = pos + 8
            val_end = val_start + prop_len
            
            # Get property name from strings block
            name_bytes_start = strings_offset + name_off
            name_end = data.index(b'\x00', name_bytes_start)
            name = data[name_bytes_start:name_end].decode('utf-8', errors='replace')
            
            val = bytes(data[val_start:val_end])
            
            if depth == 1 and name == prop_name:  # Only at root node (depth=1)
                if old_val_bytes in val:
                    if len(new_val_bytes) == len(old_val_bytes):
                        idx = val.find(old_val_bytes)
                        data[val_start + idx:val_start + idx + len(old_val_bytes)] = new_val_bytes
                        patched += 1
                        print(f"  Patched '{prop_name}': '{old_val}' -> '{new_val}'")
                    else:
                        print(f"  SKIP: len mismatch: '{old_val}'({len(old_val_bytes)}) vs '{new_val}'({len(new_val_bytes)})")
                        print(f"  Consider padding new value to match old: new_val={repr(new_val_bytes)}")
            
            pos = val_end
            pos = (pos + 3) & ~3
        elif token == FDT_NOP:
            pass
        elif token == FDT_END:
            break
        else:
            break
    
    if patched == 0:
        print(f"  WARNING: '{prop_name}'='{old_val}' not found at root level")
    
    return bytes(data)

def main():
    parser = argparse.ArgumentParser(description='Patch QEMU DTB compatible strings')
    parser.add_argument('input', help='Input DTB file')
    parser.add_argument('output', help='Output DTB file')
    parser.add_argument('--model', default=None, help='Replacement model string (same length or shorter)')
    parser.add_argument('--compat', default=None, help='Replacement compatible string (same length or shorter)')
    parser.add_argument('--show', action='store_true', help='Just show current values, no patching')
    args = parser.parse_args()
    
    with open(args.input, 'rb') as f:
        data = f.read()
    
    hdr = parse_fdt_header(data)
    print(f"Input DTB: {args.input} ({len(data)} bytes)")
    print(f"  totalsize={hdr['totalsize']}, struct@{hdr['off_dt_struct']:#x}, strings@{hdr['off_dt_strings']:#x}")
    
    if args.show:
        # Just show model and compatible values
        FDT_PROP = 0x00000003
        FDT_NODE_BEGIN = 0x00000001
        FDT_NODE_END = 0x00000002
        FDT_END = 0x00000009
        FDT_NOP = 0x00000004
        pos = hdr['off_dt_struct']
        depth = 0
        data_ba = bytearray(data)
        strings_offset = hdr['off_dt_strings']
        while pos < len(data_ba):
            token = struct.unpack_from('>I', data_ba, pos)[0]
            pos += 4
            if token == FDT_NODE_BEGIN:
                end = data_ba.index(0, pos)
                pos = end + 1
                pos = (pos + 3) & ~3
                depth += 1
            elif token == FDT_NODE_END:
                depth -= 1
                if depth <= 0: break
            elif token == FDT_PROP:
                plen = struct.unpack_from('>I', data_ba, pos)[0]
                noff = struct.unpack_from('>I', data_ba, pos + 4)[0]
                val = bytes(data_ba[pos+8:pos+8+plen])
                name_start = strings_offset + noff
                name_end = data_ba.index(0, name_start)
                name = data_ba[name_start:name_end].decode('utf-8', errors='replace')
                if depth == 1 and name in ('model', 'compatible'):
                    printable = val.replace(b'\x00', b'|')
                    print(f"  root/{name} = {printable}")
                pos += 8 + plen
                pos = (pos + 3) & ~3
            elif token == FDT_NOP:
                pass
            elif token == FDT_END:
                break
            else:
                break
        return
    
    if args.model:
        data = patch_property_value(data, 'model', 'linux,dummy-virt', args.model)
    
    if args.compat:
        data = patch_property_value(data, 'compatible', 'linux,dummy-virt', args.compat)
    
    with open(args.output, 'wb') as f:
        f.write(data)
    print(f"Output: {args.output} ({len(data)} bytes)")

if __name__ == '__main__':
    main()
