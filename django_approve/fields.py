from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.db import models
from django.db.models import Field

from django_approve.registry import registry

UNSUPPORTED_FIELDS = (models.FileField,)


def _is_eligible(field: Field[Any, Any]) -> bool:
    if isinstance(field, UNSUPPORTED_FIELDS):
        return False
    if field.primary_key or not field.editable:
        return False
    return not (getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False))


def get_candidate_fields(model: type[models.Model]) -> list[str]:
    return [field.name for field in model._meta.concrete_fields if _is_eligible(field=field)]


def get_approvable_fields(model: type[models.Model]) -> list[str]:
    """Intersect a model's eligible fields with the developer whitelist; "__all__" means every candidate."""
    candidates = get_candidate_fields(model)
    whitelist = registry.get_whitelist(model)

    if whitelist == "__all__":
        return candidates

    return [name for name in candidates if name in whitelist]


def prune_tracked_fields(model: type[models.Model], tracked_fields: Iterable[str]) -> list[str]:
    valid = set(get_approvable_fields(model))
    return [name for name in tracked_fields if name in valid]


def get_tracked_fields(model: type[models.Model]) -> list[str]:
    """Return the model's pruned tracked fields, or an empty list if no enabled config exists."""

    from django.contrib.contenttypes.models import ContentType  # noqa: PLC0415

    from django_approve.models import ApprovalConfig  # noqa: PLC0415

    ct = ContentType.objects.get_for_model(model)
    config = ApprovalConfig.objects.filter(content_type=ct, is_enabled=True).only("tracked_fields").first()
    if config is None:
        return []

    return prune_tracked_fields(model=model, tracked_fields=config.tracked_fields)
