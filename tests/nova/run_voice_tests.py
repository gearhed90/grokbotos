#!/usr/bin/env python3
"""Voice (step 6) tests: mocked xAI /stt + /tts, fake pw-record/pw-play, generated WAV. No mic, no sound."""
import json, os, stat, subprocess, sys, tempfile, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "build_files", "rpi5", "nova")
os.environ["NOVA_SYS_KEY_FILE"] = ""
T = tempfile.mkdtemp(); RUN = T + "/run"; os.makedirs(RUN, mode=0o700)
key = T + "/key"; open(key, "w").write("sk-test"); os.chmod(key, 0o600)
WAV = T + "/sample.wav"; subprocess.check_call([sys.executable, HERE + "/make_wav.py", WAV])
NEXT = T + "/next_transcript"; RECLOG = T + "/rec.log"; open(RECLOG, "w").close()
base = dict(os.environ, NOVA_API_BASE="http://127.0.0.1:8799/v1", NOVA_DRY_RUN="1", NOVA_KEY_FILE=key,
            GROKBOT_API_SOCK=T + "/none.sock", XDG_RUNTIME_DIR=RUN, NOVA_TEST_WAV=WAV, NOVA_TEST_RECLOG=RECLOG,
            NOVA_REC_CMD="%s %s/fake_rec.py {out}" % (sys.executable, HERE),
            NOVA_PLAY_CMD="%s %s/fake_play.py {in}" % (sys.executable, HERE), NOVA_TEST_SPK="1")
A = dict(base, NOVA_PORT="8766", NOVA_TEST_MIC="1", NOVA_REC_CAP="1.5", NOVA_VOICE_CFG=T + "/cfgA/nova-voice.json")
Bn = dict(base, NOVA_PORT="8767", NOVA_TEST_MIC="0", NOVA_VOICE_CFG=T + "/cfgB/nova-voice.json")
la, lb = open(T + "/a.log", "w"), open(T + "/b.log", "w")
ps = [subprocess.Popen([sys.executable, HERE + "/mock_xai.py"], env=dict(os.environ, MOCK_STT_NEXT=NEXT)),
      subprocess.Popen([sys.executable, ROOT + "/novad.py"], env=A, stderr=la),
      subprocess.Popen([sys.executable, ROOT + "/novad.py"], env=Bn, stderr=lb)]
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
    check("status not recording? (still awaiting stop)", J(8766, "/api/voice/status")["recording"] is True)
    r = J(8766, "/api/voice/stop", {}); check("stop after cap: capped transcript", r.get("capped") is True and r.get("secs") == 1.5, r)
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
    # no mic
    s = J(8767, "/api/voice/status"); check("no-mic status", s["mic"] is False, s)
    r = J(8767, "/api/voice/start", {}); check("no-mic start -> 'No microphone found.'", r.get("error") == "nomic" and r["text"] == "No microphone found.", r)
    a = ask(8767, "what time is it", via="typed"); check("typing unaffected without mic", "Mock reply" in a.get("reply", ""), a)
    # security
    check("voice bad Origin 403", req(8766, "/api/voice/start", {}, {"Origin": "http://evil.com"}) == "HTTP 403")
    check("voice bad Host 403", req(8766, "/api/voice/status", None, {"Host": "evil.com:8766"}) == "HTTP 403")
    check("voice oversize 413", req(8766, "/api/voice/speak", {"text": "x" * 5000}) == "HTTP 413")
finally:
    for p in ps: p.terminate()
    time.sleep(.3); la.close(); lb.close()
lg = open(T + "/a.log").read() + open(T + "/b.log").read()
check("no transcript text in logs", not any(w in lg for w in ("burnt peanut", "ramble", "Yes, please", "nothing to see")), lg)
check("audit lines record voice use", lg.count('"tool": "voice"') >= 10 and '"event": "stt"' in lg and '"event": "tts"' in lg)
check("prompt log says via voice", "voice; text not logged" in lg)
check("no key in logs", "sk-test" not in lg)
check("spool empty at end", os.listdir(RUN + "/nova-voice") == [])
open(T + "/last-voice.log", "w").write(lg)
print("\n%d passed, %d failed" % (ok, fail)); sys.exit(1 if fail else 0)
