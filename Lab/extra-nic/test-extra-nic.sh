#!/bin/sh
# Lab test script: extra-nic install on ARM64 CHR with Intel NICs in QEMU
#
# Tests:
#   1. Boot ARM64 CHR with e1000e + igb devices added
#   2. Verify Intel NICs appear in PCI hardware but NOT as interfaces (no driver)
#   3. Install extra-nic.npk via SCP
#   4. Reboot and verify ether2/ether3 now appear as usable interfaces
#
# Prerequisites:
#   - Built mikropkl machines (chr.aarch64.qemu.7.22.1.utm)
#   - qemu-system-aarch64 in PATH
#   - UEFI firmware at /usr/local or /opt/homebrew share/qemu/
#
# Usage:
#   ./test-extra-nic.sh [path-to-chr-disk.img] [path-to-extra-nic.npk]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MIKROPKL_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

CHR_IMG="${1:-$MIKROPKL_DIR/Machines/chr.aarch64.qemu.7.22.1.utm/Data/chr-7.22.1-arm64.img}"
EXTRA_NIC_NPK="${2:-/tmp/extra-nic-7.22.1-arm64.npk}"

HTTP_PORT=9382
SSH_PORT=9322
TEST_IMG=/tmp/chr-arm64-extra-nic-test.img
TEST_VARS=/tmp/chr-arm64-extra-nic-vars.fd
SERIAL_SOCK=/tmp/chr-arm64-extra-nic-serial.sock
QEMU_LOG=/tmp/chr-arm64-extra-nic-qemu.log
QEMU_PID_FILE=/tmp/chr-arm64-extra-nic.pid

# --- Find UEFI firmware ---
find_firmware() {
    for dir in /opt/homebrew/share/qemu /usr/local/share/qemu; do
        if [ -f "$dir/edk2-aarch64-code.fd" ]; then
            EFI_CODE="$dir/edk2-aarch64-code.fd"
            EFI_VARS_TEMPLATE="$dir/edk2-arm-vars.fd"
            return 0
        fi
    done
    echo "ERROR: UEFI aarch64 firmware not found" >&2
    return 1
}

# --- Download extra-nic if not present ---
if [ ! -f "$EXTRA_NIC_NPK" ]; then
    echo "Downloading extra-nic-7.22.1-arm64.npk..."
    curl -fsSL -o "$EXTRA_NIC_NPK" \
        "https://download.mikrotik.com/routeros/7.22.1/extra-nic-7.22.1-arm64.npk"
fi

find_firmware

# --- Prepare test environment ---
echo "Copying disk image to test location..."
cp "$CHR_IMG" "$TEST_IMG"
cp "$EFI_VARS_TEMPLATE" "$TEST_VARS"

# --- Start QEMU ---
echo "Starting QEMU with e1000e + igb devices..."
qemu-system-aarch64 \
    -M virt \
    -cpu cortex-a710 \
    -m 1024M \
    -smp 2 \
    -accel tcg,tb-size=256 \
    -drive if=pflash,format=raw,readonly=on,unit=0,file="$EFI_CODE" \
    -drive if=pflash,format=raw,unit=1,file="$TEST_VARS" \
    -drive file="$TEST_IMG",format=raw,if=none,id=drive0 \
    -device virtio-blk-pci,drive=drive0,bootindex=0 \
    -netdev "user,id=net0,hostfwd=tcp::${HTTP_PORT}-:80,hostfwd=tcp::${SSH_PORT}-:22" \
    -device virtio-net-pci,netdev=net0,mac=0e:7e:27:7d:3c:32 \
    -netdev user,id=net1 \
    -device e1000e,netdev=net1,mac=0e:7e:27:7d:3c:33 \
    -netdev user,id=net2 \
    -device igb,netdev=net2,mac=0e:7e:27:7d:3c:34 \
    -display none \
    -monitor none \
    -chardev "socket,id=serial0,path=$SERIAL_SOCK,server=on,wait=off" \
    -serial chardev:serial0 \
    -D "$QEMU_LOG" \
    > /tmp/chr-arm64-extra-nic-out.log 2>&1 &
QEMU_PID=$!
echo "$QEMU_PID" > "$QEMU_PID_FILE"
echo "QEMU started (PID $QEMU_PID)"

# --- Wait for first boot ---
echo "Waiting for first boot (~60s TCG)..."
for i in $(seq 1 24); do
    sleep 5
    if curl -sf -m 3 -u "admin:" "http://localhost:${HTTP_PORT}/" > /dev/null 2>&1; then
        echo "  CHR up after $((i*5))s"
        break
    fi
    kill -0 "$QEMU_PID" 2>/dev/null || { echo "ERROR: QEMU died. Log:"; tail -5 "$QEMU_LOG"; exit 1; }
    printf "  %ds elapsed...\n" "$((i*5))"
done

# --- Phase 1: Check BEFORE extra-nic ---
echo ""
echo "=== BEFORE extra-nic ==="
echo "Packages:"
curl -sf -u "admin:" "http://localhost:${HTTP_PORT}/rest/system/package" \
    | python3 -c "import sys,json; [print(' ', p['name'], p['version']) for p in json.load(sys.stdin)]"

echo "Interfaces:"
curl -sf -u "admin:" "http://localhost:${HTTP_PORT}/rest/interface" \
    | python3 -c "import sys,json; [print(' ', i['name'], i.get('mac-address','')) for i in json.load(sys.stdin)]"

echo "Hardware (PCI only):"
curl -sf -u "admin:" \
    "http://localhost:${HTTP_PORT}/rest/system/resource/hardware/print" \
    -X POST -H "Content-Type: application/json" -d '{"detail":""}' \
    | python3 -c "import sys,json; [print(' ', d.get('location','?'), d.get('name','?')) for d in json.load(sys.stdin) if d.get('type')=='pci']"

# --- Install extra-nic ---
echo ""
echo "=== Installing extra-nic ==="
echo "Uploading $EXTRA_NIC_NPK via SCP..."
scp -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o LogLevel=ERROR \
    -P "$SSH_PORT" \
    "$EXTRA_NIC_NPK" "admin@127.0.0.1:/"

echo "Verifying file on CHR:"
curl -sf -u "admin:" "http://localhost:${HTTP_PORT}/rest/file" \
    | python3 -c "import sys,json; [print(' ', f['name'], f.get('size','')) for f in json.load(sys.stdin) if 'extra-nic' in f.get('name','')]"

echo "Rebooting..."
curl -sf -u "admin:" -X POST "http://localhost:${HTTP_PORT}/rest/system/reboot" > /dev/null

# --- Wait for second boot ---
echo "Waiting for post-install reboot (~60s TCG)..."
sleep 10  # give it time to actually start rebooting
for i in $(seq 1 24); do
    sleep 5
    if curl -sf -m 3 -u "admin:" "http://localhost:${HTTP_PORT}/" > /dev/null 2>&1; then
        echo "  CHR back up after $((i*5+10))s"
        break
    fi
    kill -0 "$QEMU_PID" 2>/dev/null || { echo "ERROR: QEMU died post-reboot"; tail -5 "$QEMU_LOG"; break; }
    printf "  %ds elapsed...\n" "$((i*5+10))"
done

# --- Phase 2: Check AFTER extra-nic ---
echo ""
echo "=== AFTER extra-nic ==="
echo "Packages:"
curl -sf -u "admin:" "http://localhost:${HTTP_PORT}/rest/system/package" \
    | python3 -c "import sys,json; [print(' ', p['name'], p['version']) for p in json.load(sys.stdin)]"

echo "Interfaces:"
curl -sf -u "admin:" "http://localhost:${HTTP_PORT}/rest/interface" \
    | python3 -c "import sys,json; [print(' ', i['name'], i.get('mac-address',''), '('+i.get('type','')+')') for i in json.load(sys.stdin)]"

echo "Hardware (PCI only):"
curl -sf -u "admin:" \
    "http://localhost:${HTTP_PORT}/rest/system/resource/hardware/print" \
    -X POST -H "Content-Type: application/json" -d '{"detail":""}' \
    | python3 -c "import sys,json; [print(' ', d.get('location','?'), d.get('name','?'), '['+ d.get('owner','')+']') for d in json.load(sys.stdin) if d.get('type')=='pci']"

# --- Cleanup ---
echo ""
echo "=== Cleanup ==="
echo "Stopping QEMU (PID $QEMU_PID)..."
kill "$QEMU_PID" 2>/dev/null || true
rm -f "$QEMU_PID_FILE" "$TEST_VARS"
echo "Done. Test disk preserved at: $TEST_IMG"
echo "       QEMU log at:           $QEMU_LOG"
