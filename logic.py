"""What a button press means and what the LEDs should show - pure logic, no network, no Django,
so it can be tested on its own (tests/test_logic.py). service.py feeds it console events and
recorder state and carries out what it returns.

Buttons of a group (4 consecutive assign buttons), by position:
  0 REC   not recording: press -> start. Recording: double press (two presses within
          double_press_s) OR hold for hold_s -> stop. A single press while recording only
          answers with a short blink ("press again / hold to stop").
  1 SONG  song start / song end (like the web UI's marker button)
  2 NEXT  end the open song and start the next one of the setlist
  3 -     reserved (left untouched)
"""
REC, SONG, NEXT = 'rec', 'song', 'next'
FUNCTIONS = (REC, SONG, NEXT)

# Results of press()/tick()
START, STOP, MARKER, NEXT_SONG = 'start', 'stop', 'marker', 'next'
ARMED = 'armed'                  # REC pressed once while recording - waiting for 2nd press / hold
NOT_RECORDING = 'not_recording'  # SONG/NEXT without a running recording


class ButtonLogic:
    def __init__(self, double_press_s=0.6, hold_s=1.5):
        self.double_press_s = double_press_s
        self.hold_s = hold_s
        self._rec_last_press = None   # time of the arming press while recording
        self._rec_down_since = None   # REC currently held down since
        self._hold_fired = False
        self._blinks = {}             # function -> (start, times, period_s)

    # --- input -------------------------------------------------------------------------------

    def press(self, function, now, recording):
        if function == REC:
            self._rec_down_since = now
            self._hold_fired = False
            if not recording:
                self._rec_last_press = None
                return START
            if self._rec_last_press is not None and now - self._rec_last_press <= self.double_press_s:
                self._rec_last_press = None
                self._hold_fired = True  # the stop is done - don't fire again via hold
                return STOP
            self._rec_last_press = now
            return ARMED
        if function in (SONG, NEXT):
            if not recording:
                return NOT_RECORDING
            return MARKER if function == SONG else NEXT_SONG
        return None

    def release(self, function, now):
        if function == REC:
            self._rec_down_since = None

    def tick(self, now, recording):
        """Call regularly (e.g. every 50 ms): fires the hold-to-stop."""
        if (recording and self._rec_down_since is not None and not self._hold_fired
                and now - self._rec_down_since >= self.hold_s):
            self._hold_fired = True
            self._rec_last_press = None
            return STOP
        return None

    # --- output ------------------------------------------------------------------------------

    def blink(self, function, now, times=2, period_s=0.25):
        """Short feedback flashes on one button, overriding its normal LED state meanwhile."""
        self._blinks[function] = (now, times, period_s)

    def leds(self, now, recording, song_open):
        """{function: on?} for every button of the group."""
        state = {REC: recording, SONG: recording and song_open, NEXT: False}
        for function, (start, times, period_s) in list(self._blinks.items()):
            elapsed = now - start
            if elapsed >= times * period_s:
                del self._blinks[function]
                continue
            # on for the first half of each period, off for the second
            state[function] = (elapsed % period_s) < period_s / 2
        return state
