#!/usr/bin/env python3
"""Stand-in for pw-play: checks the file is a WAV and logs its size."""
import os, sys, wave
w = wave.open(sys.argv[1]); open(os.environ["NOVA_TEST_RECLOG"], "a").write("PLAY %d frames\n" % w.getnframes())
