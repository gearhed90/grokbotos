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
Confirms `quay.io/fedora/fedora-bootc` boots cleanly before any of this
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

1. `build-disk.yml` now runs **automatically** -- it's chained via a
   `workflow_run` trigger off `build.yml` ("Build container image"), so
   every successful push to `main` kicks off both platforms' `qcow2` +
   `anaconda-iso` builds (4 jobs) with no manual step. Just wait for it
   to show up and finish on the Actions tab after `build.yml` goes green.
   To build just one platform on demand instead, trigger `build-disk.yml`
   manually (Actions tab → "Build disk images" → "Run workflow") and pick
   `platform` matching **the machine you'll boot the VM on**, not the
   machine running the CI job -- `amd64` for Intel/most PCs, `arm64` for
   Apple Silicon Macs. `build.yml` publishes both `ghcr.io/head77x/oais`
   (amd64) and `ghcr.io/head77x/oais-arm64` (arm64) as separate images;
   `build-disk.yml` picks the right one automatically either way.
2. Get the built image:
   - **If the S3 secrets below are set**: `build-disk.yml` uploads it
     straight to `s3://$AWS_S3_BUCKET/oais/<disk-type>-<platform>/`
     automatically -- pull it from there (`aws s3 cp` or the S3 console).
     Much faster than the next option for a multi-GB `anaconda-iso`.
   - **Otherwise**: download the `oais-anaconda-iso-<platform>` artifact
     from the completed run's Actions page (slow for a multi-GB file --
     set up the S3 secrets once and this step goes away).
3. Boot the ISO in a VM:
   - **Linux**: `just build-qcow2` locally, or boot the ISO in
     `virt-manager`/`virsh`.
   - **Mac (Apple Silicon)**: install [UTM](https://mac.getutm.app/)
     (`brew install --cask utm`), create a new VM → "Virtualize" (native,
     not "Emulate") → Linux → boot the downloaded arm64 ISO. 4GB+ RAM,
     20GB+ disk (matches `disk_config/disk.toml`'s `minsize`).
4. Run through the Anaconda installer (accept default partitioning is
   fine for a VM; **do** set a user account/password when prompted --
   without one there'd be nothing to log in with).
5. Reboot into the installed system and confirm login works, then:
   ```bash
   sudo bootc status   # should show ghcr.io/head77x/oais(-arm64):latest
   ```

## 5. `bootc switch` rebase test (Phase 1)

From an existing bootc system (e.g. a Fedora Silverblue install), matching
its architecture:
```bash
sudo bootc switch ghcr.io/head77x/oais:latest        # amd64
sudo bootc switch ghcr.io/head77x/oais-arm64:latest  # arm64
sudo systemctl reboot
```
Confirms the "rebase an existing install" path works, not just fresh ISO
installs.

## 6. (Optional) Direct-to-S3 disk image upload

Downloading a multi-GB `anaconda-iso`/`qcow2` through GitHub's artifact
zip UI is the slowest part of the whole `build-disk.yml` run. Set these
repo secrets (Settings → Secrets and variables → Actions) and the
workflow uploads straight to S3 instead, automatically -- no input to
toggle, no artifact download:

| Secret | Required | Notes |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | yes | IAM user/role with `s3:PutObject` on the bucket below |
| `AWS_SECRET_ACCESS_KEY` | yes | |
| `AWS_S3_BUCKET` | yes | bucket name only, no `s3://` prefix |
| `AWS_REGION` | no | defaults to `us-east-1` if unset |

If `AWS_ACCESS_KEY_ID` or `AWS_S3_BUCKET` isn't set, the workflow falls
back to the old GitHub Artifact upload automatically -- nothing breaks by
leaving these unset, uploads are just slower to retrieve.

Uploads land at
`s3://$AWS_S3_BUCKET/oais/<qcow2|anaconda-iso>-<amd64|arm64>/`.

## Why this can't run in the current dev sandbox

Checked at scaffolding time: no `/dev/kvm`, and none of `podman`/`bootc`/
`just`/`qemu-system-x86_64`/`virsh` installed. `bootc-image-builder` also
needs privileged loop-device access that a shared cloud container won't
grant. GitHub Actions runners don't have this problem — `build.yml` and
`build-disk.yml` run on real `ubuntu-24.04` runners, so those two can be
verified purely from CI once secrets are configured (step 3 above).
