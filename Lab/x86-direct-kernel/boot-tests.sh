#!/bin/bash
# boot-tests.sh — Reproduce x86 CHR boot experiments
#
# Prerequisites:
#   brew install qemu mtools
#   x86 CHR image at /tmp/x86-chr/chr-7.22.img
#   fat-chr image at Machines/chr.x86_64.apple.7.22.utm/Data/chr-efi.img
#     (or run: make CHR_VERSION=7.22)
#
# Usage: ./boot-tests.sh [test-name]
#   test-name: bios | ovmf | direct-kernel | all (default: all)

set -euo pipefail

CHR_IMG="${CHR_IMG:-/tmp/x86-chr/chr-7.22.img}"
FATCHR_IMG="${FATCHR_IMG:-$(dirname "$0")/../../Machines/chr.x86_64.apple.7.22.utm/Data/chr-efi.img}"
OVMF_CODE="/usr/local/share/qemu/edk2-x86_64-code.fd"
OVMF_VARS_SRC="/usr/local/share/qemu/edk2-i386-vars.fd"
PORT_BASE=9200
TIMEOUT=120

cleanup() {
    for pidfile in /tmp/x86-boot-test-*.pid; do
        [ -f "$pidfile" ] && kill "$(cat "$pidfile")" 2>/dev/null || true
    done
    rm -f /tmp/x86-boot-test-*.pid /tmp/x86-boot-test-*.log /tmp/x86-boot-test-vars.fd
}

wait_for_http() {
    local port=$1 max_attempts=$2
    for i in $(seq 1 "$max_attempts"); do
        if curl -s -m 5 --fail "http://localhost:$port/" > /dev/null 2>&1; then
            echo "  HTTP up after $((i * 5))s"
            return 0
        fi
        sleep 5
    done
    echo "  TIMEOUT — HTTP not reachable after $((max_attempts * 5))s"
    return 1
}

check_installation() {
    local port=$1
    local result
    result=$(curl -s -m 120 -u "admin:" -H "Content-Type: application/json" \
        -d '{"duration":"30s"}' "http://localhost:$port/rest/system/check-installation")
    if echo "$result" | grep -q "installation is ok"; then
        echo "  check-installation: PASS"
    else
        echo "  check-installation: FAIL — $result"
    fi
}

extract_kernel() {
    # Extract bzImage from CHR boot partition (offset 0x80000 from partition 1 start)
    # Partition 1 starts at LBA 34
    local kernel="/tmp/chr-x86-kernel.bzImage"
    if [ ! -f "$kernel" ]; then
        echo "Extracting kernel from $CHR_IMG ..."
        python3 -c "
import struct
with open('$CHR_IMG', 'rb') as f:
    f.seek(34*512 + 0x80000)  # partition 1 start + kernel offset
    hdr = f.read(0x300)
    setup_sects = hdr[0x1f1] or 4
    syssize = struct.unpack_from('<I', hdr, 0x1f4)[0]
    total = (setup_sects + 1) * 512 + syssize * 16
    f.seek(34*512 + 0x80000)
    data = f.read(total)
with open('$kernel', 'wb') as f:
    f.write(data)
print(f'Extracted {len(data)} bytes to $kernel')
"
    fi
    echo "$kernel"
}

test_bios() {
    echo "=== Test: SeaBIOS + original CHR image ==="
    local port=$((PORT_BASE))
    qemu-system-x86_64 \
        -drive file="$CHR_IMG",format=raw,if=virtio \
        -m 256 -smp 1 \
        -display none -monitor none \
        -serial file:/tmp/x86-boot-test-bios.log \
        -netdev user,id=net0,hostfwd=tcp::${port}-:80 \
        -device virtio-net-pci,netdev=net0 \
        -M q35 \
        -daemonize -pidfile /tmp/x86-boot-test-bios.pid
    echo "  QEMU PID: $(cat /tmp/x86-boot-test-bios.pid)"
    if wait_for_http $port 24; then
        check_installation $port
    fi
    echo "  Serial: $(cat /tmp/x86-boot-test-bios.log 2>/dev/null | strings | head -3)"
    kill "$(cat /tmp/x86-boot-test-bios.pid)" 2>/dev/null || true
}

test_ovmf() {
    echo "=== Test: OVMF UEFI + fat-chr image ==="
    local port=$((PORT_BASE + 1))
    if [ ! -f "$OVMF_CODE" ]; then
        echo "  SKIP — OVMF not found at $OVMF_CODE"
        return
    fi
    if [ ! -f "$FATCHR_IMG" ]; then
        echo "  SKIP — fat-chr image not found at $FATCHR_IMG"
        return
    fi
    cp "$OVMF_VARS_SRC" /tmp/x86-boot-test-vars.fd
    qemu-system-x86_64 \
        -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
        -drive if=pflash,format=raw,file=/tmp/x86-boot-test-vars.fd \
        -drive file="$FATCHR_IMG",format=raw,if=virtio \
        -m 256 -smp 1 \
        -display none -monitor none \
        -serial file:/tmp/x86-boot-test-ovmf.log \
        -netdev user,id=net0,hostfwd=tcp::${port}-:80 \
        -device virtio-net-pci,netdev=net0 \
        -M q35 \
        -daemonize -pidfile /tmp/x86-boot-test-ovmf.pid
    echo "  QEMU PID: $(cat /tmp/x86-boot-test-ovmf.pid)"
    if wait_for_http $port 24; then
        check_installation $port
    fi
    echo "  Serial (tail): $(xxd /tmp/x86-boot-test-ovmf.log 2>/dev/null | tail -5)"
    kill "$(cat /tmp/x86-boot-test-ovmf.pid)" 2>/dev/null || true
}

test_direct_kernel() {
    echo "=== Test: Direct -kernel boot (no firmware) ==="
    local port=$((PORT_BASE + 2))
    local kernel
    kernel=$(extract_kernel)
    echo "  Using kernel: $kernel"
    # This test is expected to FAIL — documents the limitation
    timeout "$TIMEOUT" qemu-system-x86_64 \
        -kernel "$kernel" \
        -append "console=ttyS0,115200 earlyprintk=serial,ttyS0,115200 root=/dev/vda2" \
        -drive file="$CHR_IMG",format=raw,if=virtio \
        -m 256 -smp 1 \
        -nographic \
        -netdev user,id=net0,hostfwd=tcp::${port}-:80 \
        -device virtio-net-pci,netdev=net0 \
        -M q35 2>&1 | head -20
    echo "  RESULT: Kernel hangs during real-mode setup (expected)"
}

# Main
trap cleanup EXIT

case "${1:-all}" in
    bios) test_bios ;;
    ovmf) test_ovmf ;;
    direct-kernel|direct) test_direct_kernel ;;
    all)
        test_bios
        echo ""
        test_ovmf
        echo ""
        test_direct_kernel
        ;;
    *) echo "Usage: $0 [bios|ovmf|direct-kernel|all]"; exit 1 ;;
esac
