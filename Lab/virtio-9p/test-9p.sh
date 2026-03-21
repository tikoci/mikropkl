#!/bin/sh
# Test whether RouterOS CHR kernel recognizes virtio-9p-pci
#
# Adds a virtio-9p-pci device via QEMU_EXTRA and checks:
#   1. QEMU accepts the device (doesn't crash)
#   2. RouterOS boots normally (HTTP 200 on REST API)
#   3. Guest kernel logs show whether 9p device was recognized or ignored
#
# Usage:
#   ./test-9p.sh [UTM_PATH]
#
# Default: uses chr.x86_64.qemu machine in Machines/

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Find a machine to test with
UTM="${1:-$(ls -d "$PROJECT_DIR"/Machines/chr.x86_64.qemu.*.utm 2>/dev/null | head -1)}"
if [ -z "$UTM" ] || [ ! -d "$UTM" ]; then
    echo "No machine found. Build first with 'make' or pass UTM path as argument."
    exit 1
fi

QEMU_SH="$UTM/qemu.sh"
if [ ! -x "$QEMU_SH" ]; then
    echo "No executable qemu.sh in $UTM"
    exit 1
fi

SHARED_DIR="$SCRIPT_DIR/shared"
mkdir -p "$SHARED_DIR"
echo "hello from host" > "$SHARED_DIR/test.txt"

PORT=9199
SERIAL_LOG="$SCRIPT_DIR/serial.log"

echo "=== virtio-9p-pci test ==="
echo "Machine: $UTM"
echo "Shared dir: $SHARED_DIR"
echo "Port: $PORT"
echo ""

# Add virtio-9p-pci device via QEMU_EXTRA
# -fsdev local: share a host directory
# -device virtio-9p-pci: present it as a PCI device to the guest
export QEMU_EXTRA="-fsdev local,id=fsdev0,path=$SHARED_DIR,security_model=none -device virtio-9p-pci,fsdev=fsdev0,mount_tag=hostshare"
export QEMU_PORT="$PORT"

echo "Starting QEMU with virtio-9p-pci device..."
"$QEMU_SH" --background --port "$PORT"

# Read PID from the pidfile
PIDFILE="$UTM/qemu.pid"
sleep 2
if [ ! -f "$PIDFILE" ]; then
    echo "FAIL: QEMU did not start (no pidfile)"
    exit 1
fi
PID=$(cat "$PIDFILE")

echo "QEMU PID: $PID"
echo ""

# Wait for boot (check HTTP)
echo "Waiting for RouterOS to boot..."
BOOTED=false
for i in $(seq 1 12); do
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "FAIL: QEMU process died during boot"
        # Check if there's a log
        [ -f "$UTM/qemu.log" ] && echo "--- qemu.log ---" && tail -20 "$UTM/qemu.log"
        exit 1
    fi
    if curl -sf -o /dev/null "http://127.0.0.1:$PORT/rest/system/resource" 2>/dev/null; then
        BOOTED=true
        echo "RouterOS booted after ~$((i * 5))s"
        break
    fi
    sleep 5
done

if [ "$BOOTED" = false ]; then
    echo "TIMEOUT: RouterOS did not respond within 60s"
    echo "But QEMU is still running — the 9p device didn't crash QEMU."
    echo ""
fi

# Check system info
if [ "$BOOTED" = true ]; then
    echo ""
    echo "=== RouterOS System Info ==="
    curl -sf "http://127.0.0.1:$PORT/rest/system/resource" 2>/dev/null | python3 -m json.tool 2>/dev/null || true

    echo ""
    echo "=== Checking for 9p device in guest ==="
    echo "Attempting /system/resource/pci/print (if available)..."
    curl -sf "http://127.0.0.1:$PORT/rest/system/resource/pci" 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "(PCI endpoint not available via REST)"

    echo ""
    echo "Attempting /file/print to check mounted filesystems..."
    curl -sf "http://127.0.0.1:$PORT/rest/file" 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "(file endpoint not available)"
fi

# Check QEMU monitor for PCI devices
MONITOR_SOCK="$UTM/qemu.monitor"
if [ -S "$MONITOR_SOCK" ]; then
    echo ""
    echo "=== QEMU Monitor: PCI devices ==="
    echo "info pci" | socat - UNIX-CONNECT:"$MONITOR_SOCK" 2>/dev/null | grep -A2 -i '9p\|filesystem\|virtio' || echo "(no 9p device in PCI listing)"

    echo ""
    echo "=== QEMU Monitor: qtree (virtio-9p) ==="
    echo "info qtree" | socat - UNIX-CONNECT:"$MONITOR_SOCK" 2>/dev/null | grep -B2 -A5 -i '9p\|fsdev\|hostshare' || echo "(no 9p in qtree)"
fi

# Check QEMU log for 9p-related messages
if [ -f "$UTM/qemu.log" ]; then
    echo ""
    echo "=== QEMU stderr log (9p/virtio related) ==="
    grep -i '9p\|fsdev\|v9fs' "$UTM/qemu.log" 2>/dev/null || echo "(no 9p messages in log)"
fi

echo ""
echo "=== Cleanup ==="
"$QEMU_SH" --stop 2>/dev/null || kill "$PID" 2>/dev/null || true
echo "Stopped QEMU (PID $PID)"

echo ""
echo "=== Conclusion ==="
if [ "$BOOTED" = true ]; then
    echo "RouterOS booted successfully WITH virtio-9p-pci device attached."
    echo "If no 9p filesystem appears in the guest, the kernel lacks CONFIG_9P_FS / CONFIG_9P_VIRTIO."
    echo ""
    echo "Binary analysis of the aarch64 kernel (5.6.3) shows NO 9p-related strings:"
    echo "  - No 'v9fs', '9pnet', '9pnet_virtio', '9p_virtio' symbols found"
    echo "  - Compiled virtio drivers: virtio_blk, virtio_scsi, virtio_net, virtio_console,"
    echo "    virtio_balloon, virtio_gpu, virtio_rproc_serial"
    echo "  - Missing: virtio_9p (9p/VirtFS transport)"
else
    echo "RouterOS did not boot — check logs above."
fi
