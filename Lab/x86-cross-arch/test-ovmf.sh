#!/bin/sh
# Test OVMF boot with standard CHR x86_64 image
set -eu
cd /Users/amm0/Documents/mikropkl/Machines/chr.x86_64.qemu.7.23beta2.utm

rm -f /tmp/test-ovmf-serial.sock /tmp/test-ovmf-stderr.log /tmp/test-ovmf-serial.log

OVMF=/usr/local/share/qemu/edk2-x86_64-code.fd
if [ ! -f "$OVMF" ]; then
  echo "ERROR: No OVMF firmware at $OVMF"
  exit 1
fi

# OVMF needs pflash — both units must be same size.
# Homebrew QEMU 10.2: code=3653632 bytes, vars=540672 bytes — mismatch.
# Pad vars to match code size.
OVMF_VARS=/usr/local/share/qemu/edk2-i386-vars.fd
CODE_SIZE=$(stat -f%z "$OVMF")
VARS_COPY=/tmp/test-ovmf-vars.fd
cp "$OVMF_VARS" "$VARS_COPY"
dd if=/dev/zero of="$VARS_COPY" bs=1 count=0 seek="$CODE_SIZE" 2>/dev/null
echo "pflash code: $CODE_SIZE, vars padded to: $(stat -f%z "$VARS_COPY")"

echo "Testing OVMF boot with standard CHR image..."
qemu-system-x86_64 \
  -M q35 \
  -accel tcg,tb-size=256 \
  -m 1024 -smp 2 \
  -drive if=pflash,format=raw,readonly=on,unit=0,file="$OVMF" \
  -drive if=pflash,format=raw,unit=1,file="$VARS_COPY" \
  -drive file=./Data/chr-7.23beta2.img,format=raw,if=virtio \
  -device virtio-net-pci,netdev=net0 \
  -netdev user,id=net0,hostfwd=tcp::19180-:80 \
  -display none \
  -nodefaults \
  -chardev socket,id=serial0,path=/tmp/test-ovmf-serial.sock,server=on,wait=off \
  -serial chardev:serial0 \
  2>/tmp/test-ovmf-stderr.log &
QPID=$!
echo "PID=$QPID"
sleep 2

if ! kill -0 "$QPID" 2>/dev/null; then
  echo "QEMU failed to start!"
  cat /tmp/test-ovmf-stderr.log
  exit 1
fi

socat -u UNIX-CONNECT:/tmp/test-ovmf-serial.sock CREATE:/tmp/test-ovmf-serial.log 2>/dev/null &
SPID=$!

BOOTED=0
for i in $(seq 1 12); do
  if ! kill -0 "$QPID" 2>/dev/null; then
    echo "QEMU exited early"
    break
  fi
  if curl -s -m 2 --fail http://localhost:19180/ > /dev/null 2>&1; then
    echo "HTTP OK after $((i*5))s"
    BOOTED=1
    break
  fi
  echo "Attempt $i/12..."
  sleep 5
done

kill "$SPID" 2>/dev/null; wait "$SPID" 2>/dev/null || true

echo "=== Serial output ==="
if [ -s /tmp/test-ovmf-serial.log ]; then
  head -30 /tmp/test-ovmf-serial.log
else
  echo "(empty)"
fi

echo "=== QEMU stderr ==="
if [ -s /tmp/test-ovmf-stderr.log ]; then
  cat /tmp/test-ovmf-stderr.log
else
  echo "(empty)"
fi

kill "$QPID" 2>/dev/null; wait "$QPID" 2>/dev/null || true
rm -f /tmp/test-ovmf-serial.sock /tmp/test-ovmf-serial.log /tmp/test-ovmf-stderr.log /tmp/test-ovmf-vars.fd

if [ "$BOOTED" = "1" ]; then
  echo "RESULT: OVMF boots standard CHR image!"
else
  echo "RESULT: OVMF cannot boot standard CHR image (as expected - proprietary boot partition)"
fi
