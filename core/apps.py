from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Registers the signal that removes a photo's files when it is deleted,
        # and the ones that count failed sign-ins.
        from . import login_guard, photos  # noqa: F401
