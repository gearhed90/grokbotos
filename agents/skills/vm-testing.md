# Skill: build and boot the image in a VM

The tools are in [`tools/vm/`](../../tools/vm/). Work files go in `$GBVM_DIR` (default `<repo>/.vm`, git-ignored). For the general setup, see [`docs/LOCAL_SETUP.md`](../../docs/LOCAL_SETUP.md).

1. Run the tests: `bash tests/run-tests.sh`
2. Build: `just build` (gives `localhost/grokbotos:latest`; override with `GBVM_IMAGE`).
3. Make a disk without an installer (UEFI):
   ```bash
   sudo -E tools/vm/mkdisk.sh            # -> .vm/disk.qcow2
   # optional local-only recovery user, never commit real values:
   GBVM_TEST_USER=... GBVM_TEST_PASS=... sudo -E tools/vm/mkdisk.sh
   ```
4. Boot: `sudo -E tools/vm/vm.sh .vm/disk.qcow2 uefi` (or `secboot`, `bios`). It uses KVM when available and TCG otherwise (`GBVM_ACCEL=tcg` forces TCG).
5. Drive it:
   - `tools/vm/mon.py shot NAME.png`: screenshot into `.vm/shots/`
   - `tools/vm/mon.py type 'text'`: type text and press Enter (`KD=0.2` sets a slower per-key delay)
   - `tools/vm/mon.py sendkey ctrl-alt-f3`: send any HMP command
   - `tools/vm/qmp.py click X Y`: click at guest pixel coordinates (1280x800)
   - `tools/vm/mon.py quit`: stop the VM
6. Serial log: `.vm/serial-<mode>.log`.

Pitfalls:
- If the VM runs under sudo, the sockets are root-owned. Run `mon.py`/`qmp.py` with `sudo -E` too.
- Under TCG, keys can be delayed or dropped. Type slowly, then check with a screenshot.
- Screenshots arrive at 1280x800. If you scale them down, scale click coordinates back up.
