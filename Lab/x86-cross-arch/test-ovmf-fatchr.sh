#!/bin/sh
# Test OVMF boot with fat-chr EFI image (the reformatted one used by Apple VZ)
set -eu
cd /Users/amm0/Documents/mikropkl/Machines/chr.x86_64.qemu.7.23beta2.utm

EFI_IMG="../chr.x86_64.apple.7.23beta2.utm/Data/chr-efi.img"
OVMF=/usr/local/share/qemu/edk2-x86_64-code.fd
OVMF_VARS=/usr/local/share/qemu/edk2-i386-vars.fd

if [ ! -f "$EFI_IMG" ]; then
  echo "ERROR: fat-chr image not found at $EFI_IMG"
  exit 1
fi

rm -f /tmp/test-efi-serial.sock /tmp/test-efi-stderr.log /tmp/test-efi-serial.log

# Pad vars to code size
CODE_SIZE=$(stat -f%z "$OVMF")
VARS_COPY=/tmp/test-efi-vars.fd
cp "$OVMF_VARS" "$VARS_COPY"
dd if=/dev/zero of="$VARS_COPY" bs=1 count=0 seek="$CODE_SIZE" 2>/dev/null
echo "pflash code=$CODE_SIZE vars=$(stat -f%z "$VARS_COPY")"

echo "Testing OVMF + fat-chr image (q35, virtio)..."
qemu-system-x86_64 \
  -M q35 \
  -accel tcg,tb-size=256 \
  -m 1024 -smp 2 \
  -drive if=pflash,format=raw,readonly=on,unit=0,file="$OVMF" \
  -drive if=pflash,format=raw,unit=1,file="$VARS_COPY" \
  -drive file="$EFI_IMG",format=raw,if=virtio \
  -device virtio-net-pci,netdev=net0 \
  -netdev user,id=net0,hostfwd=tcp::19180-:80 \
  -display none \
  -nodefaults \
  -chardev socket,id=serial0,path=/tmp/test-efi-serial.sock,server=on,wait=off \
  -serial chardev:serial0 \
  2>/tmp/test-efi-stderr.log &
QPID=$!
echo "PID=$QPID"
sleep 2

if ! kill -0 "$QPID" 2>/dev/null; then
  echo "QEMU failed to start!"
  cat /tmp/test-efi-stderr.log 2>/dev/null
  exit 1
fi

socat -u UNIX-CONNECT:/tmp/test-efi-serial.sock CREATE:/tmp/test-efi-serial.log 2>/dev/null &
SPID=$!

BOOTED=0
START=$(date +%s)
for i in $(seq 1 12); do
  if ! kill -0 "$QPID" 2>/dev/null; then
    echo "QEMU exited early"
    break
  fi
  if curl -s -m 2 --fail http://localhost:19180/ > /dev/null 2>&1; then
    ELAPSED=$(( $(date +%s) - START ))
    echo "HTTP OK after ${ELAPSED}s"
    BOOTED=1
    break
  fi
  echo "Attempt $i/12..."
  sleep 5
done

kill "$SPID" 2>/dev/null; wait "$SPID" 2>/dev/null || true

echo "=== Serial output ==="
if [ -s /tmp/test-efi-serial.log ]; then
  head -30 /tmp/test-efi-serial.log
else
  echo "(empty)"
fi

echo "=== QEMU stderr ==="
cat /tmp/test-efi-stderr.log 2>/dev/null | head -10

kill "$QPID" 2>/dev/null; wait "$QPID" 2>/dev/null || true
rm -f /tmp/test-efi-serial.sock /tmp/test-efi-serial.log /tmp/test-efi-stderr.log /tmp/test-efi-vars.fd

if [ "$BOOTED" = "1" ]; then
  echo "RESULT: OVMF + fat-chr boots successfully!"
else
  echo "RESULT: OVMF + fat-chr failed to boot"
fi
