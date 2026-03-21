#!/bin/sh
# gen-nvram.sh — Generate a pristine empty UEFI NVRAM variable store.
#
# Equivalent to Apple's VZEFIVariableStore(creatingVariableStoreAt:).
# Produces a valid EFI Firmware Volume with an authenticated variable store,
# filled with 0xFF (erase polarity) — ready for first boot.
#
# Usage: ./gen-nvram.sh [output-file] [size-kib]
#   output-file   path to write      (default: efi_vars.fd)
#   size-kib      volume size in KiB (default: 128)
#
# POSIX sh — no bash/zsh required.  All printf escapes use octal (\NNN),
# NOT hex (\xNN), because dash (Ubuntu /bin/sh) does not support \x.

set -eu

OUTPUT="${1:-efi_vars.fd}"
SIZE_KIB="${2:-128}"

# --- 96-byte header (3 structures, all fields little-endian) ---

# EFI_FIRMWARE_VOLUME_HEADER  [0x00–0x37]  56 bytes
#   [0x00] ZeroVector            16B   all zeros
printf '\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000' > "$OUTPUT"
#   [0x10] FileSystemGuid        16B   EFI_SYSTEM_NV_DATA_FV_GUID
#          {fff12b8d-7696-4c8b-a985-2747075b4f50}
printf '\215\053\361\377\226\166\213\114\251\205\047\107\007\133\117\120' >> "$OUTPUT"
#   [0x20] FvLength               8B   0x20000 (128 KiB)
#   [0x28] Signature              4B   "_FVH"
#   [0x2C] Attributes             4B   0x00000e36
printf '\000\000\002\000\000\000\000\000\137\106\126\110\066\016\000\000' >> "$OUTPUT"
#   [0x30] HeaderLength           2B   0x0048 (72 bytes)
#   [0x32] Checksum               2B   0xe9e6
#   [0x34] ExtHeaderOffset        2B   0x0000
#   [0x36] Reserved + Revision    2B   0x00, 0x02
printf '\110\000\346\351\000\000\000\002' >> "$OUTPUT"

# FV_BLOCK_MAP_ENTRY[]  [0x38–0x47]  16 bytes
#   [0x38] {NumBlocks=32, Length=4096}  — 32 × 4 KiB = 128 KiB
#   [0x40] {0, 0}                       — terminator
printf '\040\000\000\000\000\020\000\000\000\000\000\000\000\000\000\000' >> "$OUTPUT"

# VARIABLE_STORE_HEADER  [0x48–0x5F]  24 bytes
#   [0x48] Signature             16B   EFI_AUTHENTICATED_VARIABLE_GUID
#          {ddcf3616-3275-4164-98b6-fe85707ffe7d}
printf '\026\066\317\335\165\062\144\101\230\266\376\205\160\177\376\175' >> "$OUTPUT"
#   [0x58] Size                   4B   0x0000dfb8 (57272 — variable region capacity)
#   [0x5C] Format                 1B   0x5a (VARIABLE_STORE_FORMATTED)
#   [0x5D] State                  1B   0xfe (VARIABLE_STORE_HEALTHY)
#   [0x5E] Reserved               2B   0x0000
printf '\270\337\000\000\132\376\000\000' >> "$OUTPUT"

# --- 0xFF fill to end of volume ---
# EFI uses 0xFF for erased flash (erase polarity bit in Attributes).
# LC_ALL=C prevents macOS BSD tr from UTF-8-encoding \377 as U+00FF (c3 bf).
PAD=$((SIZE_KIB * 1024 - 96))
LC_ALL=C tr '\0' '\377' < /dev/zero | head -c "$PAD" >> "$OUTPUT"

SIZE=$(wc -c < "$OUTPUT" | tr -d ' ')
echo "Generated $OUTPUT ($SIZE bytes)"
