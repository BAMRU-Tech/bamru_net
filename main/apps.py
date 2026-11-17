from django.apps import AppConfig


class MainConfig(AppConfig):
    name = 'main'

    def ready(self):
        # Registers the check of ACTIVITY_REPORTS, and reads the setting again when a test changes it.
        from main.lib import report_settings  # noqa: F401
