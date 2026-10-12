"""Minimal two-way OSC link to an X32 - one UDP socket for queries, writes and the /xremote event
stream (the console answers to the sender's port, so all of it has to share one socket).

X32 specifics used by this plugin (see the Unofficial X32/M32 OSC Remote Protocol, P.-G. Maillot):
  /config/userctrl/<A|B|C>/btn/<5..12>   string  assignment of an assign button
  /-stat/userpar/<id>/value               int     button pressed (127) / released (0) - pushed to
                                                  /xremote subscribers; writing it sets the LED.
                                                  id: A5..A12 = 1..8, B = 9..16, C = 17..24
  /xremote                                        subscribe to pushed events, expires after ~10 s
"""
import socket
import threading
import time

from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder

BANKS = "ABC"
SUBSCRIBE_EVERY_S = 8  # the console drops a subscription after ~10 s


def userpar_id(bank, button):
    return BANKS.index(bank) * 8 + (button - 4)


def button_path(bank, button):
    return f"/config/userctrl/{bank}/btn/{button}"


def led_path(bank, button):
    return f"/-stat/userpar/{userpar_id(bank, button):02d}/value"


def _dgram(path, *args):
    b = OscMessageBuilder(address=path)
    for a in args:
        b.add_arg(a)
    return b.build().dgram


class X32Link:
    """on_event(address, params) is called from the receive thread for every pushed message."""

    def __init__(self, on_event=None):
        self.on_event = on_event
        self.addr = None
        self.subscribed = False
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("0.0.0.0", 0))
        self._sock.settimeout(0.2)
        self._lock = threading.Lock()
        self._replies = {}
        self._running = True
        self._last_subscribe = 0.0
        threading.Thread(target=self._receive, daemon=True, name="x32-recv").start()

    def set_target(self, ip, port):
        new = (ip, int(port)) if ip else None
        if new != self.addr:
            self.addr = new
            self._last_subscribe = 0.0

    def close(self):
        self._running = False
        self._sock.close()

    def send(self, path, *args):
        if self.addr:
            self._sock.sendto(_dgram(path, *args), self.addr)

    def query(self, path, timeout_s=0.6):
        """The console's current value for path, or None if it doesn't answer in time."""
        if not self.addr:
            return None
        with self._lock:
            self._replies.pop(path, None)
        self.send(path)
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            with self._lock:
                if path in self._replies:
                    return self._replies[path]
            time.sleep(0.02)
        return None

    def keep_subscribed(self):
        """Call regularly; renews /xremote when due."""
        now = time.monotonic()
        if self.addr and now - self._last_subscribe >= SUBSCRIBE_EVERY_S:
            self._last_subscribe = now
            self.send("/xremote")

    def _receive(self):
        while self._running:
            try:
                data, _ = self._sock.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            try:
                msg = OscMessage(data)
            except Exception:
                continue
            with self._lock:
                self._replies[msg.address] = list(msg.params)
            if self.on_event and msg.address.startswith("/-stat/userpar/"):
                try:
                    self.on_event(msg.address, list(msg.params))
                except Exception:
                    pass
