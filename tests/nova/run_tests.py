#!/usr/bin/env python3
"""DRY_RUN end-to-end tests for novad OS tools and the confirm flow."""
import json, os, subprocess, sys, tempfile, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "build_files", "rpi5", "nova")
os.environ["NOVA_SYS_KEY_FILE"] = ""
T = tempfile.mkdtemp(); SOCK = T + "/api.sock"
os.makedirs(T + "/webapps/files"); open(T + "/webapps/files/manifest.json", "w").write("{}")
os.makedirs(T + "/webapps/settings"); open(T + "/webapps/settings/manifest.json", "w").write("{}")
os.makedirs(T + "/thermal/thermal_zone0"); open(T + "/thermal/thermal_zone0/temp", "w").write("58950\n")
key = T + "/key"; open(key, "w").write("sk-test"); os.chmod(key, 0o600)
env = dict(os.environ, NOVA_API_BASE="http://127.0.0.1:8799/v1", NOVA_DRY_RUN="1", NOVA_KEY_FILE=key,
           GROKBOT_API_SOCK=SOCK, NOVA_SYS_APPS=T + "/webapps", NOVA_USER_APPS=T + "/none",
           NOVA_THERMAL=T + "/thermal", NOVA_TEST_SAVED="Home,Saved5G", NOVA_CONFIRM_TTL="2")
gl = open(T + "/gbd.log", "w"); nl = open(T + "/novad.log", "w")
ps = [subprocess.Popen([sys.executable, HERE + "/mock_xai.py"]),
      subprocess.Popen([sys.executable, HERE + "/mock_grokbotd.py", SOCK], stdout=gl),
      subprocess.Popen([sys.executable, ROOT + "/novad.py"], env=env, stderr=nl)]
time.sleep(1.2)
B = "http://127.0.0.1:8765"
def post(path, body, hdr=None):
    rq = urllib.request.Request(B + path, json.dumps(body).encode(), {"Content-Type": "application/json", **(hdr or {})})
    try:
        return urllib.request.urlopen(rq).read().decode()
    except urllib.error.HTTPError as e:
        return "HTTP %d" % e.code
def ask(p):
    return [json.loads(l) for l in post("/api/ask", {"prompt": p}).splitlines() if l.strip()][-1]
def tool(n, a=None): return ask("TOOL %s %s" % (n, json.dumps(a or {})))
def conf(i, yes=True): return json.loads(post("/api/confirm", {"id": i, "yes": yes}))
ok = fail = 0
def check(name, cond, info=""):
    global ok, fail
    ok += bool(cond); fail += not cond
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(info)[:300]))
try:
    r = tool("system_info"); check("system_info reads storage/temp/wifi", "cpu_temp_c" in r.get("reply", "") and "59.0" in r["reply"] and "Home" in r["reply"], r)
    r = tool("updates_status"); check("updates_status read-only", "44.20261023.0" in r.get("reply", ""), r)
    r = tool("get_volume"); check("get_volume", "30" in r.get("reply", ""), r)
    r = tool("get_brightness"); check("get_brightness", "48" in r.get("reply", ""), r)
    r = tool("wifi_status"); check("wifi_status", "Saved5G" in r.get("reply", "") and "saved" in r["reply"], r)
    r = tool("set_volume", {"change": 10}); check("volume +10 runs directly", "40%" in r.get("reply", ""), r)
    r = tool("set_volume", {"muted": True}); check("mute runs directly", "muted" in r.get("reply", ""), r)
    r = tool("set_volume", {"percent": 100}); check("volume 30->100 needs confirm", "confirm" in r, r)
    c = conf(r["confirm"]["id"]); check("confirm yes runs volume", "100%" in c.get("reply", ""), c)
    c = conf(r["confirm"]["id"]); check("replay refused", c.get("error") == "gone", c)
    r = tool("set_volume", {"percent": 150}); check("volume out of range rejected", "0 to 100" in r.get("reply", ""), r)
    r = tool("set_brightness", {"percent": 60}); check("brightness 48->60 direct", "60%" in r.get("reply", ""), r)
    r = tool("set_brightness", {"percent": 100}); check("brightness 48->100 needs confirm", "confirm" in r, r)
    c = conf(r["confirm"]["id"], False); check("confirm no declines", "won't" in c.get("reply", ""), c)
    r = tool("open_app", {"name": "files"}); check("open_app files", "opened" in r.get("reply", ""), r)
    r = tool("open_app", {"name": "bash"}); check("open_app non-allowlisted refused", "not allowed" in r.get("reply", ""), r)
    r = tool("close_app", {"name": "nova-shell"}); check("close nova-shell refused", "not allowed" in r.get("reply", ""), r)
    r = tool("close_app", {"name": "files"}); check("close_app needs confirm", "confirm" in r, r)
    c = conf(r["confirm"]["id"]); check("close_app confirmed", "Closed files" in c.get("reply", ""), c)
    r = tool("close_app", {"name": "settings"}); check("close app not open", "not open" in r.get("reply", ""), r)
    r = tool("wifi_connect", {"ssid": "Saved5G"}); check("wifi saved needs confirm", "confirm" in r, r)
    c = conf(r["confirm"]["id"]); check("wifi saved confirmed", "Connected to Saved5G" in c.get("reply", ""), c)
    r = tool("wifi_connect", {"ssid": "CoffeeOpen"}); check("wifi open needs confirm", "confirm" in r and "open network" in r["confirm"]["text"], r)
    r = tool("wifi_connect", {"ssid": "Neighbor"}); check("wifi secured unsaved -> Settings", "needs_password" in r.get("reply", ""), r)
    r = tool("wifi_connect", {"ssid": "Neighbor", "password": "hunter2hunter2"}); check("wifi password arg refused", "Settings" in r.get("reply", ""), r)
    r = tool("wifi_connect", {"ssid": "Nowhere"}); check("wifi unknown ssid", "not in range" in r.get("reply", ""), r)
    for a in ("lock", "restart", "shutdown"):
        r = tool("power", {"action": a}); check("power %s needs confirm" % a, "confirm" in r, r)
    c = conf(r["confirm"]["id"]); check("shutdown confirmed (dry run)", "Shutting down" in c.get("reply", ""), c)
    r = tool("power", {"action": "suspend"}); check("power bad action", "lock, restart or shutdown" in r.get("reply", ""), r)
    r = tool("run_shell", {"cmd": "id"}); check("unknown tool refused", "unknown tool" in r.get("reply", ""), r)
    r = tool("power", {"action": "lock"}); time.sleep(2.5)
    c = conf(r["confirm"]["id"]); check("expired confirm refused", c.get("error") == "expired", c)
    c = conf("bogus"); check("bogus id refused", c.get("error") == "gone", c)
    check("confirm bad Origin 403", post("/api/confirm", {"id": "x", "yes": True}, {"Origin": "http://evil.com"}) == "HTTP 403")
    check("confirm bad Host 403", post("/api/confirm", {"id": "x", "yes": True}, {"Host": "evil.com:8765"}) == "HTTP 403")
    check("confirm oversize 413", post("/api/confirm", {"id": "x" * 2000, "yes": True}) == "HTTP 413")
finally:
    for p in ps: p.terminate()
    time.sleep(.3); gl.close(); nl.close()
logtxt = open(T + "/novad.log").read(); gbd = open(T + "/gbd.log").read()
check("no grokbotd write reached socket", not any(w in gbd for w in ("audio.set", "display.set_brightness", "network.wifi.connect", "power.action")), gbd)
check("dry-run writes logged", "DRY-RUN rpc: power.action" in logtxt and "DRY-RUN swaymsg kill con_id 21" in logtxt)
check("audit lines present", logtxt.count("AUDIT") > 20)
check("no password or key in log", "hunter2" not in logtxt and "sk-test" not in logtxt)
open(T + "/last-novad.log", "w").write(logtxt)
print("\n%d passed, %d failed" % (ok, fail)); sys.exit(1 if fail else 0)
