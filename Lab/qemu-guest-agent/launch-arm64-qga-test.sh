#!/bin/sh
# launch-arm64-qga-test.sh — Launch aarch64 CHR with QGA for testing
# Uses the MikroTik test build chr-7.23_ab650-arm64.img
set -eu

cd "$(dirname "$0")"

# Prepare writable EFI vars
cp /usr/local/share/qemu/edk2-arm-vars.fd /tmp/qga-arm64-test-vars.fd

# Clean up stale sockets
rm -f /tmp/qga-arm64-test.sock /tmp/qga-arm64-test-serial.sock

exec qemu-system-aarch64 \
  -M virt -cpu cortex-a710 -m 1024 -smp 2 \
  -accel tcg,tb-size=256 \
  -drive if=pflash,format=raw,readonly=on,unit=0,file=/usr/local/share/qemu/edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,unit=1,file=/tmp/qga-arm64-test-vars.fd \
  -drive file=chr-7.23_ab650-arm64.img,format=raw,if=none,id=drive1 \
  -device virtio-blk-pci,drive=drive1,bootindex=0 \
  -netdev user,id=net0,hostfwd=tcp::9197-:80 \
  -device virtio-net-pci,netdev=net0 \
  -display none -monitor none \
  -chardev socket,id=serial0,path=/tmp/qga-arm64-test-serial.sock,server=on,wait=off \
  -serial chardev:serial0 \
  -device virtio-serial-pci,id=virtio-serial-qga \
  -chardev socket,id=qga0,path=/tmp/qga-arm64-test.sock,server=on,wait=off \
  -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0,id=qga-port0
