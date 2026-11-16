# cypher-alpha: Cypher's side of Alpha

Versioned copy of what runs on Alpha (user gearhed) under `~/nova-projects/cypher/` for Cypher
(the grokbotos Pi 5 deck). Until build 15 these files lived only on Alpha.

| dir | unit | what |
| --- | --- | --- |
| `proxy/` | `cypher-brain-proxy.service` | the narrow door to Alpha's llama-server (token, LAN/tailnet only, cameras first), the mind lease + state/journal sync (`cypher_sync.py`) and, since build 15, Cypher's library (`cypher_library.py`, sqlite FTS5 in `~/.local/share/cypher-library/`) |
| `alpha/` | `cypherd-alpha.service` | the standby mind: the deck's own `cypherd.py` with `CYPHER_HOST=alpha`; `install.sh` copies it from this repo |
| `camfeed/` | `cypher-camfeed.service` | sanitized camera events for Cypher (read-only) |

All units are user units with `MemoryMax=128M`.

Install / update on Alpha (after `git pull`):

```bash
cp tools/cypher-alpha/proxy/*.py ~/nova-projects/cypher/proxy/
cp tools/cypher-alpha/proxy/cypher-brain-proxy.service ~/.config/systemd/user/   # if it changed
systemctl --user daemon-reload && systemctl --user restart cypher-brain-proxy
~/nova-projects/cypher/alpha/install.sh && systemctl --user restart cypherd-alpha
```

Tests (no GPU, no network): `for t in tools/cypher-alpha/tests/test_*.py; do python3 "$t"; done`
