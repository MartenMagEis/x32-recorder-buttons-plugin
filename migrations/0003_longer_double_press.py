from django.db import migrations, models


def _bump_old_default(apps, schema_editor):
    ButtonSettings = apps.get_model("x32_recorder_buttons_plugin", "ButtonSettings")
    ButtonSettings.objects.filter(double_press_ms=600).update(double_press_ms=1000)


class Migration(migrations.Migration):

    dependencies = [
        ("x32_recorder_buttons_plugin", "0002_remove_hold"),
    ]

    operations = [
        migrations.AlterField(
            model_name="buttonsettings",
            name="double_press_ms",
            field=models.IntegerField(
                default=1000,
                help_text="Aufnahme stoppen: REC zweimal innerhalb dieser Zeit drücken. So lange ist das LED nach "
                "dem ersten Druck aus.",
                verbose_name="Doppeldruck-Fenster (ms)",
            ),
        ),
        migrations.RunPython(_bump_old_default, migrations.RunPython.noop),
    ]
