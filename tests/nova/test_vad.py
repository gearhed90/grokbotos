#!/usr/bin/env python3
"""End-of-speech detector (novad.Vad / _wav_layout) on synthetic audio. No mic, no network."""
import io, os, struct, sys, wave
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "build_files", "rpi5", "nova"))
sys.path.insert(0, HERE)
os.environ.setdefault("NOVA_SYS_KEY_FILE", "")
import novad, make_wav
ok = fail = 0
def check(name, cond, info=""):
    global ok, fail
    ok += bool(cond); fail += not cond
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(info)[:300]))
def pcm(spec, scale=1.0):
    return b"".join(struct.pack("<h", max(-32768, min(32767, int(x * scale)))) for x in make_wav.build(spec))
def run(spec, chunk=1000, scale=1.0, **kw):
    """Feed in odd-sized chunks like a growing file; return (verdict, seconds of audio consumed)."""
    v = novad.Vad(16000, **kw); data = pcm(spec, scale)
    for i in range(0, len(data), chunk):
        out = v.feed(data[i:i + chunk])
        if out: return out, v.frames * novad.VAD_FRAME_S
    return None, v.frames * novad.VAD_FRAME_S

r, t = run("s1,v1.5,s2"); check("silence, speech, silence -> ends ~1.2 s after speech", r == "silence" and 3.6 <= t <= 3.9, (r, t))
r, t = run("s1,v1.5,s2", silence_s=0.8); check("silence_s is honoured (0.8 s)", r == "silence" and 3.2 <= t <= 3.5, (r, t))
r, t = run("s1,v1,s0.7,v1,s2"); check("a short pause mid-sentence does not end it", r == "silence" and t >= 4.8, (r, t))
r, t = run("v1.5,s2"); check("talking right away still ends on the pause", r == "silence" and 2.6 <= t <= 2.9, (r, t))
r, t = run("s9"); check("no speech -> 'nospeech' at 7 s", r == "nospeech" and abs(t - 7.0) < 0.15, (r, t))
r, t = run("s4", no_speech_s=3); check("no_speech_s is honoured", r == "nospeech" and abs(t - 3.0) < 0.15, (r, t))
r, t = run("s1,v0.2,s9"); check("a 0.2 s click is not speech", r == "nospeech", (r, t))
r, t = run("s1,v1.5,s0.5"); check("still talking/short tail -> no verdict yet", r is None, (r, t))
r, t = run("s1,v1.5,s6", scale=0.04); check("very quiet voice under speech_rms -> nospeech", r == "nospeech", (r, t))
r, t = run("s1,v1.5,s2", scale=0.04, speech_rms=60); check("lower speech_rms picks up a quiet mic", r == "silence", (r, t))
# loud steady background (fan): floor adapts, speech still detected and pause still ends it
loud = lambda spec: b"".join(struct.pack("<h", max(-32768, min(32767, a + b))) for a, b in
                             zip(make_wav.build(spec), make_wav.noise(16000 * 5, amp=400, seed=3)))
v = novad.Vad(16000); data = loud("s1,v1.5,s2.5"); out = None
for i in range(0, len(data), 3200):
    out = out or v.feed(data[i:i + 3200])
check("noisy room (fan) still ends on the pause", out == "silence", out)
# WAV header parsing
b = io.BytesIO(); w = wave.open(b, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\0\0" * 10); w.close()
h = b.getvalue()
check("plain 44-byte header", novad._wav_layout(h) == (44, 16000), novad._wav_layout(h))
check("partial header -> wait", novad._wav_layout(h[:30]) is None and novad._wav_layout(h[:40]) is None)
ext = h[:12] + b"LIST" + (6).to_bytes(4, "little") + b"abcdef" + h[12:]
check("extra chunk before data", novad._wav_layout(ext) == (58, 16000), novad._wav_layout(ext))
b = io.BytesIO(); w = wave.open(b, "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000); w.writeframes(b"\0" * 40); w.close()
check("stereo -> unsupported (auto stop off)", novad._wav_layout(b.getvalue()) is False)
check("not a WAV -> unsupported", novad._wav_layout(b"\x01" * 64) is False)
# config clamping
p = novad.vad_params({"auto_stop": True, "silence_s": 0.01, "no_speech_s": "x", "speech_rms": 99999})
check("vad_params clamps bad values", p["silence_s"] == 0.4 and p["no_speech_s"] == novad.VAD_DEFAULTS["no_speech_s"] and p["speech_rms"] == 8000, p)
check("auto_stop false turns it off", novad.vad_params({"auto_stop": False})["auto_stop"] is False)
check("default silence timeout 1.2 s", novad.VAD_DEFAULTS["silence_s"] == 1.2 or "NOVA_VAD_SILENCE" in os.environ, novad.VAD_DEFAULTS)
print("\n%d passed, %d failed" % (ok, fail)); sys.exit(1 if fail else 0)
