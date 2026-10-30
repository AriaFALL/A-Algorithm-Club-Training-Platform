from django.apps import AppConfig


class ClubConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "club"

    def ready(self):
        from . import role_signals  # noqa: F401
        from . import solved_signals  # noqa: F401
        from . import system_task  # noqa: F401
