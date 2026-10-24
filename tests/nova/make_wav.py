#!/usr/bin/env python3
"""Generate a 1.5 s 16 kHz mono s16 WAV (a voice-like chirp), the format pw-record produces."""
import math, struct, sys, wave
w = wave.open(sys.argv[1], "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * (180 + 60 * math.sin(i / 1600)) * i / 16000)
    * (0.5 + 0.5 * math.sin(i / 900)))) for i in range(24000))); w.close()
