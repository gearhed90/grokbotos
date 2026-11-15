#!/bin/bash
# Tests for grokbot-touch-retry against a fake sysfs (no root, no hardware).
set -u
here=$(cd "$(dirname "$0")" && pwd)
S="$here/../build_files/rpi5/touch/grokbot-touch-retry"
ok=0; fail=0
check() { if eval "$2"; then ok=$((ok+1)); echo "PASS $1"; else fail=$((fail+1)); echo "FAIL $1"; fi; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mk() {  # fresh fake sysfs with one goodix device and no driver bound
    rm -rf "$T/sys" "$T/input"; mkdir -p "$T/sys/bus/i2c/devices/11-005d" "$T/sys/bus/i2c/drivers/Goodix-TS"
    echo "goodix-ts" > "$T/sys/bus/i2c/devices/11-005d/name"; : > "$T/input"; : > "$T/sys/bus/i2c/drivers/Goodix-TS/bind"
}
run() { GROKBOT_TOUCH_SYSFS="$T/sys" GROKBOT_TOUCH_INPUT="$T/input" GROKBOT_TOUCH_SLEEP=0 GROKBOT_TOUCH_TRIES=3 "$S" 2>&1; }

mk; ln -s ../../drivers/Goodix-TS "$T/sys/bus/i2c/devices/11-005d/driver"; echo 'N: Name="Goodix Capacitive TouchScreen"' > "$T/input"
out=$(run); check "touch already up -> nothing done" '[[ $out == *"touch is up"* && ! -s $T/sys/bus/i2c/drivers/Goodix-TS/bind ]]'

mk
# a fake "kernel": answers once the script is on its 2nd try
( for i in $(seq 1 200); do if grep -q "retry 2 of" "$T/log" 2>/dev/null; then
    ln -s ../../drivers/Goodix-TS "$T/sys/bus/i2c/devices/11-005d/driver"; echo 'N: Name="Goodix Capacitive TouchScreen"' > "$T/input"; break; fi; sleep 0.05; done ) &
run > "$T/log"; rc=$?; wait; out=$(cat "$T/log")
check "missed probe -> rebinds until it answers" '[[ $out == *"back after retry 2"* && $out != *"retry 3 of"* ]]'
check "bind was written with the device name" 'grep -qx 11-005d "$T/sys/bus/i2c/drivers/Goodix-TS/bind"'
check "exit 0" '[[ $rc -eq 0 ]]'

mk; out=$(run); rc=$?
check "never answers -> 3 tries, cable hint, exit 0" '[[ $(grep -c "no driver bound, retry" <<<"$out") -eq 3 && $out == *"ribbon cable"* && $rc -eq 0 ]]'

rm -rf "$T/sys"; mkdir -p "$T/sys/bus/i2c/devices/1-0050"; echo eeprom > "$T/sys/bus/i2c/devices/1-0050/name"
out=$(run); check "no goodix device -> nothing to do" '[[ $out == *"nothing to do"* ]]'

mk; mv "$T/sys/bus/i2c/devices/11-005d" "$T/sys/bus/i2c/devices/4-0014"; echo "of:NgoodixT(null)Cgoodix,gt911" > "$T/sys/bus/i2c/devices/4-0014/modalias"; echo x > "$T/sys/bus/i2c/devices/4-0014/name"
out=$(run); check "finds goodix by modalias at another address" '[[ $out == *"4-0014: no driver bound"* ]]'
echo "$ok passed, $fail failed"; [[ $fail -eq 0 ]]
