# Lab: UEFI NVRAM Generation — Shell vs Pkl

Comparison of generating a pristine 128 KiB UEFI NVRAM variable store using
POSIX shell vs pkl.  Both produce byte-identical output (verified via SHA-256).

## Files

| File | Approach | Lines | Output mechanism |
|---|---|---|---|
| `gen-nvram.sh` | POSIX sh | ~50 | `printf` octal escapes + `tr` fill |
| `nvram_gen.pkl` | pkl | ~85 | `FileOutput.bytes` + `base64DecodedBytes` |

## How to run

```sh
# Shell
./gen-nvram.sh efi_vars.fd

# Pkl
pkl eval nvram_gen.pkl -m .
```

## Comparison

### Shell strengths

- **Byte-level control is natural.**  `printf '\215\053'` maps directly to bytes
  0x8D, 0x2B — you can read the UEFI spec and transcribe field-by-field.
- **Fill generation is elegant.**  `tr '\0' '\377' < /dev/zero | head -c N` is
  a single pipeline for arbitrary-length byte fills.
- **No encoding layer.**  What you write is what you get (modulo the octal
  conversion).  Easy to patch a single byte.

### Shell weaknesses

- **Portability traps.**  The hex escape bug (`\xNN` not supported in dash) was
  the root cause of the GitHub Actions failure that prompted this investigation.
  Octal works everywhere, but you have to *know* that.
- **No validation.**  A typo in an octal escape silently produces wrong bytes.
  The checksum field could be wrong and nothing catches it until UTM rejects
  the file at runtime.
- **Locale sensitivity.**  `tr '\0' '\377'` produces UTF-8 `c3 bf` instead of
  raw `0xFF` without `LC_ALL=C` on macOS.  Another silent correctness bug.

### Pkl strengths

- **Structured documentation.**  Doc comments on `headerBase64` describe every
  field offset, size, and value.  The documentation IS the code — pkl's doc
  comments render in IDEs and `pkl doc`.
- **Computed properties.**  `fillSize` is derived from `volumeSize` and
  `headerSize` — change the volume size and the fill adjusts automatically
  (though the header base64 would also need regeneration).
- **Type safety.**  `DataSize` ensures you don't accidentally mix KiB and bytes.
  `repeat()` requires `UInt` — pkl caught the `Float` division error at eval
  time (needed `~/` truncating division instead of `/`).
- **Single-expression output.**  The entire 131072-byte file is one expression:
  `(headerBase64 + fillBase64).base64DecodedBytes`.

### Pkl weaknesses

- **Binary data is opaque.**  The header is a base64 blob — you can't read the
  individual UEFI fields from `"AAAAAAAAAAAAAAAAAAAAAI0r8f+..."`.  Changing a
  single byte means re-encoding the entire 96-byte header.
- **No byte-level construction for large data.**  `Bytes(0x8D, 0x2B, ...)` works
  for small sequences, but 130976 bytes of fill would be impractical.  The
  base64 `"////".repeat(N)` trick works but is non-obvious.
- **Integer division quirk.**  pkl's `/` always returns `Float`, even for `Int`
  operands.  Must use `~/` for truncating integer division — easy to forget.

### Pkl alternative: byte-level header

The header *could* be written byte-by-byte using `Bytes()`, trading compactness
for readability:

```pkl
local header: Bytes =
  // ZeroVector (16 bytes)
  Bytes(0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
  // FileSystemGuid: EFI_SYSTEM_NV_DATA_FV_GUID
  + Bytes(0x8D, 0x2B, 0xF1, 0xFF, 0x96, 0x76, 0x8B, 0x4C,
          0xA9, 0x85, 0x27, 0x47, 0x07, 0x5B, 0x4F, 0x50)
  // ... 64 more bytes
```

This is more readable than base64 (hex values match the spec directly) but
still can't help with the fill region.  And it's ~15 lines of byte literals
vs one line of base64 — a judgment call.

## Verdict

**For this specific task (fixed binary blob generation), shell is the better fit.**
The byte-level control maps naturally to the problem domain, and the portability
issues are solvable with known patterns (octal escapes, `LC_ALL=C`).

**Pkl would shine if** the NVRAM generation were part of a larger configuration
pipeline — e.g., generating the variable store alongside the `config.plist` and
`qemu.cfg` in a single pkl module, where typed properties and cross-file
validation matter more than byte-level control.  The current Makefile approach
(pkl emits `.genefi` placeholder, Make generates binary) is a reasonable hybrid.
