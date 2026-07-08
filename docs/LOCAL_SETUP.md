# Steps that require your own machine

This repo's day-to-day scaffolding (Containerfile, build scripts, CI
workflows, docs) can be done from any dev environment, including a cloud
sandbox with no virtualization support. The following `ROADMAP.md` items
cannot be — they need real hardware with KVM and root, so do them from your
own Linux machine.

## 1. Install the toolchain (Phase 0)

```bash
# Fedora / Universal Blue base
sudo dnf install -y podman bootc just git qemu-kvm libvirt virt-install
sudo systemctl enable --now libvirtd
```

Verify:
```bash
sudo bootc status   # should print your current booted image
```

## 2. Boot-test the unmodified base image (Phase 0)

```bash
just build-qcow2       # or: just spawn-vm
just run-vm-qcow2
```
Confirms `ghcr.io/ublue-os/base-main` boots cleanly before any of this
repo's customizations are layered on top.

## 3. First CI build (Phase 1)

Before `build.yml` will push successfully to GHCR:

```bash
COSIGN_PASSWORD="" cosign generate-key-pair
gh secret set SIGNING_SECRET < cosign.key   # or add it via repo Settings > Secrets
git add cosign.pub
git commit -m "Add cosign public key"
```
`cosign.key` must **never** be committed — it's already covered by
`.gitignore`. Push to `main`, then check the Actions tab for a green run and
`ghcr.io/head77x/oais:latest`.

## 4. ISO install test (Phase 1)

1. Trigger `build-disk.yml` (workflow_dispatch, or push to `disk_config/*.toml`).
2. Download the `anaconda-iso` artifact.
3. `just build-qcow2` locally, or boot the ISO in `virt-manager`/`virsh` on
   your machine, and run through the Anaconda installer.
4. Reboot into the installed system and confirm login works.

## 5. `bootc switch` rebase test (Phase 1)

From an existing bootc system (e.g. a Bazzite or Fedora Silverblue install):
```bash
sudo bootc switch ghcr.io/head77x/oais:latest
sudo systemctl reboot
```
Confirms the "rebase an existing install" path works, not just fresh ISO
installs.

## Why this can't run in the current dev sandbox

Checked at scaffolding time: no `/dev/kvm`, and none of `podman`/`bootc`/
`just`/`qemu-system-x86_64`/`virsh` installed. `bootc-image-builder` also
needs privileged loop-device access that a shared cloud container won't
grant. GitHub Actions runners don't have this problem — `build.yml` and
`build-disk.yml` run on real `ubuntu-24.04` runners, so those two can be
verified purely from CI once secrets are configured (step 3 above).
