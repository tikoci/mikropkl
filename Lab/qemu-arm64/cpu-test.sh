#!/usr/bin/env bash
# Lab/qemu-arm64/cpu-test.sh
# Test different QEMU CPU models to find one where RouterOS check-installation passes.
# Run from mikropkl root: ./Lab/qemu-arm64/cpu-test.sh
set -euo pipefail

DISK="Lab/qemu-arm64/RAW/chr-7.22-arm64.img"
EFI_CODE="/usr/local/share/qemu/edk2-aarch64-code.fd"
PORT=9181   # Use 9181 to avoid conflict with boot-test.sh
TIMEOUT=300 # 5 min per test (TCG is slow)
LOGDIR="/tmp/chr-cpu-tests"
mkdir -p "$LOGDIR"

CPU_MODELS=(
    "cortex-a53"      # IPQ5332 (embedded DTB in BOOTAA64.EFI is A53!)
    "neoverse-n1"     # Ampere Altra = Oracle Cloud Free Tier
    "cortex-a57"      # Common early ARMv8 server
    "cortex-a72"      # Common ARMv8 server
    "cortex-a710"     # Current default in boot-test.sh
    "cortex-a76"      # Late ARMv8.2
    "max"             # All features enabled
)

run_test() {
    local cpu="$1"
    local log="$LOGDIR/${cpu}.log"
    local sockpath="/tmp/chr-test-${cpu}.sock"
    local pidfile="/tmp/chr-test-${cpu}.pid"
    local varfile="/tmp/chr-vars-${cpu}.fd"

    echo ""
    echo "=== Testing CPU: $cpu ==="

    # Clean up previous
    rm -f "$sockpath" "$pidfile" "$varfile"
    cp /usr/local/share/qemu/edk2-arm-vars.fd "$varfile"

    # Launch QEMU
    qemu-system-aarch64 \
        -cpu "$cpu" \
        -M virt \
        -m 512 \
        -smp 1 \
        -display none \
        -monitor none \
        -chardev socket,id=serial0,path="$sockpath",server=on,wait=off \
        -serial "chardev:serial0" \
        -drive if=pflash,format=raw,readonly=on,unit=0,file="$EFI_CODE" \
        -drive if=pflash,format=raw,unit=1,file="$varfile" \
        -drive file="$DISK",format=raw,if=none,id=drive1 \
        -device virtio-blk-pci,drive=drive1,bootindex=0 \
        -netdev user,id=net0,hostfwd=tcp::"${PORT}"-:80 \
        -device virtio-net-pci,netdev=net0 \
        -accel tcg,tb-size=256 \
        -daemonize -pidfile "$pidfile" 2>>"$log"

    local pid
    pid=$(cat "$pidfile")
    echo "  QEMU pid=$pid, log=$log"

    # Capture serial output in background
    (nc -U "$sockpath" 2>/dev/null || true) > "${log}.serial" &
    local nc_pid=$!

    # Wait for RouterOS to boot (poll HTTP)
    local elapsed=0
    local booted=false
    echo -n "  Waiting for HTTP (max ${TIMEOUT}s)..."
    while [ $elapsed -lt $TIMEOUT ]; do
        if curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/" 2>/dev/null | grep -q "200"; then
            booted=true
            break
        fi
        sleep 5
        elapsed=$((elapsed + 5))
        echo -n "."
    done
    echo ""

    if ! $booted; then
        echo "  RESULT: TIMEOUT - RouterOS did not boot in ${TIMEOUT}s"
        # Show CPU% to diagnose hang
        ps -p "$pid" -o pid,pcpu,rss 2>/dev/null || true
        kill "$pid" 2>/dev/null || true
        kill "$nc_pid" 2>/dev/null || true
        return
    fi

    echo "  HTTP 200 - RouterOS is up (elapsed: ${elapsed}s)"

    # Check serial for kexec result
    sleep 2
    if [ -f "${log}.serial" ]; then
        echo "  Serial (kexec-related):"
        grep -i "kexec\|load fail\|EFI/BOOT\|Starting serv\|check.install\|Invalid 2nd" "${log}.serial" 2>/dev/null | head -10 | sed 's/^/    /'
    fi

    # Test check-installation
    echo -n "  check-installation: "
    local ci_code
    ci_code=$(curl -s -o "/tmp/ci-${cpu}.json" -w "%{http_code}" \
        -X POST \
        -u "admin:" \
        "http://localhost:${PORT}/rest/system/check-installation" \
        --data '{"duration":"30s"}' 2>/dev/null || echo "000")

    local ci_result
    ci_result=$(cat "/tmp/ci-${cpu}.json" 2>/dev/null || echo "no output")
    echo "HTTP $ci_code — $ci_result"

    # Cleanup
    kill "$pid" 2>/dev/null || true
    kill "$nc_pid" 2>/dev/null || true
    rm -f "$sockpath" "$varfile" "$pidfile"

    # Summary line
    if echo "$ci_result" | grep -q "installation is ok"; then
        echo "  *** SUCCESS: check-installation PASSED for cpu=$cpu ***"
    elif [ "$ci_code" = "200" ]; then
        echo "  PARTIAL: HTTP 200 but not 'installation is ok'"
    else
        echo "  FAIL: check-installation failed (HTTP $ci_code)"
    fi
}

if ! [ -f "$DISK" ]; then
    echo "ERROR: Disk not found: $DISK"
    echo "Run from the mikropkl root directory"
    exit 1
fi

echo "CHR ARM64 CPU Model Test"
echo "Disk: $DISK"
echo "Logs: $LOGDIR"
echo "Port: $PORT"
echo ""
echo "CPUs to test: ${CPU_MODELS[*]}"

for cpu in "${CPU_MODELS[@]}"; do
    run_test "$cpu"
    sleep 3
done

echo ""
echo "=== All tests complete. Results summary ==="
for cpu in "${CPU_MODELS[@]}"; do
    ci_file="/tmp/ci-${cpu}.json"
    if [ -f "$ci_file" ]; then
        result=$(cat "$ci_file")
        echo "  $cpu: $result"
    else
        echo "  $cpu: (timed out)"
    fi
done
