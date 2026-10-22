"""audio.devices.list / audio.set_default / audio.set id: PipeWire via pw-dump + wpctl."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "system_files", "usr", "lib", "grokbot"))
from grokbotd import audiodev, media, procs, writes  # noqa: E402
from grokbotd.backends import BackendError  # noqa: E402


def node(i, cls, name, desc, api="alsa"):
    return {"id": i, "type": "PipeWire:Interface:Node",
            "info": {"props": {"media.class": cls, "node.name": name, "node.description": desc, "device.api": api}}}


DUMP = [
    {"id": 0, "type": "PipeWire:Interface:Core"},
    node(40, "Audio/Sink", "alsa_output.pci.analog", "Built-in Audio Analog Stereo"),
    node(41, "Audio/Source", "alsa_input.pci.analog", "Built-in Audio Mic"),
    node(55, "Audio/Sink", "bluez_output.AA_BB", "WH-1000XM4", api="bluez5"),
    node(60, "Stream/Output/Audio", "firefox", "Firefox"),
    {"id": 30, "type": "PipeWire:Interface:Metadata", "props": {"metadata.name": "default"},
     "metadata": [{"subject": 0, "key": "default.audio.sink", "type": "Spa:String:JSON",
                   "value": {"name": "bluez_output.AA_BB"}},
                  {"subject": 0, "key": "default.audio.source", "value": "{\"name\": \"alsa_input.pci.analog\"}"}]},
]
VOL = {"40": "Volume: 0.50\n", "41": "Volume: 0.80 [MUTED]\n", "55": "Volume: 0.30\n"}


class AudioDevicesTest(unittest.TestCase):
    def setUp(self):
        self.cmds = []

        def run(cmd, timeout=3):
            if cmd == ["pw-dump"]:
                return json.dumps(DUMP)
            if cmd[:2] == ["wpctl", "get-volume"]:
                return VOL.get(cmd[2], "Volume: 1.00\n")
            return None

        def wrun(cmd, timeout=10, what=None):
            self.cmds.append(cmd)
            return ""
        self.p = [mock.patch.object(procs, "run", run), mock.patch.object(writes, "_run", wrun)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_devices(self):
        r = audiodev.audio_devices({})
        self.assertTrue(r["available"])
        outs = r["outputs"]
        self.assertEqual([o["id"] for o in outs], [55, 40])  # default first, streams excluded
        self.assertTrue(outs[0]["default"] and outs[0]["bluetooth"])
        self.assertEqual(outs[1]["volume_percent"], 50)
        self.assertEqual(r["inputs"][0]["id"], 41)
        self.assertTrue(r["inputs"][0]["default"] and r["inputs"][0]["muted"])

    def test_unavailable(self):
        with mock.patch.object(procs, "run", lambda c, timeout=3: None):
            self.assertEqual(audiodev.audio_devices({})["available"], False)
            with self.assertRaises(BackendError):
                audiodev.audio_set_default({"id": 40})

    def test_set_default(self):
        audiodev.audio_set_default({"id": 40})
        self.assertEqual(self.cmds, [["wpctl", "set-default", "40"]])
        with self.assertRaises(BackendError):
            audiodev.audio_set_default({"id": 60})  # a stream, not a device
        with self.assertRaises(BackendError):
            audiodev.audio_set_default({"id": 999})

    def test_set_per_device(self):
        with mock.patch.object(media, "audio_status", lambda p: {}):
            writes.audio_set({"id": 55, "volume_percent": 35, "muted": False})
            self.assertEqual(self.cmds, [["wpctl", "set-volume", "-l", "1.0", "55", "35%"],
                                         ["wpctl", "set-mute", "55", "0"]])
            with self.assertRaises(BackendError):
                writes.audio_set({"id": 7, "muted": True})
            self.cmds.clear()
            writes.audio_set({"target": "input", "muted": True})
            self.assertEqual(self.cmds, [["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "1"]])


if __name__ == "__main__":
    unittest.main()
