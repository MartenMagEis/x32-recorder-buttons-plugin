# X32 Assign-Tasten für x32-recorder

Plugin für [x32-recorder](https://github.com/tobire42/x32-recorder): die Aufnahme direkt am Pult
bedienen - über drei der frei belegbaren **Assign-Tasten** eines Behringer X32 / Midas M32, mit
Status-LEDs. Gedacht z.B. für die Kirche: der Techniker muss nicht ans Tablet, um eine Aufnahme zu
starten oder die Predigt zu markieren.

**Nicht für das X32 Rack** - das hat keine Assign-Sektion.

## Bedienung

Eine Gruppe aus 4 nebeneinanderliegenden Tasten einer Bank (in den Einstellungen wählbar, z.B.
"Bank C, Tasten 5-8"):

| Taste | Funktion | LED |
|---|---|---|
| 1. **REC** | Drücken: Aufnahme starten (mit der zuletzt gewählten Vorlage, wie in der Weboberfläche vorbelegt). **Stoppen nur per Doppeldruck oder Halten** (Zeiten einstellbar) - ein einzelner Druck während der Aufnahme blinkt nur ("nochmal drücken oder halten") | an = Aufnahme läuft |
| 2. **SONG** | Song-Start / Song-Ende, wie der Marker-Button | an = Song offen |
| 3. **NEXT** | Offenen Song beenden und nächsten Song der Setlist starten | aus |
| 4. | bleibt frei und unverändert | |

Jede ausgeführte Aktion quittiert die Taste mit zweimal kurzem Blinken, ein Fehler (z.B. Start
nicht möglich) mit schnellem Blinken. SONG/NEXT ohne laufende Aufnahme: kurzes Flackern, sonst nichts.

## Einrichten

1. Plugin in x32-recorder unter **Einstellungen → Plugins** per GitHub-URL hinzufügen, Dienste neu
   starten.
2. Die IP des Pults muss in x32-recorder eingestellt sein (Einstellungen → Pult/OSC).
3. In den Plugin-Einstellungen die **Tastengruppe** wählen und **"Tasten am Pult belegen"** klicken.
   Vorher wird genau angezeigt, welche Tasten mit welcher bisherigen Belegung überschrieben werden.
   Die alte Belegung wird gemerkt; **"Tasten freigeben"** stellt sie wieder her.
4. **Aktiviert** einschalten.

Lädt jemand am Pult eine Szene, die die Assign-Tasten anders belegt, zeigt der Status das an (das
Plugin schreibt nie ungefragt ins Pult) - dann einfach neu belegen.

## Technik

- Die Tasten werden als MIDI-Note-Taster auf MIDI-Kanal 16 belegt (bewirken am Pult selbst nichts);
  Druck und Loslassen meldet das Pult per OSC (`/-stat/userpar/<id>/value`) an angemeldete Clients
  (`/xremote`, alle 8 s erneuert). Die LEDs setzt das Plugin über denselben Pfad.
- Läuft als Hintergrund-Thread im x32-recorder-Webprozess; Aktionen laufen über dessen REST-API
  (`start_from_template`, `stop`, `marker_action`) - dieselben Wege wie Weboberfläche und
  Sprachsteuerung.
- Vor dem ersten Einsatz am echten Pult: `tools/x32_assign_probe.py` aus x32-recorder prüft, ob
  Tastenmeldungen und LEDs am konkreten Pult/Firmware wie erwartet funktionieren.

## Tests

```bash
python -m unittest tests.test_logic                                   # Tastenlogik, im Plugin-Ordner
uv run python x32recorder/manage.py test x32_recorder_buttons_plugin  # mit simuliertem Pult, in x32-recorder
```

## Ideen für später

- Multitrack-Wiedergabe der letzten Aufnahme über die 4. Taste (nur per Doppeldruck/Halten), evtl.
  Auswahl der Aufnahme per Drehregler - bewusst noch nicht gebaut: das Risiko, im Gottesdienst
  versehentlich etwas abzuspielen, ist größer als der Nutzen; die Weboberfläche ist der sicherere Weg.
