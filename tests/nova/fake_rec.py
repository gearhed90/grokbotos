#!/usr/bin/env python3
"""Stand-in for pw-record: writes the sample WAV to argv[1], then waits for SIGINT like pw-record.
NOVA_TEST_STREAM=1: writes it like a live mic instead, 100 ms at a time in real time, then keeps
writing quiet room noise until SIGINT (so the end-of-speech watcher sees a growing file)."""
import os, random, shutil, signal, struct, sys, time, wave
LOG = os.environ["NOVA_TEST_RECLOG"]
stop = []
def on_int(*a):
    open(LOG, "a").write("REC stop\n"); stop.append(1)
signal.signal(signal.SIGINT, on_int)
open(LOG, "a").write("REC start\n")
if os.environ.get("NOVA_TEST_STREAM") != "1":
    shutil.copy(os.environ["NOVA_TEST_WAV"], sys.argv[1])
    while not stop: time.sleep(.05)
    sys.exit(0)
src = wave.open(os.environ["NOVA_TEST_WAV"]); data = src.readframes(src.getnframes()); src.close()
out = wave.open(sys.argv[1], "wb"); out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000)
r = random.Random(7); pos = 0; step = 3200   # 100 ms of s16 mono
while not stop:
    if pos < len(data): chunk = data[pos:pos + step]; pos += step
    else: chunk = b"".join(struct.pack("<h", int(r.gauss(0, 60))) for _ in range(step // 2))
    out.writeframes(chunk); out._file.flush()
    time.sleep(.1)
out.close()
