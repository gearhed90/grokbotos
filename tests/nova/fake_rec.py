#!/usr/bin/env python3
"""Stand-in for pw-record: writes the sample WAV to argv[1], then waits for SIGINT like pw-record."""
import shutil, signal, sys, time, os
shutil.copy(os.environ["NOVA_TEST_WAV"], sys.argv[1])
open(os.environ["NOVA_TEST_RECLOG"], "a").write("REC start\n")
signal.signal(signal.SIGINT, lambda *a: (open(os.environ["NOVA_TEST_RECLOG"], "a").write("REC stop\n"), sys.exit(0)))
while True: time.sleep(.05)
