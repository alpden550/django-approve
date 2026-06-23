from typing import Any

from django.apps import AppConfig
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model, Q

from django_approve.config import conf
from django_approve.cons import ApprovalStatusChoices
from django_approve.fields import prune_tracked_fields
from django_approve.models import ApprovalConfig, ChangeRequestField
from django_approve.registry import registry


def sync_approval_configs(sender: AppConfig, **kwargs: Any) -> None:
    """Create/update `ApprovalConfig` rows for registered models; prune stale tracked fields.

    Orphaned configs (model no longer registered) are deleted only while
    `is_enabled=True`, so a manually disabled config survives unregistration.
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


def ensure_approval_group(sender: AppConfig, **kwargs: Any) -> None:
    """Idempotently sync the `conf.GROUP_NAME` group's view/change permissions.

    No-op when `APPROVE_AUTO_CREATE_GROUP` is disabled.
    """
    if not conf.AUTO_CREATE_GROUP:
        return

    crf_ct = ContentType.objects.get_for_model(ChangeRequestField)
    ac_ct = ContentType.objects.get_for_model(ApprovalConfig)

    permissions = list(
        Permission.objects.filter(
            Q(content_type=crf_ct, codename__in=("view_changerequestfield", "change_changerequestfield"))
            | Q(content_type=ac_ct, codename__in=("view_approvalconfig", "change_approvalconfig")),
        ),
    )

    group, _ = Group.objects.get_or_create(name=conf.GROUP_NAME)
    group.permissions.set(permissions)


def cleanup_orphan_requests(sender: type[Model], instance: Model, **kwargs: Any) -> None:
    """Mark pending requests of a deleted target as `deleted`.

    The target no longer exists, so the request can never be applied. Moving it
    out of `pending` releases the per-field lock while keeping the row as audit;
    already terminal (`approved`/`rejected`) requests are left untouched.

    Args:
        sender: The model class of the deleted instance.
        instance: The deleted instance (its pk is still available here).
        **kwargs: Additional keyword arguments provided by the signal.
    """
    if not registry.is_registered(sender):
        return

    content_type = ContentType.objects.get_for_model(sender)
    ChangeRequestField.objects.filter(
        content_type=content_type,
        object_id=instance.pk,
        status=ApprovalStatusChoices.PENDING,
    ).update(status=ApprovalStatusChoices.DELETED)
