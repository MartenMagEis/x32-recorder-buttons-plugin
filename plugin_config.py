"""Settings on x32-recorder's Settings page (plugin_config.py convention)."""
from django.core.exceptions import ValidationError

from recorder.plugin_support import describe_model_fields, model_instance_values

from . import logic
from .models import ButtonSettings, group_buttons
from .service import get_service

FIELDS = ["enabled", "group", "double_press_ms", "hold_ms"]
FUNCTION_LABELS = {logic.REC: "REC", logic.SONG: "SONG", logic.NEXT: "NEXT"}


def _assign_confirm(group):
    bank, numbers = group_buttons(group)
    current = get_service().current_assignments(group)
    lines = []
    for function, number in zip(logic.FUNCTIONS, numbers):
        value = current.get(f"{bank}{number}")
        shown = "keine Antwort vom Pult" if value is None else ("frei" if value in ("", "-") else value)
        lines.append(f"  {bank}{number} (bisher: {shown})  ->  {FUNCTION_LABELS[function]}")
    return ("Folgende Assign-Tasten am Pult werden überschrieben:\n\n" + "\n".join(lines) +
            f"\n\n{bank}{numbers[-1] + 1} bleibt unverändert. Die bisherige Belegung wird gemerkt und "
            "mit 'Tasten freigeben' wiederhergestellt. Fortfahren?")


def _release_confirm(settings):
    bank, numbers = group_buttons(settings.assigned_group)
    names = ", ".join(f"{bank}{n}" for n in numbers)
    return f"Die Tasten {names} bekommen ihre frühere Belegung zurück. Fortfahren?"


def get_config_schema():
    settings = ButtonSettings.get_solo()
    fields = describe_model_fields(ButtonSettings, FIELDS)
    fields.append({"name": "assignment", "label": "Belegung am Pult", "type": "string", "help_text": "",
                   "readonly": True})
    if settings.assigned_group:
        fields.append({"name": "release", "label": "Tasten freigeben (frühere Belegung zurück)",
                       "type": "action", "help_text": "", "readonly": False,
                       "confirm": _release_confirm(settings)})
    else:
        fields.append({"name": "assign", "label": "Tasten am Pult belegen", "type": "action",
                       "help_text": "Schreibt die Belegung ins Pult - vorher wird genau angezeigt, welche "
                                    "Tasten betroffen sind.", "readonly": False,
                       "confirm": _assign_confirm(settings.group)})
    fields += [
        {"name": "status", "label": "Status", "type": "string", "help_text": "", "readonly": True},
        {"name": "recent", "label": "Letzte Tastendrücke", "type": "string", "help_text": "", "readonly": True},
    ]
    return {"fields": fields}


def get_config_values():
    settings = ButtonSettings.get_solo()
    service = get_service()
    values = model_instance_values(settings, FIELDS)
    if settings.assigned_group:
        bank, numbers = group_buttons(settings.assigned_group)
        values["assignment"] = ", ".join(f"{bank}{n} = {FUNCTION_LABELS[f]}"
                                         for f, n in zip(logic.FUNCTIONS, numbers))
    else:
        values["assignment"] = "nicht belegt"
    values["status"] = service.status + (f" - {service.warning}" if service.warning else "")
    values["recent"] = "\n".join(service.recent) or "–"
    return values


def update_config_values(data):
    settings = ButtonSettings.get_solo()
    if settings.assigned_group and data.get("group", settings.group) != settings.group:
        raise ValidationError("Die Tastengruppe lässt sich nur ändern, solange keine Tasten belegt sind - "
                              "erst 'Tasten freigeben'.")
    for key, value in data.items():
        if key in FIELDS:
            setattr(settings, key, value)
    settings.full_clean()
    settings.save()
    return get_config_values()


def handle_config_action(action_name, data):
    settings = ButtonSettings.get_solo()
    service = get_service()
    if action_name == "assign":
        if settings.assigned_group:
            raise ValidationError("Tasten sind schon belegt.")
        service.assign(settings.group)
    elif action_name == "release":
        if settings.assigned_group:
            service.release()

