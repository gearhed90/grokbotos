#!/usr/bin/env python3
"""Voice (step 6) tests: mocked xAI /stt + /tts, fake pw-record/pw-play, generated WAV. No mic, no sound.
Ports 8766/8767: classic push-to-talk. 8768/8769: end-of-speech auto stop with a live-like (streaming) fake mic."""
import json, os, stat, subprocess, sys, tempfile, threading, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "build_files", "rpi5", "nova")
os.environ["NOVA_SYS_KEY_FILE"] = ""
T = tempfile.mkdtemp(); RUN = T + "/run"; os.makedirs(RUN, mode=0o700)
key = T + "/key"; open(key, "w").write("sk-test"); os.chmod(key, 0o600)
WAV = T + "/sample.wav"; subprocess.check_call([sys.executable, HERE + "/make_wav.py", WAV])
NEXT = T + "/next_transcript"; RECLOG = T + "/rec.log"; open(RECLOG, "w").close()
SPEECH = T + "/speech.wav"; subprocess.check_call([sys.executable, HERE + "/make_wav.py", SPEECH, "s0.6,v1.2,s0.2"])
QUIET = T + "/quiet.wav"; subprocess.check_call([sys.executable, HERE + "/make_wav.py", QUIET, "s0.5"])
STTLOG = T + "/stt.log"; open(STTLOG, "w").close()
base = dict(os.environ, NOVA_API_BASE="http://127.0.0.1:8799/v1", NOVA_DRY_RUN="1", NOVA_TEST_SOURCES="[]", NOVA_KEY_FILE=key,
            GROKBOT_API_SOCK=T + "/none.sock", XDG_RUNTIME_DIR=RUN, NOVA_TEST_WAV=WAV, NOVA_TEST_RECLOG=RECLOG,
            NOVA_REC_CMD="%s %s/fake_rec.py {out}" % (sys.executable, HERE),
            NOVA_PLAY_CMD="%s %s/fake_play.py {in}" % (sys.executable, HERE), NOVA_TEST_SPK="1")
A = dict(base, NOVA_PORT="8766", NOVA_TEST_MIC="1", NOVA_REC_CAP="1.5", NOVA_VOICE_CFG=T + "/cfgA/nova-voice.json")
Bn = dict(base, NOVA_PORT="8767", NOVA_TEST_MIC="0", NOVA_TEST_SOURCES="[]", NOVA_VOICE_CFG=T + "/cfgB/nova-voice.json")
C = dict(base, NOVA_PORT="8768", NOVA_TEST_MIC="1", NOVA_REC_CAP="10", NOVA_VOICE_CFG=T + "/cfgC/nova-voice.json",
         NOVA_TEST_STREAM="1", NOVA_TEST_WAV=SPEECH, NOVA_VAD_SILENCE="0.8")
D = dict(base, NOVA_PORT="8769", NOVA_TEST_MIC="1", NOVA_REC_CAP="3", NOVA_VOICE_CFG=T + "/cfgD/nova-voice.json",
         NOVA_TEST_STREAM="1", NOVA_TEST_WAV=QUIET, NOVA_VAD_NO_SPEECH="2")
la, lb, lc, ld = (open(T + "/%s.log" % n, "w") for n in "abcd")
ps = [subprocess.Popen([sys.executable, HERE + "/mock_xai.py"], env=dict(os.environ, MOCK_STT_NEXT=NEXT, MOCK_STT_LOG=STTLOG)),
      subprocess.Popen([sys.executable, ROOT + "/novad.py"], env=A, stderr=la),
      subprocess.Popen([sys.executable, ROOT + "/novad.py"], env=Bn, stderr=lb),
      subprocess.Popen([sys.executable, ROOT + "/novad.py"], env=C, stderr=lc),
      subprocess.Popen([sys.executable, ROOT + "/novad.py"], env=D, stderr=ld)]
time.sleep(1.2)
def req(port, path, body=None, hdr=None):
    u = "http://127.0.0.1:%d%s" % (port, path)
    rq = urllib.request.Request(u, json.dumps(body).encode() if body is not None else None,
                                {"Content-Type": "application/json", **(hdr or {})})
    try:
        return urllib.request.urlopen(rq).read().decode()
    except urllib.error.HTTPError as e:
        return "HTTP %d" % e.code
J = lambda *a, **k: json.loads(req(*a, **k))
def ask(port, p, via="voice"): return [json.loads(l) for l in req(port, "/api/ask", {"prompt": p, "via": via}).splitlines() if l.strip()][-1]
def say(text, hold=0.6):   # simulate one push-to-talk press with the generated WAV
    open(NEXT, "w").write(text); r = J(8766, "/api/voice/start", {}); time.sleep(hold)
    return r, J(8766, "/api/voice/stop", {})
ok = fail = 0
def check(name, cond, info=""):
    global ok, fail
    ok += bool(cond); fail += not cond
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(info)[:300]))
try:
    s = J(8766, "/api/voice/status"); check("status: mic + speaker, not muted", s["mic"] and s["speaker"] and not s["muted"] and s["cap_s"] == 1.5, s)
    st, r = say("bring up the burnt peanut twitch stream")
    check("push-to-talk start", st.get("ok"), st)
    check("transcript returned", r.get("transcript") == "bring up the burnt peanut twitch stream" and r.get("intent") is None, r)
    check("temp audio deleted after stop", os.listdir(RUN + "/nova-voice") == [], os.listdir(RUN + "/nova-voice"))
    a = ask(8766, r["transcript"]); check("transcript goes through normal ask flow", "Twitch" in a.get("reply", ""), a)
    st, r = say("TOOL power {\"action\": \"lock\"}"); a = ask(8766, r["transcript"])
    check("voice request -> confirmation", "confirm" in a, a)
    st, r = say("Yes, please."); check("spoken 'yes' -> intent yes", r.get("intent") == "yes", r)
    c = J(8766, "/api/confirm", {"id": a["confirm"]["id"], "yes": r["intent"] == "yes"}); check("spoken yes runs action", "Locking" in c.get("reply", "") or "lock" in c.get("reply", "").lower(), c)
    a = ask(8766, "TOOL power {\"action\": \"restart\"}"); st, r = say("No, don't.")
    check("spoken 'no' -> intent no", r.get("intent") == "no", r)
    c = J(8766, "/api/confirm", {"id": a["confirm"]["id"], "yes": r["intent"] == "yes"}); check("spoken no declines", "won't" in c.get("reply", ""), c)
    st, r = say("nothing to see"); check("'nothing' not read as no", r.get("intent") is None, r)
    # 30 s cap (1.5 s in test)
    open(NEXT, "w").write("a very long ramble"); J(8766, "/api/voice/start", {}); time.sleep(2.2)
    check("cap stops the recorder by itself", open(RECLOG).read().strip().splitlines()[-1] == "REC stop", open(RECLOG).read())
    time.sleep(.3); check("cap ends the take by itself (not recording)", J(8766, "/api/voice/status")["recording"] is False)
    r = J(8766, "/api/voice/stop", {}); check("stop after cap: capped transcript", r.get("capped") is True and r.get("secs") == 1.5 and r.get("end") == "cap", r)
    check("double stop refused", J(8766, "/api/voice/stop", {}).get("error") == "idle")
    J(8766, "/api/voice/start", {}); r = J(8766, "/api/voice/stop", {"cancel": True}); check("Esc cancels without STT", r.get("cancelled"), r)
    check("busy start refused", (J(8766, "/api/voice/start", {}), J(8766, "/api/voice/start", {}))[1].get("error") == "busy"); J(8766, "/api/voice/stop", {"cancel": True})
    # TTS + mute
    r = J(8766, "/api/voice/speak", {"text": "Opening burntpeanut's Twitch stream now."}); check("reply spoken", r.get("ok"), r)
    check("player got a WAV", "PLAY" in open(RECLOG).read())
    r = J(8766, "/api/voice/mute", {"muted": True}); check("mute on", r["muted"] is True, r)
    cf = T + "/cfgA/nova-voice.json"; check("mute remembered in nova-voice.json (0600)", json.load(open(cf))["muted"] is True and stat.S_IMODE(os.stat(cf).st_mode) == 0o600)
    n = open(RECLOG).read().count("PLAY"); r = J(8766, "/api/voice/speak", {"text": "hello"})
    check("muted reply not spoken", r.get("skipped") == "muted" and open(RECLOG).read().count("PLAY") == n, r)
    check("mute survives restart (status reads file)", J(8766, "/api/voice/status")["muted"] is True)
    J(8766, "/api/voice/mute", {"muted": False}); check("unmute", J(8766, "/api/voice/speak", {"text": "hi"}).get("ok"))
    # ---- end of speech (auto stop), streaming fake mic: 0.6 s room noise, 1.2 s voice, then quiet ----
    nstt = lambda: open(STTLOG).read().count("STT")
    open(NEXT, "w").write("what's the weather tomorrow"); n0 = nstt(); t0 = time.time()
    st = J(8768, "/api/voice/start", {}); check("auto start returns sid + auto", st.get("sid") and st.get("auto") is True and st.get("silence_s") == 0.8, st)
    e = J(8768, "/api/voice/wait", {"sid": st["sid"], "until": "ended"}); te = time.time() - t0
    check("take ends by itself after the pause", e.get("ended") is True and e.get("end") == "silence" and 2.2 < te < 4.5, (e, te))
    r = J(8768, "/api/voice/wait", {"sid": st["sid"]})
    check("wait returns the transcript", r.get("transcript") == "what's the weather tomorrow" and r.get("sid") == st["sid"] and r.get("end") == "silence", r)
    check("auto stop: one STT call", nstt() == n0 + 1, nstt() - n0)
    check("auto stop: not recording, spool empty", J(8768, "/api/voice/status")["recording"] is False and os.listdir(RUN + "/nova-voice") == [])
    check("tap after auto stop already delivered -> idle", J(8768, "/api/voice/stop", {}).get("error") == "idle")
    # tap early while the page is long-polling: both get the same single result
    n0 = nstt(); st = J(8768, "/api/voice/start", {}); got = {}
    th = threading.Thread(target=lambda: got.update(J(8768, "/api/voice/wait", {"sid": st["sid"]}))); th.start()
    time.sleep(1.2); r = J(8768, "/api/voice/stop", {}); th.join(5)
    check("tap stops early", r.get("end") == "tap" and r.get("transcript"), r)
    check("long poll gets the same result", got.get("sid") == st["sid"] and got.get("transcript") == r.get("transcript"), got)
    check("tap + auto stop: STT only once", nstt() == n0 + 1, nstt() - n0)
    time.sleep(2.5); check("no late auto stop after a tap", nstt() == n0 + 1 and J(8768, "/api/voice/status")["recording"] is False)
    # auto stop racing a tap: tap lands right as the pause ends -> still one result
    n0 = nstt(); st = J(8768, "/api/voice/start", {}); time.sleep(2.6)
    rs = [None, None]
    ths = [threading.Thread(target=lambda i=i: rs.__setitem__(i, J(8768, "/api/voice/" + ("stop" if i else "wait"), {"sid": st["sid"]}))) for i in (0, 1)]
    [x.start() for x in ths]; [x.join(8) for x in ths]
    check("race: one STT call, same result to both", nstt() == n0 + 1 and rs[0].get("transcript") and rs[0].get("sid") == st["sid"]
          and (rs[1].get("transcript") == rs[0]["transcript"] or rs[1].get("error") == "idle"), (rs, nstt() - n0))
    # Esc while listening -> cancelled for the long poll too, no STT
    n0 = nstt(); st = J(8768, "/api/voice/start", {}); time.sleep(.4)
    r = J(8768, "/api/voice/stop", {"cancel": True}); w = J(8768, "/api/voice/wait", {"sid": st["sid"]})
    check("cancel: page poll sees cancelled, no STT", r.get("cancelled") and w.get("cancelled") and nstt() == n0, (r, w))
    check("stale sid -> idle", J(8768, "/api/voice/wait", {"sid": "nope"}).get("error") == "idle")
    # nothing said: gives up at no_speech_s (2 s here) without calling STT
    n0 = nstt(); t0 = time.time(); st = J(8769, "/api/voice/start", {}); r = J(8769, "/api/voice/wait", {"sid": st["sid"]}); tn = time.time() - t0
    check("no speech -> \"I didn't catch that.\" at ~2 s", r.get("error") == "empty" and r.get("text") == "I didn't catch that." and r.get("end") == "nospeech" and 1.8 < tn < 3.5, (r, tn))
    check("no speech: no STT call, spool empty", nstt() == n0 and os.listdir(RUN + "/nova-voice") == [])
    # auto_stop off in nova-voice.json -> old behaviour (tap or cap ends it)
    os.makedirs(T + "/cfgD", exist_ok=True); json.dump({"auto_stop": False}, open(T + "/cfgD/nova-voice.json", "w"))
    st = J(8769, "/api/voice/start", {}); check("auto_stop false honoured", st.get("auto") is False and J(8769, "/api/voice/status")["auto_stop"] is False, st)
    time.sleep(2.4); check("auto_stop off: still recording after silence", J(8769, "/api/voice/status")["recording"] is True)
    r = J(8769, "/api/voice/stop", {}); check("auto_stop off: tap ends it", r.get("end") == "tap", r)
    # no mic
    s = J(8767, "/api/voice/status"); check("no-mic status", s["mic"] is False, s)
    r = J(8767, "/api/voice/start", {}); check("no-mic start -> 'No microphone found.'", r.get("error") == "nomic" and r["text"].startswith("No microphone found."), r)
    a = ask(8767, "what time is it", via="typed"); check("typing unaffected without mic", "Mock reply" in a.get("reply", ""), a)
    # security
    check("voice bad Origin 403", req(8766, "/api/voice/start", {}, {"Origin": "http://evil.com"}) == "HTTP 403")
    check("voice bad Host 403", req(8766, "/api/voice/status", None, {"Host": "evil.com:8766"}) == "HTTP 403")
    check("voice oversize 413", req(8766, "/api/voice/speak", {"text": "x" * 5000}) == "HTTP 413")
finally:
    for p in ps: p.terminate()
    time.sleep(.3); [f.close() for f in (la, lb, lc, ld)]
lg = "".join(open(T + "/%s.log" % n).read() for n in "abcd")
check("no transcript text in logs", not any(w in lg for w in ("burnt peanut", "ramble", "Yes, please", "nothing to see", "weather")), lg)
check("auto stop is logged without text", "take ended by silence" in lg and '"end": "silence"' in lg and '"end": "nospeech"' in lg)
check("audit lines record voice use", lg.count('"tool": "voice"') >= 10 and '"event": "stt"' in lg and '"event": "tts"' in lg)
check("prompt log says via voice", "voice; text not logged" in lg)
check("no key in logs", "sk-test" not in lg)
check("spool empty at end", os.listdir(RUN + "/nova-voice") == [])
open(T + "/last-voice.log", "w").write(lg)
print("\n%d passed, %d failed" % (ok, fail)); sys.exit(1 if fail else 0)
