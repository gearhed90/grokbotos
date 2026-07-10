"""Graphical boot shell (ROADMAP.md 2.1 + Phase 4).

Replaces the plain-text `onboarding_cli.py` loop as the thing sway
actually launches: a local HTTP server (`server.py`) serving a small
single-page kiosk UI (`static/`) that Firefox displays fullscreen.
`onboarding.py`'s connection logic is unchanged and fully reused here --
this package only adds a UI on top of it.
"""
