from typing import Any

from django.apps import AppConfig
from django.contrib.contenttypes.models import ContentType

from django_approve.fields import prune_tracked_fields
from django_approve.models import ApprovalConfig
from django_approve.registry import registry


def sync_approval_configs(sender: AppConfig, **kwargs: Any) -> None:
    """
    Synchronizes approval configurations for all models registered in the application. For each model,
    retrieves its content type and ensures an `ApprovalConfig` entry exists with tracked fields updated.

    Args:
        sender (AppConfig): The application configuration instance sending the signal.
        **kwargs (Any): Additional keyword arguments provided by the signal.
    """
    active_content_type_ids = set()

    for model in registry.get_models():
        content_type = ContentType.objects.get_for_model(model)
        active_content_type_ids.add(content_type.id)
        config, _ = ApprovalConfig.objects.get_or_create(
            content_type=content_type,
            defaults={"tracked_fields": []},
        )

        pruned = prune_tracked_fields(model=model, tracked_fields=config.tracked_fields)
        if pruned != config.tracked_fields:
            config.tracked_fields = pruned
            config.save(update_fields=["tracked_fields", "updated"])

    ApprovalConfig.objects.filter(is_enabled=True).exclude(
        content_type_id__in=active_content_type_ids,
    ).delete()
