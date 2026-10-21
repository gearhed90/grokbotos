# 이 머신에서만 할 일

Containerfile, 스크립트, CI, 문서는 가상화가 없는 환경에서도 고칠 수 있다. 아래는 KVM과 root가 있는 본인 리눅스 머신, 또는 Apple Silicon Mac + UTM이 필요하다.

기본 이미지의 첫 화면은 Grok Bot 0.71.2다. amd64와 arm64 둘 다 RPM을 넣는다. 이 환경에서 그 화면을 부팅해 보지는 않았다. 플레이스홀더 안내 페이지는 `GROKBOT_DISABLE_BUNDLED_APP=1`로 빌드했을 때만 나온다. 주소와 체크섬은 [`GROKBOT_APP.md`](./GROKBOT_APP.md). 하드웨어는 [`HARDWARE.md`](./HARDWARE.md).

## 1. 도구 설치

```bash
# Fedora / Universal Blue
sudo dnf install -y podman bootc just git qemu-kvm libvirt virt-install
sudo systemctl enable --now libvirtd
```

확인:

```bash
sudo bootc status
```

## 2. 이미지 빌드

```bash
just build
```

이 빌드는 `downloads.cursor.com`에서 아키텍처에 맞는 Grok Bot RPM을 받는다. 체크섬이 다르면 실패한다. 네트워크가 필요하다.

플레이스홀더 안내 페이지만 넣으려면:

```bash
GROKBOT_DISABLE_BUNDLED_APP=1 just build
```

웹 주소는 그 플레이스홀더 빌드에서만 쓴다. RPM을 넣는 기본 빌드에서는 무시된다.

```bash
GROKBOT_DISABLE_BUNDLED_APP=1 \
GROKBOT_WEB_URL='https://확인된-주소' \
just build
```

디스크 이미지:

```bash
just build-qcow2
just build-iso
```

로컬 `just build-iso`는 `disk_config/iso.toml`의 kickstart를 그대로 쓴다. 그 주소는 `ghcr.io/head77x/grokbotos:latest`다. arm64 머신에서 로컬 ISO를 만들면, CI의 `build-disk.yml`이 하듯이 설치 대상 이미지 이름을 `grokbotos-arm64`로 바꾼 뒤에 빌드해야 한다. 문자열 자체는 워크플로가 sed하는 기준이라 파일에서 지우면 CI가 깨진다.

## 3. GHCR 푸시

`build.yml`은 `main`에 푸시될 때 `ghcr.io/head77x/grokbotos`(amd64)와 `ghcr.io/head77x/grokbotos-arm64`(arm64)를 올린다. 이미지 이름은 제품 이름과 다르다. `grokbotos.env`의 `IMAGE_NAME=grokbotos`를 바꾸지 않는다.

서명이 필요하면:

```bash
COSIGN_PASSWORD="" cosign generate-key-pair
gh secret set SIGNING_SECRET < cosign.key
git add cosign.pub
```

`cosign.key`는 커밋하지 않는다. `.gitignore`에 있다.

## 4. ISO 설치

1. `main`에서 `build.yml`이 성공하면 `build-disk.yml`이 이어서 qcow2와 anaconda ISO를 amd64, arm64로 만든다. 한 아키텍처만 만들려면 Actions에서 "Build disk images"를 수동 실행하고, **VM을 띄울 머신**의 아키텍처를 고른다. Apple Silicon은 `arm64`, 일반 PC는 `amd64`.
2. 이미지를 받는다.
   - S3 시크릿이 있으면 `s3://$AWS_S3_BUCKET/grokbotos/<qcow2|anaconda-iso>-<amd64|arm64>/`.
   - 없으면 Actions 아티팩트 `grokbotos-anaconda-iso-<platform>`.
3. 부팅한다.
   - Linux: `virt-manager` 또는 `just run-vm-qcow2`.
   - Apple Silicon: [UTM](https://mac.getutm.app/)에서 Virtualize → Linux. RAM 4GB 이상, 디스크 20GB 이상 (`disk_config/disk.toml`의 `minsize`).
4. Anaconda에서 사용자와 비밀번호를 만든다. 이 계정은 복구용이다. 화면을 쓰는 계정은 이미지 안의 `grokbot`이고, 비밀번호 없이 tty1에 자동 로그인된다.
5. 재부팅 후 확인할 것:
   - 패널이나 데스크톱 없이 Grok Bot만 보이는지. 안내 페이지가 보이면 그 이미지에 RPM이 없다.
   - `Alt+Space`로 앱 목록이 뜨는지. `Alt+G`로 돌아오는지. UTM에서 Super가 안 먹으면 Alt를 쓴다.
   - `Ctrl+Alt+F2`로 관리자 로그인 뒤:

```bash
sudo bootc status
# ghcr.io/head77x/grokbotos:latest  또는  ghcr.io/head77x/grokbotos-arm64:latest

sudo cat ~grokbot/.local/share/grokbot/shell.log
```

이 전환 이후 이미지는 아직 이렇게 확인해 본 적이 없다.

## 5. `bootc switch`

이미 bootc를 쓰는 시스템에서, 아키텍처를 맞춰:

```bash
sudo bootc switch ghcr.io/head77x/grokbotos:latest        # amd64
sudo bootc switch ghcr.io/head77x/grokbotos-arm64:latest  # arm64
sudo systemctl reboot
```

이 경로는 한 번도 확인하지 않았다.

## 6. S3로 디스크 이미지 받기

멀티 GB ISO를 GitHub 아티팩트로 받으면 느리다. 저장소 시크릿을 넣으면 `build-disk.yml`이 S3로 올린다.

| 시크릿 | 필수 | 설명 |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | 예 | 버킷에 `s3:PutObject` |
| `AWS_SECRET_ACCESS_KEY` | 예 | |
| `AWS_S3_BUCKET` | 예 | 버킷 이름만. `s3://` 없이 |
| `AWS_REGION` | 아니오 | 없으면 `us-east-1` |

없으면 예전처럼 아티팩트로 올라간다. 경로는 `s3://$AWS_S3_BUCKET/grokbotos/<qcow2|anaconda-iso>-<amd64|arm64>/`. 이 접두사 `grokbotos`는 이미지 이름과 맞추어 두었고, 제품 이름으로 바꾸지 않았다.

## 7. 부팅 뒤에 더 볼 것

RPM은 이미 기본 빌드에 들어 있다. 아래는 그 이미지를 실제로 켠 뒤에 하는 일이다. 여기서는 하지 않았다.

1. 첫 화면이 Grok Bot 로그인 또는 구독인지 본다. 안내 페이지가 보이면 `GROKBOT_DISABLE_BUNDLED_APP=1`로 만든 이미지다.
2. 재부팅 뒤 세션이 `/var/home/grokbot`에 남는지 본다.
3. `grokbot-install flatpak org.mozilla.firefox` 같은 설치가 사용자 권한으로 되는지 본다. 네트워크가 필요하다.
4. `Alt+Space`로 그 앱을 열고 `Alt+G`로 Grok Bot에 돌아오는지 본다.
5. 하드웨어 항목은 [`HARDWARE.md`](./HARDWARE.md)의 표대로 적는다. 안 본 칸은 미확인이다.

## 이 개발 샌드박스에서 안 되는 이유

`/dev/kvm`이 없고, podman으로 fedora-bootc 이미지를 만들어 부팅할 수 없다. `bootc-image-builder`는 루프 장치와 특권이 필요하다. GitHub Actions의 `build.yml`과 `build-disk.yml`은 `ubuntu-24.04` / `ubuntu-24.04-arm`에서 돈다. `check.yml`은 셸 테스트와 Justfile만 돈다.
