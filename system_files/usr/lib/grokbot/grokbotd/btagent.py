"""BlueZ pairing agent (org.bluez.Agent1) that answers through the consent prompt.

bluetooth.pair runs the Pair call on its own system-bus connection with
this agent registered for that connection only, so BlueZ asks *us* (not
some other agent) for the PIN/passkey of that one pairing, and only while
it runs. The answers:

  RequestConfirmation(passkey)  -> consent prompt "does the device show N?"
  RequestAuthorization          -> consent prompt
  DisplayPasskey/DisplayPinCode -> consent prompt telling the user what to type
  RequestPinCode/RequestPasskey -> the pin given to bluetooth.pair, else Rejected
  AuthorizeService              -> allowed only for the device being paired

Every answer is decided by Handler (pure Python, unit tested). Gio is only
imported when a real pairing runs.
"""
import re
import threading

from .backends import BackendError

AGENT_PATH = "/org/grokbot/btagent"
PIN_RE = re.compile(r"^[0-9A-Za-z]{1,16}$")

INTROSPECT = """<node><interface name="org.bluez.Agent1">
<method name="Release"/>
<method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
<method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
<method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
<method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
<method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
<method name="RequestAuthorization"><arg type="o" direction="in"/></method>
<method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
<method name="Cancel"/>
</interface></node>"""


class Rejected(Exception):
    """Maps to org.bluez.Error.Rejected."""


class Handler:
    """Answers Agent1 calls for one pairing.

    confirm(kind, text_ko, text_en, passkey) -> bool asks the user (consent prompt);
    notify(kind, text_ko, text_en, passkey) shows a code without waiting for an answer.
    """

    def __init__(self, device_path, name, pin, confirm, notify):
        self.device_path, self.name, self.pin = device_path, name or "", pin
        self.confirm, self.notify = confirm, notify
        self.asked = []

    def _mine(self, dev):
        if dev != self.device_path:
            raise Rejected("not the device being paired")

    def call(self, method, args):
        self.asked.append(method)
        if method in ("Release", "Cancel"):
            return None
        dev = args[0] if args else None
        n = self.name or dev
        if method == "RequestConfirmation":
            self._mine(dev)
            pk = "%06d" % int(args[1])
            if not self.confirm("confirm", "%s 기기에 %s 이(가) 보이나요? 같으면 허용하세요." % (n, pk),
                                "Does %s show %s? Allow only if it matches." % (n, pk), pk):
                raise Rejected("passkey not confirmed")
            return None
        if method == "RequestAuthorization":
            self._mine(dev)
            if not self.confirm("authorize", "%s 기기와 페어링할까요?" % n, "Pair with %s?" % n, None):
                raise Rejected("not authorized")
            return None
        if method in ("DisplayPasskey", "DisplayPinCode"):
            self._mine(dev)
            code = "%06d" % int(args[1]) if method == "DisplayPasskey" else str(args[1])
            self.notify("display", "%s 기기에서 %s 을(를) 입력하고 Enter를 누르세요." % (n, code),
                        "Type %s on %s, then press Enter." % (code, n), code)
            return None
        if method in ("RequestPinCode", "RequestPasskey"):
            self._mine(dev)
            if not self.pin:
                raise Rejected("the device needs a PIN; pair again with pin")
            if method == "RequestPasskey":
                if not self.pin.isdigit() or int(self.pin) > 999999:
                    raise Rejected("passkey must be 0-999999")
                return int(self.pin)
            return self.pin
        if method == "AuthorizeService":
            self._mine(dev)
            return None
        raise Rejected("unknown agent method")


def check_pin(pin):
    if pin is None or pin == "":
        return None
    if not isinstance(pin, str) or not PIN_RE.match(pin):
        raise BackendError("pin: 1-16 letters or digits")
    return pin


def pair(device_path, handler, timeout=60):
    """Device1.Pair with Handler as this connection's agent. Raises BackendError."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
    except (ImportError, ValueError):
        raise BackendError("bluetooth: PIN/passkey pairing needs python3-gobject")
    ctx = GLib.MainContext.new()
    ctx.push_thread_default()
    try:
        bus = Gio.DBusConnection.new_for_address_sync(
            Gio.dbus_address_get_for_bus_sync(Gio.BusType.SYSTEM, None),
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)
        node = Gio.DBusNodeInfo.new_for_xml(INTROSPECT)
        loop = GLib.MainLoop.new(ctx, False)
        out_sig = {"RequestPinCode": "(s)", "RequestPasskey": "(u)"}

        def on_call(_c, _s, _p, _i, method, params, inv):
            # Prompts block, so answer from a worker thread; inv is thread safe.
            def work():
                try:
                    r = handler.call(method, list(params.unpack()))
                    inv.return_value(GLib.Variant(out_sig[method], (r,)) if method in out_sig else None)
                except Rejected as e:
                    inv.return_dbus_error("org.bluez.Error.Rejected", str(e))
                except Exception as e:  # noqa: BLE001 - never leave BlueZ waiting
                    inv.return_dbus_error("org.bluez.Error.Rejected", str(e)[:200])
            threading.Thread(target=work, daemon=True).start()

        reg = bus.register_object(AGENT_PATH, node.interfaces[0], on_call, None, None)
        res = {}
        try:
            bus.call_sync("org.bluez", "/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                          GLib.Variant("(os)", (AGENT_PATH, "KeyboardDisplay")), None, 0, 5000, None)

            def done(c, r):
                try:
                    c.call_finish(r)
                    res["ok"] = True
                except GLib.Error as e:
                    res["err"] = e.message
                loop.quit()
            bus.call("org.bluez", device_path, "org.bluez.Device1", "Pair", None, None, 0,
                     timeout * 1000, None, done)
            loop.run()
        finally:
            try:
                bus.call_sync("org.bluez", "/org/bluez", "org.bluez.AgentManager1", "UnregisterAgent",
                              GLib.Variant("(o)", (AGENT_PATH,)), None, 0, 5000, None)
            except GLib.Error:
                pass
            bus.unregister_object(reg)
            bus.close_sync(None)
    except GLib.Error as e:
        from .bluetooth import _friendly
        raise BackendError("bluetooth: %s" % _friendly(e.message))
    finally:
        ctx.pop_thread_default()
    if "err" in res:
        from .bluetooth import _friendly
        raise BackendError("bluetooth: %s" % _friendly(res["err"]))
