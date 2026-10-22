# Skill: visual verification

Every PR that changes something on screen (sway config, docks, wallpaper, launcher, Grok Bot window, first boot, installer) needs screenshots.

1. Boot the changed image in a VM (`vm-testing.md`).
2. Take a screenshot of **every changed screen** with `tools/vm/mon.py shot <name>.png`. Use names that say what they show, e.g. `dock-left-labels.png`.
3. Open each screenshot and check it yourself. A file existing proves nothing. Check the following:
   - there are no icons on the desktop, only widgets
   - top/bottom docks show icons only; left/right docks show icons or icons plus labels
   - Grok Bot is on workspace 1, and windows are not hidden under the docks
   - text appears in both Korean and English where it is user-facing
4. Attach the screenshots to the PR. List any screen or hardware you could not check (HiDPI, multiple monitors, real hardware).
5. Before and after pairs help reviewers when you change an existing screen.
