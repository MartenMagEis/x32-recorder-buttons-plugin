"""Tests for the pure button logic - run from the plugin folder: python -m unittest tests.test_logic"""
import unittest

try:
    from logic import (ARMED, MARKER, NEXT, NEXT_SONG, NOT_RECORDING, REC, SONG, START, STOP,
                       ButtonLogic)
except ImportError:  # inside x32-recorder's Django test run the module is the package's, not top-level
    raise unittest.SkipTest('logic tests run standalone from the plugin folder')


class PressTests(unittest.TestCase):
    def setUp(self):
        self.logic = ButtonLogic(double_press_s=0.6, hold_s=1.5)

    def test_rec_starts_when_idle(self):
        self.assertEqual(self.logic.press(REC, 0.0, recording=False), START)

    def test_single_press_while_recording_only_arms(self):
        self.assertEqual(self.logic.press(REC, 0.0, recording=True), ARMED)
        self.logic.release(REC, 0.1)
        self.assertIsNone(self.logic.tick(5.0, recording=True))

    def test_double_press_stops(self):
        self.logic.press(REC, 0.0, recording=True)
        self.logic.release(REC, 0.1)
        self.assertEqual(self.logic.press(REC, 0.4, recording=True), STOP)

    def test_slow_second_press_rearms(self):
        self.logic.press(REC, 0.0, recording=True)
        self.logic.release(REC, 0.1)
        self.assertEqual(self.logic.press(REC, 1.0, recording=True), ARMED)
        self.logic.release(REC, 1.1)
        self.assertEqual(self.logic.press(REC, 1.4, recording=True), STOP)

    def test_hold_stops_once(self):
        self.logic.press(REC, 0.0, recording=True)
        self.assertIsNone(self.logic.tick(1.0, recording=True))
        self.assertEqual(self.logic.tick(1.5, recording=True), STOP)
        self.assertIsNone(self.logic.tick(3.0, recording=True))

    def test_start_then_quick_press_does_not_stop(self):
        self.assertEqual(self.logic.press(REC, 0.0, recording=False), START)
        self.logic.release(REC, 0.1)
        self.assertEqual(self.logic.press(REC, 0.3, recording=True), ARMED)

    def test_hold_after_start_does_not_stop(self):
        # pressing REC to start and keeping it down must not turn into a stop
        self.assertEqual(self.logic.press(REC, 0.0, recording=False), START)
        self.assertIsNone(self.logic.tick(2.0, recording=False))

    def test_song_and_next(self):
        self.assertEqual(self.logic.press(SONG, 0.0, recording=True), MARKER)
        self.assertEqual(self.logic.press(NEXT, 0.0, recording=True), NEXT_SONG)
        self.assertEqual(self.logic.press(SONG, 0.0, recording=False), NOT_RECORDING)


class LedTests(unittest.TestCase):
    def test_steady_state(self):
        logic = ButtonLogic()
        self.assertEqual(logic.leds(0.0, recording=True, song_open=True), {REC: True, SONG: True, NEXT: False})
        self.assertEqual(logic.leds(0.0, recording=False, song_open=True), {REC: False, SONG: False, NEXT: False})

    def test_blink_overrides_then_ends(self):
        logic = ButtonLogic()
        logic.blink(NEXT, 10.0, times=2, period_s=0.25)
        self.assertTrue(logic.leds(10.05, True, False)[NEXT])
        self.assertFalse(logic.leds(10.2, True, False)[NEXT])
        self.assertTrue(logic.leds(10.3, True, False)[NEXT])
        self.assertFalse(logic.leds(10.6, True, False)[NEXT])  # over - back to steady (off)


if __name__ == '__main__':
    unittest.main()
