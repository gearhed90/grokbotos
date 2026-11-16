# avatar-v1: the deck's flat avatar (retired in build 16)

Until build 16 the grokbotos deck (Raspberry Pi 5, Touch Display 2) showed Cypher as a flat 2D
avatar: a colored shape with two dark eyes that blinked, looked around, typed, thought and slept.
Build 16 replaced it with Cypher's 3D apartment (`build_files/rpi5/nova/apartment.py`,
`apartment_gl.py`). Zack asked for the avatar to be removed from the deck completely and kept here
intact so it can be reused somewhere else later. Archived by Grok Bot on 2026-11-16.

Nothing in the deck image loads these files any more (the image no longer installs them and
`tests/test-rpi5-nova.sh` / `tests/cypher/test_cypherd_build16.py` fail if a deck file imports them).

## What is here

| File | What it was |
| --- | --- |
| `nova/avatar.py` | The cairo avatar: states (idle, listening, thinking, looking, working, typing, sleeping), blinking, eye motion, the sleeping z's. |
| `nova/avatar_shapes.py` | 13 shapes (capsule, the original green horizontal pill, plus circle, blob, diamond, sparkle, clover, bean, scallop, drop, triangle, house, star, hexagon) x 11 colors; saved choice in `~/.config/grokbot/avatar.json` (`NOVA_AVATAR_CFG`). |
| `nova/glview.py` | The GLES2 fragment-shader avatar (`GLView`, `GLAvatar`) used on the Pi's GPU, with the cairo one as fallback. |
| `nova/shell.html` | The original web version of the screen (served by novad at `/`), with its CSS and canvas avatar. |
| `nova/lock.html` | The original web lock screen with the sleeping avatar (the native `lockscene.py` was based on it). |
| `nova/nova_native.build16-pre-removal.py` | `nova_native.py` as it was right before removal: the look picker (shape grid, color row, `button#look`, `#picker` CSS), `--shape/--color/--blink/--view`, the GLView path and the build-16 avatar fallback. |
| `nova/lockscene.with-avatar.py` | The lock scene with the sleeping avatar on the left. |
| `nova/novad.with-avatar.py` | novad with the `set_avatar` tool (shape and color), `GET/POST /api/avatar` and the `/` + `/shell.html` routes. |
| `nova/cypher_panels.with-avatar.py` | The HUD with `AVATAR_H` / `avatar_h()` sizing and `render_png(avatar=True)`. |
| `tests/test_units.with-avatar.py`, `tests/run_tests.with-avatar.py` | The avatar's unit and HTTP tests (shapes, colors, eyes on every shape, picker, `/api/avatar`). |

What stayed on the deck: his color. `build_files/rpi5/nova/look.py` keeps the same 11 colors and the
same file (`~/.config/grokbot/avatar.json`, color only; an old `shape` key is ignored). It tints the
apartment's placeholder body. cypherd's `set_avatar_color` action and novad's `set_color` tool /
`POST /api/color` write it.

## How to restore it on the deck

1. `git mv archive/avatar-v1/nova/{avatar.py,avatar_shapes.py,glview.py,shell.html,lock.html} build_files/rpi5/nova/`
2. Put `avatar.py avatar_shapes.py glview.py shell.html` back in the install loop in `build_files/rpi5-nova.sh`.
3. Restore the picker, the GLView path and the view switch in `nova_native.py` from
   `nova/nova_native.build16-pre-removal.py` (or `git show d505c4b:build_files/rpi5/nova/nova_native.py`),
   and if wanted the avatar lock scene, novad routes/tool and panel sizing from the `*.with-avatar.py` copies
   (same content as commit `d505c4b`).
4. Bring back the `apartment` feature flag in `cypherd.py` / `cypher-limits.json` if both views should coexist.
5. Restore the matching tests from `tests/` here and drop the "avatar is archived" checks in
   `tests/test-rpi5-nova.sh` and `tests/cypher/test_cypherd_build16.py`.

The same files are also in a tarball on Alpha: `~/nova-work/backups/avatar-v1-20261116.tgz`.
