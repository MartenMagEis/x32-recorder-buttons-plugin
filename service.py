"""The running part: listens to the console's assign buttons, triggers recorder actions, keeps the
button LEDs in sync with the recorder. A background thread in the x32-recorder web process
(started by apps.py), light enough for that: one UDP socket, a 50 ms loop.

Actions go through x32-recorder's own REST API (start_from_template, stop, marker_action) - the
same paths the web UI and the voice plugin use, so all validation stays in one place.
"""
import json
import logging
import threading
import time
import urllib.error
import urllib.request

from django.db import close_old_connections

from . import logic
from .logic import ButtonLogic
from .x32_osc import X32Link, button_path, led_path, userpar_id

logger = logging.getLogger(__name__)

LOOP_S = 0.05
REFRESH_S = 2.0
LED_RESEND_S = 2.0
INTEGRITY_CHECK_S = 30.0
MAX_RECENT = 10


def assignment_value(bank, button):
    """What our buttons are set to: a MIDI-note push button on MIDI channel 16 - does nothing on
    the console itself, but makes it report presses and releases via /-stat/userpar."""
    return f"MN16{100 + userpar_id(bank, button):03d}"


class ButtonService:
    def __init__(self):
        self.link = X32Link(on_event=self._on_event)
        self.logic = ButtonLogic()
        self._events = []
        self._events_lock = threading.Lock()
        self.settings = None
        self.functions = {}       # userpar id -> logic function
        self.buttons = {}         # logic function -> (bank, button)
        self.recording = None     # active Recording (state NEW/RECORD) or None
        self.song_open = False
        self._led_sent = {}
        self._last_led_resend = 0.0
        self._last_refresh = 0.0
        self._last_integrity = 0.0
        self.status = 'startet'
        self.warning = ''
        self.recent = []

    # --- console events (receive thread) ------------------------------------------------------

    def _on_event(self, address, params):
        try:
            par = int(address.split('/')[3])
            value = int(params[0]) if params else 0
        except (IndexError, ValueError):
            return
        with self._events_lock:
            self._events.append((time.monotonic(), par, value))

    # --- state -------------------------------------------------------------------------------

    def refresh(self):
        from recorder import markers
        from recorder.models import OscConfig, Recording

        from .models import ButtonSettings, group_buttons

        close_old_connections()
        self.settings = ButtonSettings.get_solo()
        cfg = OscConfig.get_solo()
        self.link.set_target(cfg.x32_ip, cfg.x32_port)
        self.logic.double_press_s = self.settings.double_press_ms / 1000.0
        self.logic.hold_s = self.settings.hold_ms / 1000.0

        self.functions, self.buttons = {}, {}
        if self.settings.assigned_group:
            bank, numbers = group_buttons(self.settings.assigned_group)
            for function, number in zip(logic.FUNCTIONS, numbers):
                self.functions[userpar_id(bank, number)] = function
                self.buttons[function] = (bank, number)

        self.recording = Recording.objects.filter(state__in=(Recording.NEW, Recording.RECORD)).order_by('-id').first()
        self.song_open = bool(self.recording and markers.open_song(self.recording))

        if not self.settings.enabled:
            self.status = 'aus'
        elif not self.settings.assigned_group:
            self.status = 'Tasten noch nicht belegt'
        elif not cfg.x32_ip:
            self.status = 'keine Pult-IP eingestellt'
        else:
            self.status = 'aktiv (Aufnahme läuft)' if self.recording else 'aktiv'

    @property
    def active(self):
        return bool(self.settings and self.settings.enabled and self.settings.assigned_group)

    def remember(self, function, result):
        self.recent.insert(0, f"{time.strftime('%H:%M:%S')}  {function.upper()}: {result}")
        del self.recent[MAX_RECENT:]

    # --- actions -----------------------------------------------------------------------------

    def _api(self, method, path, data=None):
        from recorder.models import RecorderSettings

        port = RecorderSettings.get_solo().web_port or 8000
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api{path}",
                                     data=json.dumps(data or {}).encode(), method=method,
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read()
                return json.loads(text) if text else None
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get('error', '')
            except Exception:
                detail = ''
            raise RuntimeError(detail or f'HTTP {e.code}') from e

    def _run_action(self, function, action, recording_id):
        """In its own thread - an HTTP round trip must never stall the button loop."""
        close_old_connections()
        try:
            if action == logic.START:
                rec = self._api('POST', '/recordings/start_from_template/')
                result = f"Aufnahme gestartet: {rec.get('name') or '(ohne Name)'}"
            elif action == logic.STOP:
                self._api('POST', f'/recordings/{recording_id}/stop/')
                result = 'Aufnahme gestoppt'
            else:
                which = 'toggle' if action == logic.MARKER else 'next'
                res = self._api('POST', f'/recordings/{recording_id}/marker_action/', {'action': which})
                result = 'Marker: ' + ', '.join(
                    ('Start ' + (m['name'] or '(ohne Name)')) if m['marker_type'] == 1 else 'Ende'
                    for m in res['created'])
            self.logic.blink(function, time.monotonic(), times=2, period_s=0.2)
        except Exception as e:
            result = f'Fehler: {e}'
            self.logic.blink(function, time.monotonic(), times=6, period_s=0.12)
        self.remember(function, result)
        self._last_refresh = 0.0  # pick up the new recording/marker state right away
        logger.info('%s: %s', function, result)

    def _dispatch(self, function, action):
        if action is None:
            return
        now = time.monotonic()
        if action == logic.ARMED:
            self.logic.blink(function, now, times=2, period_s=0.3)
            self.remember(function, 'zum Stoppen nochmal drücken oder halten')
            return
        if action == logic.NOT_RECORDING:
            self.logic.blink(function, now, times=3, period_s=0.12)
            self.remember(function, 'keine Aufnahme aktiv')
            return
        recording_id = self.recording.id if self.recording else None
        threading.Thread(target=self._run_action, args=(function, action, recording_id), daemon=True).start()

    # --- LEDs --------------------------------------------------------------------------------

    def _update_leds(self, now, force=False):
        wanted = self.logic.leds(now, recording=bool(self.recording), song_open=self.song_open)
        for function, on in wanted.items():
            if function not in self.buttons:
                continue
            if force or self._led_sent.get(function) != on:
                bank, number = self.buttons[function]
                self.link.send(led_path(bank, number), 127 if on else 0)
                self._led_sent[function] = on

    def _check_integrity(self):
        """A scene recall can overwrite the assign buttons - then say so (no silent rewrite:
        writing to the console only ever happens after the user confirmed it)."""
        bank, number = self.buttons[logic.REC]
        current = self.link.query(button_path(bank, number))
        if current is not None and current[0] != assignment_value(bank, number):
            self.warning = ('Die Tasten wurden am Pult umbelegt (Szene geladen?) - '
                            'in den Plugin-Einstellungen neu belegen.')
        elif current is not None:
            self.warning = ''

    # --- main loop ---------------------------------------------------------------------------

    def step(self):
        """One pass of the main loop."""
        now = time.monotonic()
        if now - self._last_refresh >= REFRESH_S:
            self._last_refresh = now
            self.refresh()
        with self._events_lock:
            events, self._events = self._events, []
        if not self.active:
            return
        self.link.keep_subscribed()
        for t, par, value in events:
            function = self.functions.get(par)
            if function is None:
                continue
            if value > 0:
                self._dispatch(function, self.logic.press(function, t, bool(self.recording)))
            else:
                self.logic.release(function, t)
                self._update_leds(now, force=True)  # the console may have changed it
        self._dispatch(logic.REC, self.logic.tick(now, bool(self.recording)))
        resend = now - self._last_led_resend >= LED_RESEND_S
        if resend:
            self._last_led_resend = now
        self._update_leds(now, force=resend)
        if now - self._last_integrity >= INTEGRITY_CHECK_S:
            self._last_integrity = now
            self._check_integrity()

    def run(self):
        while True:
            try:
                self.step()
            except Exception:
                logger.exception('button service error')
                time.sleep(1)
            time.sleep(LOOP_S)

    # --- programming the console (called from plugin_config actions) -------------------------

    def current_assignments(self, group):
        from .models import group_buttons

        bank, numbers = group_buttons(group)
        result = {}
        for number in numbers:
            value = self.link.query(button_path(bank, number))
            result[f"{bank}{number}"] = None if value is None else value[0]
        return result

    def assign(self, group):
        from .models import ButtonSettings, group_buttons

        self.refresh()
        bank, numbers = group_buttons(group)
        originals = {}
        for number in numbers:
            value = self.link.query(button_path(bank, number))
            if value is None:
                raise RuntimeError('Pult antwortet nicht - IP in den Einstellungen prüfen')
            originals[button_path(bank, number)] = value[0]
        for number in numbers:
            self.link.send(button_path(bank, number), assignment_value(bank, number))
        time.sleep(0.3)
        for number in numbers:
            value = self.link.query(button_path(bank, number))
            if not value or value[0] != assignment_value(bank, number):
                for path, original in originals.items():
                    self.link.send(path, original)
                raise RuntimeError(f'Taste {bank}{number} ließ sich nicht belegen - alte Belegung wiederhergestellt')
        settings = ButtonSettings.get_solo()
        settings.assigned_group = group
        settings.original_assignments = originals
        settings.save()
        self.warning = ''
        self._last_refresh = 0.0
        self._led_sent = {}

    def release(self):
        from .models import ButtonSettings

        settings = ButtonSettings.get_solo()
        for function, (bank, number) in self.buttons.items():
            self.link.send(led_path(bank, number), 0)
        for path, original in (settings.original_assignments or {}).items():
            self.link.send(path, original)
        settings.assigned_group = ''
        settings.original_assignments = {}
        settings.save()
        self.warning = ''
        self._last_refresh = 0.0


_service = None


def get_service():
    global _service
    if _service is None:
        _service = ButtonService()
    return _service


def run_service():
    get_service().run()
