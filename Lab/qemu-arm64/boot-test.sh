#!/bin/zsh
# boot-test.sh — Local macOS aarch64 RouterOS CHR boot test
#
# Usage: ./Lab/qemu-arm64/boot-test.sh [path/to/chr-arm64.img]
#
# Tests QEMU boot for RouterOS CHR ARM64, matching the CI workflow as closely
# as possible. Reports HTTP + REST + check-installation results.
#
# Prerequisites (Homebrew):
#   brew install qemu

set -e

DISK="${1:-Lab/qemu-arm64/RAW/chr-7.22-arm64.img}"
VARS_SRC=/usr/local/share/qemu/edk2-arm-vars.fd
CODE=/usr/local/share/qemu/edk2-aarch64-code.fd
VARS_COPY=/tmp/qemu-test-vars.fd
PIDFILE=/tmp/qemu-test.pid
SOCKFILE=/tmp/qemu-test.sock
PORT=9280  # avoid conflicts with running UTM

cleanup() {
  local pid
  pid=$(cat "$PIDFILE" 2>/dev/null) && kill "$pid" 2>/dev/null || true
  rm -f "$PIDFILE" "$SOCKFILE" "$VARS_COPY"
}
trap cleanup EXIT

echo "=== aarch64 boot test ==="
echo "Disk:  $DISK"
echo "Code:  $CODE ($(stat -f%z "$CODE") bytes)"

cp "$VARS_SRC" "$VARS_COPY"

qemu-system-aarch64 \
  -cpu cortex-a710 \
  -M virt \
  -m 1024 \
  -smp 2 \
  -display none \
  -monitor none \
  -chardev "socket,id=serial0,path=$SOCKFILE,server=on,wait=off" \
  -serial chardev:serial0 \
  -drive "if=pflash,format=raw,readonly=on,unit=0,file=$CODE" \
  -drive "if=pflash,format=raw,unit=1,file=$VARS_COPY" \
  -drive "file=$DISK,format=raw,if=none,id=drive1" \
  -device virtio-blk-pci,drive=drive1,bootindex=0 \
  -netdev "user,id=net0,hostfwd=tcp::${PORT}-:80" \
  -device virtio-net-pci,netdev=net0 \
  -accel tcg,tb-size=256 \
  -daemonize -pidfile "$PIDFILE"

PID=$(cat "$PIDFILE")
echo "QEMU PID=$PID"
echo "Waiting for RouterOS to boot..."

attempt=0
max=24  # 4 minutes
while [[ $attempt -lt $max ]]; do
  sleep 10
  attempt=$((attempt + 1))
  cpu=$(ps -p "$PID" -o %cpu= 2>/dev/null | tr -d ' ')
  printf "  [%02d/%02d] CPU=%s%%" "$attempt" "$max" "$cpu"
  if curl -sS -m 5 --fail "http://localhost:${PORT}/" >/dev/null 2>&1; then
    echo " — HTTP 200! RouterOS is up."
    break
  else
    echo " — not ready, retrying..."
  fi
done

if ! curl -sS -m 5 --fail "http://localhost:${PORT}/" >/dev/null 2>&1; then
  echo "ERROR: RouterOS did not come up in time"
  exit 1
fi

echo ""
echo "=== REST identity ==="
curl -sS "http://admin:@localhost:${PORT}/rest/system/identity"
echo ""

echo ""
echo "=== /system/check-installation ==="
HTTP_CODE=$(curl -sS -o /tmp/check-result.json -w "%{http_code}" -X POST \
  -H 'Content-Type: application/json' \
  -d '{"duration":"30s"}' \
  "http://admin:@localhost:${PORT}/rest/system/check-installation")
echo "HTTP $HTTP_CODE — $(cat /tmp/check-result.json)"
echo ""

if [[ "$HTTP_CODE" -ge 400 ]]; then
  echo "FAIL: check-installation returned HTTP $HTTP_CODE"
  exit 1
fi

STATUS=$(python3 -c "
import sys, json
data = json.load(open('/tmp/check-result.json'))
if isinstance(data, list) and len(data) > 0:
    print(data[-1].get('status', ''))
elif isinstance(data, dict):
    print(data.get('status', ''))
")

if [[ "$STATUS" == "installation is ok" ]]; then
  echo "PASS: $STATUS"
else
  echo "FAIL: status='$STATUS'"
  exit 1
fi
