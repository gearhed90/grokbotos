# 업데이트와 롤백 / Updates & rollback

Grok Bot OS는 이미지 단위로 업데이트된다(bootc). 업데이트가 잘못되면 이전 이미지로 돌아갈 수 있다. / Grok Bot OS updates as a whole image (bootc). If an update goes wrong, you can go back to the previous image.

```bash
sudo bootc status     # 현재/대기/이전 이미지 / booted, staged and rollback images
sudo bootc upgrade    # 새 이미지 받기, 재부팅 후 적용 / fetch the new image; it applies after a reboot
sudo systemctl reboot
sudo bootc rollback   # 이전 이미지로, 재부팅 후 적용 / return to the previous image; it applies after a reboot
```

- 부팅 메뉴(GRUB)에서 이전 항목을 골라 한 번만 이전 버전으로 부팅할 수도 있다. / You can also pick the previous entry in the GRUB boot menu to boot the old version once.
- 릴리스는 날짜 태그로 나온다. 변경 사항은 릴리스 노트에서 본다. / Releases carry dated tags. See the release notes for what changed.

> ⚠️ 업데이트와 롤백은 아직 끝까지 검증되지 않았다. / Upgrade and rollback are not yet verified end to end.
