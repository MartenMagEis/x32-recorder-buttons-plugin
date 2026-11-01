"""Django-side tests with a simulated X32 on localhost - run inside an x32-recorder checkout with
this plugin enabled:  uv run python x32recorder/manage.py test x32_recorder_buttons_plugin
"""
import socket
import threading
import time
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder

from recorder.models import OscConfig, Recording

from .. import logic, plugin_config
from ..models import ButtonSettings
from ..service import ButtonService, assignment_value


def _dgram(path, *args):
    b = OscMessageBuilder(address=path)
    for a in args:
        b.add_arg(a)
    return b.build().dgram


class FakeX32:
    """Answers queries for /config/userctrl/..., stores writes, records LED writes, can push
    button events to whoever subscribed via /xremote."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.1)
        self.port = self.sock.getsockname()[1]
        self.config = {f"/config/userctrl/C/btn/{n}": "-" for n in range(5, 13)}
        self.config["/config/userctrl/C/btn/5"] = "P0002"  # something the band had assigned
        self.leds = []
        self.subscriber = None
        self.running = True
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            msg = OscMessage(data)
            if msg.address == "/xremote":
                self.subscriber = addr
            elif msg.address.startswith("/-stat/userpar/"):
                self.leds.append((msg.address, msg.params[0]))
            elif msg.address in self.config:
                if msg.params:
                    self.config[msg.address] = msg.params[0]
                else:
                    self.sock.sendto(_dgram(msg.address, self.config[msg.address]), addr)

    def press(self, par, down=True):
        self.sock.sendto(_dgram(f"/-stat/userpar/{par:02d}/value", 127 if down else 0), self.subscriber)

    def stop(self):
        self.running = False
        self.sock.close()


class ButtonPluginTests(TestCase):
    def setUp(self):
        self.x32 = FakeX32()
        self.addCleanup(self.x32.stop)
        cfg = OscConfig.get_solo()
        cfg.x32_ip, cfg.x32_port = "127.0.0.1", self.x32.port
        cfg.save()
        self.service = ButtonService()
        patcher = patch("x32_recorder_buttons_plugin.plugin_config.get_service", return_value=self.service)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.service.refresh()

    def test_confirm_text_names_buttons_and_current_assignment(self):
        fields = {f["name"]: f for f in plugin_config.get_config_schema()["fields"]}
        text = fields["assign"]["confirm"]
        self.assertIn("C5 (bisher: P0002)  ->  REC", text)
        self.assertIn("C6 (bisher: frei)  ->  SONG", text)
        self.assertIn("C7 (bisher: frei)  ->  NEXT", text)
        self.assertIn("C8 bleibt unverändert", text)

    def test_assign_and_release_restore_original(self):
        plugin_config.handle_config_action("assign", {})
        self.assertEqual(self.x32.config["/config/userctrl/C/btn/5"], assignment_value("C", 5))
        self.assertEqual(self.x32.config["/config/userctrl/C/btn/8"], "-")  # 4th left alone
        settings = ButtonSettings.get_solo()
        self.assertEqual(settings.assigned_group, "C5")
        with self.assertRaises(ValidationError):
            plugin_config.update_config_values({"group": "A9"})
        self.service.refresh()
        plugin_config.handle_config_action("release", {})
        end = time.time() + 2  # UDP - the simulated console needs a moment
        while self.x32.config["/config/userctrl/C/btn/5"] != "P0002" and time.time() < end:
            time.sleep(0.01)
        self.assertEqual(self.x32.config["/config/userctrl/C/btn/5"], "P0002")
        self.assertEqual(ButtonSettings.get_solo().assigned_group, "")

    def test_press_triggers_api_and_leds_follow_recording(self):
        plugin_config.handle_config_action("assign", {})
        settings = ButtonSettings.get_solo()
        settings.enabled = True
        settings.save()
        calls = []

        def fake_api(method, path, data=None):
            calls.append((method, path, data))
            return {"name": "Probe"}

        self.service._api = fake_api

        def run_until(condition, timeout=3.0):
            # drive the service loop in this thread (SQLite test DB + threads don't mix)
            end = time.time() + timeout
            while time.time() < end:
                self.service.step()
                if condition():
                    return True
                time.sleep(0.02)
            return False

        self.assertTrue(run_until(lambda: self.x32.subscriber is not None), "never subscribed via /xremote")

        self.x32.press(17)  # C5 = REC
        self.x32.press(17, down=False)
        self.assertTrue(run_until(lambda: calls))
        self.assertEqual(calls[0][:2], ("POST", "/recordings/start_from_template/"))

        # a recording appears -> REC LED on after the next refresh
        Recording.objects.create(state=Recording.RECORD, channels=[0])
        self.service._last_refresh = 0.0
        self.assertTrue(run_until(lambda: ("/-stat/userpar/17/value", 127) in self.x32.leds))

        # single REC press while recording only arms; a second one within the window stops
        self.x32.press(17)
        self.x32.press(17, down=False)
        run_until(lambda: False, timeout=0.15)
        self.x32.press(17)
        self.x32.press(17, down=False)
        self.assertTrue(run_until(lambda: len(calls) >= 2))
        self.assertTrue(calls[1][1].endswith("/stop/"), calls)
        run_until(lambda: False, timeout=0.3)
        self.assertEqual(len([c for c in calls if c[1].endswith("/stop/")]), 1)

    def test_lit_button_reports_only_its_release(self):
        """Real X32: while a button's LED is on, a press isn't reported - only the release."""
        plugin_config.handle_config_action("assign", {})
        settings = ButtonSettings.get_solo()
        settings.enabled = True
        settings.save()
        Recording.objects.create(state=Recording.RECORD, channels=[0])
        calls = []
        self.service._api = lambda method, path, data=None: calls.append(path) or {}
        self.service._last_refresh = 0.0

        def run_until(condition, timeout=2):
            end = time.time() + timeout
            while not condition() and time.time() < end:
                self.service.step()
                time.sleep(0.02)
            return condition()

        self.assertTrue(run_until(lambda: self.x32.subscriber is not None))
        self.x32.press(17, down=False)
        run_until(lambda: False, timeout=0.15)
        self.assertEqual(calls, [])  # one press only arms the stop
        self.x32.press(17, down=False)
        self.assertTrue(run_until(lambda: calls))
        self.assertTrue(calls[0].endswith("/stop/"), calls)
        # a release of a press that was reported is not a second press
        self.x32.press(18)
        self.assertTrue(run_until(lambda: len(calls) >= 2))
        self.x32.press(18, down=False)
        run_until(lambda: False, timeout=0.15)
        self.assertEqual(len(calls), 2, calls)

    def test_scene_recall_warns_offers_repair_and_release_leaves_console_alone(self):
        from .. import system_health

        plugin_config.handle_config_action("assign", {})
        settings = ButtonSettings.get_solo()
        settings.enabled = True
        settings.save()
        self.service.refresh()
        self.assertEqual(system_health.get_warnings(), [])

        # a scene recall re-assigns two of our buttons
        self.x32.config["/config/userctrl/C/btn/5"] = "S0001"
        self.x32.config["/config/userctrl/C/btn/6"] = "S0002"
        self.service._check_integrity()
        with patch("x32_recorder_buttons_plugin.system_health.get_service", return_value=self.service):
            warnings = system_health.get_warnings()
        self.assertEqual(warnings[0]["key"], "buttons_reassigned")
        self.assertIn("C5, C6", warnings[0]["message"])

        fields = {f["name"]: f for f in plugin_config.get_config_schema()["fields"]}
        self.assertIn("C5 (bisher: S0001)  ->  REC", fields["repair"]["confirm"])
        self.assertIn("bleiben, wie sie jetzt", fields["release"]["confirm"])

        plugin_config.handle_config_action("repair", {})
        self.assertEqual(self.x32.config["/config/userctrl/C/btn/5"], assignment_value("C", 5))
        self.assertEqual(self.service.warning, "")
        # the scene's assignment is what a later release restores
        self.assertEqual(ButtonSettings.get_solo().original_assignments["/config/userctrl/C/btn/5"], "S0001")

        # re-assigned again, and this time the user just releases: nothing is written back
        self.service.refresh()
        self.x32.config["/config/userctrl/C/btn/5"] = "S0009"
        self.service._check_integrity()
        plugin_config.handle_config_action("release", {})
        time.sleep(0.2)
        self.assertEqual(self.x32.config["/config/userctrl/C/btn/5"], "S0009")
        self.assertEqual(ButtonSettings.get_solo().assigned_group, "")

    def test_function_mapping(self):
        self.assertEqual(logic.FUNCTIONS, (logic.REC, logic.SONG, logic.NEXT))
