#!/usr/bin/env python3
"""Generate a 16 kHz mono s16 WAV, the format pw-record produces.
make_wav.py OUT            -> 1.5 s voice-like chirp
make_wav.py OUT s1,v1.5,s2 -> segments: s = room noise (quiet), v = voice-like chirp, seconds each"""
import math, random, struct, sys, wave
def voice(n, i0=0):
    return [int(8000 * math.sin(2 * math.pi * (180 + 60 * math.sin(i / 1600)) * i / 16000) * (0.5 + 0.5 * math.sin(i / 900)))
            for i in range(i0, i0 + n)]
def noise(n, amp=60, seed=1):
    r = random.Random(seed); return [int(r.gauss(0, amp)) for _ in range(n)]
def build(spec):
    out = []
    for seg in spec.split(","):
        n = int(float(seg[1:]) * 16000)
        out += voice(n, len(out)) if seg[0] == "v" else noise(n, seed=len(out))
    return out
if __name__ == "__main__":
    smp = build(sys.argv[2]) if len(sys.argv) > 2 else voice(24000)
    w = wave.open(sys.argv[1], "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
    w.writeframes(b"".join(struct.pack("<h", max(-32768, min(32767, x))) for x in smp)); w.close()
