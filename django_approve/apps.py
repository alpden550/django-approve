from django.apps import AppConfig


class ApproveConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_approve"
    verbose_name = "Approvals"

    def ready(self):
        from django.db.models.signals import post_delete, post_migrate  # noqa: PLC0415

        from django_approve.signals import (  # noqa: PLC0415
            cleanup_orphan_requests,
            ensure_approval_group,
            sync_approval_configs,
        )

        post_migrate.connect(sync_approval_configs, sender=self)
        post_migrate.connect(ensure_approval_group, sender=self)
        post_delete.connect(cleanup_orphan_requests)
