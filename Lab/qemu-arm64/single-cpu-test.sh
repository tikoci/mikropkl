#!/usr/bin/env bash
# Lab/qemu-arm64/single-cpu-test.sh
# Quick test of one CPU model: captures serial and checks check-installation
# Usage: ./Lab/qemu-arm64/single-cpu-test.sh <cpu-model> [port]
set -euo pipefail

CPU="${1:-cortex-a53}"
PORT="${2:-9182}"
DISK="Lab/qemu-arm64/RAW/chr-7.22-arm64.img"
EFI_CODE="/usr/local/share/qemu/edk2-aarch64-code.fd"
TIMEOUT=360  # 6 minutes
SOCK="/tmp/chr-single.sock"
PID_FILE="/tmp/chr-single.pid"
VAR_FILE="/tmp/chr-single-vars.fd"
SERIAL_LOG="/tmp/chr-single-serial.log"

cleanup() {
    kill "$(cat $PID_FILE 2>/dev/null)" 2>/dev/null || true
    kill "$NC_PID" 2>/dev/null || true
    rm -f "$SOCK" "$PID_FILE" "$VAR_FILE"
}
trap cleanup EXIT

rm -f "$SOCK" "$PID_FILE" "$VAR_FILE" "$SERIAL_LOG"
cp /usr/local/share/qemu/edk2-arm-vars.fd "$VAR_FILE"

echo "=== Testing CPU: $CPU (port=$PORT) ==="

qemu-system-aarch64 \
    -cpu "$CPU" \
    -M virt \
    -m 512 \
    -smp 1 \
    -display none \
    -monitor none \
    -chardev "socket,id=serial0,path=$SOCK,server=on,wait=off" \
    -serial chardev:serial0 \
    -drive if=pflash,format=raw,readonly=on,unit=0,file="$EFI_CODE" \
    -drive if=pflash,format=raw,unit=1,file="$VAR_FILE" \
    -drive "file=$DISK,format=raw,if=none,id=drive1" \
    -device virtio-blk-pci,drive=drive1,bootindex=0 \
    -netdev "user,id=net0,hostfwd=tcp::${PORT}-:80" \
    -device virtio-net-pci,netdev=net0 \
    -accel tcg,tb-size=256 \
    -daemonize -pidfile "$PID_FILE"

PID=$(cat "$PID_FILE")
echo "QEMU pid=$PID"

# Capture serial in background
nc -U "$SOCK" > "$SERIAL_LOG" 2>/dev/null &
NC_PID=$!

# Wait for boot
elapsed=0
echo -n "Waiting for RouterOS HTTP (max ${TIMEOUT}s): "
while [ $elapsed -lt $TIMEOUT ]; do
    code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/" 2>/dev/null || echo 000)
    if [ "$code" = "200" ]; then
        echo " UP! (${elapsed}s)"
        break
    fi
    sleep 5; elapsed=$((elapsed+5)); echo -n "."
done

if [ $elapsed -ge $TIMEOUT ]; then
    echo " TIMEOUT"
    echo "CPU% at timeout: $(ps -p "$PID" -o pcpu= 2>/dev/null || echo 'dead')"
    echo "Serial tail:"
    tail -20 "$SERIAL_LOG" 2>/dev/null | sed 's/^/  /'
    exit 1
fi

# Show kexec-related serial output
echo ""
echo "--- Serial output (kexec/boot events): ---"
grep -i "kexec\|Starting\|Cannot load\|Invalid\|load fail\|EFI/BOOT\|services" "$SERIAL_LOG" 2>/dev/null | head -20 | sed 's/^/  /' || echo "  (no matching lines yet)"
echo ""

# Give more time for RouterOS to fully initialize
sleep 15

echo "--- More serial (after delay): ---"
grep -i "kexec\|Invalid\|load fail\|Cannot load\|services\|check" "$SERIAL_LOG" 2>/dev/null | head -20 | sed 's/^/  /' || echo "  (no matches)"
echo ""

# Identity check
echo -n "Identity: "
curl -s -u "admin:" "http://localhost:${PORT}/rest/system/identity" || echo "(failed)"
echo ""

# check-installation
echo "Running check-installation (30s)..."
HTTP_CODE=$(curl -s -o /tmp/ci-result.json -w "%{http_code}" \
    -X POST -u "admin:" \
    --data '{"duration":"30s"}' \
    "http://localhost:${PORT}/rest/system/check-installation" 2>/dev/null || echo "000")
RESULT=$(cat /tmp/ci-result.json 2>/dev/null || echo "no output")
echo "HTTP $HTTP_CODE: $RESULT"

echo ""
if echo "$RESULT" | grep -q "installation is ok"; then
    echo "*** SUCCESS: check-installation PASSED with -cpu $CPU ***"
elif [ "$HTTP_CODE" = "400" ]; then
    echo "FAIL: damaged system package (HTTP 400)"
else
    echo "Status: HTTP $HTTP_CODE"
fi

echo ""
echo "Full serial log: $SERIAL_LOG"
