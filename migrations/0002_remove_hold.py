from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("x32_recorder_buttons_plugin", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(model_name="buttonsettings", name="hold_ms"),
        migrations.AlterField(
            model_name="buttonsettings",
            name="double_press_ms",
            field=models.IntegerField(
                default=600,
                help_text="Aufnahme stoppen: REC zweimal innerhalb dieser Zeit drücken.",
                verbose_name="Doppeldruck-Fenster (ms)",
            ),
        ),
    ]
