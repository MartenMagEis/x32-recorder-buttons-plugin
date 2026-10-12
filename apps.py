import threading

from django.apps import AppConfig

from recorder.plugin_support import should_start_background_work


class ButtonsPluginConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    # Must match the folder name this repo gets cloned into by x32-recorder's plugin system
    # (derived from the GitHub URL) - "x32-recorder-buttons-plugin" -> "x32_recorder_buttons_plugin".
    name = "x32_recorder_buttons_plugin"
    verbose_name = "X32 Assign-Tasten"

    def ready(self):
        if not should_start_background_work():
            return
        from .service import run_service

        threading.Thread(target=run_service, daemon=True, name="x32-buttons").start()
