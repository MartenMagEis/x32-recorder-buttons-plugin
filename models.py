from django.db import models

# A group = 4 consecutive assign buttons of one bank (one row on the X32): REC, SONG, NEXT and one
# reserved for later. Value = bank letter + first button number.
GROUP_CHOICES = [
    (f"{bank}{start}", f"Bank {bank}, Tasten {start}-{start + 3}")
    for bank in "ABC" for start in (5, 9)
]


def group_buttons(group):
    """'C5' -> ('C', [5, 6, 7]) - the three buttons in use (the 4th is reserved, left alone)."""
    bank, start = group[0], int(group[1:])
    return bank, [start, start + 1, start + 2]


class ButtonSettings(models.Model):
    """Singleton, shown on x32-recorder's Settings page (plugin_config.py)."""

    enabled = models.BooleanField(
        "Aktiviert", default=False,
        help_text="Solange aus, reagiert der Recorder nicht auf die Tasten und schaltet keine LEDs."
    )
    group = models.CharField(
        "Tastengruppe", max_length=3, choices=GROUP_CHOICES, default="C5",
        help_text="4 Tasten nebeneinander: 1. REC, 2. SONG, 3. NEXT, die 4. bleibt frei. Ändern nur, "
                   "solange keine Tasten belegt sind."
    )
    double_press_ms = models.IntegerField(
        "Doppeldruck-Fenster (ms)", default=1000,
        help_text="Aufnahme stoppen: REC zweimal innerhalb dieser Zeit drücken. So lange ist das LED nach "
                  "dem ersten Druck aus."
    )

    # Which group is currently programmed on the console ("" = none) and what those buttons held
    # before, so "Tasten freigeben" can put it back exactly.
    assigned_group = models.CharField(max_length=3, blank=True, default="")
    original_assignments = models.JSONField(default=dict, blank=True)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
