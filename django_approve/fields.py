from collections.abc import Iterable
from typing import Any

from django.db import models
from django.db.models import Field

from django_approve.registry import registry

UNSUPPORTED_FIELDS = (models.FileField,)


def _is_eligible(field: Field[Any, Any]) -> bool:
    """Whether a concrete field may be tracked for approval (see PLAN decision #4).

    Args:
        field: A concrete model field.

    Returns:
        False for the primary key, non-editable fields, auto_now/auto_now_add
        timestamps, and file/image fields (phase 2); True otherwise. M2M is
        already excluded upstream by concrete_fields.
    """
    if isinstance(field, UNSUPPORTED_FIELDS):
        return False
    if field.primary_key or not field.editable:
        return False
    return not (getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False))


def get_candidate_fields(model: type[models.Model]) -> list[str]:
    """Return field names eligible for approval tracking on a model.

    Args:
        model: The model to introspect.

    Returns:
        Names of the model's concrete, editable, supported fields.
    """
    return [field.name for field in model._meta.concrete_fields if _is_eligible(field=field)]


def get_approvable_fields(model: type[models.Model]) -> list[str]:
    """Intersect a model's eligible fields with the developer whitelist.

    Args:
        model: A registered model.

    Returns:
        Candidate fields are narrowed to the registry whitelist, or all candidates
        when the whitelist is "__all__".
    """
    candidates = get_candidate_fields(model)
    whitelist = registry.get_whitelist(model)

    if whitelist == "__all__":
        return candidates

    return [name for name in candidates if name in whitelist]


def prune_tracked_fields(model: type[models.Model], tracked_fields: Iterable[str]) -> list[str]:
    """Drop tracked field names that are no longer approvable for the model.

    Args:
        model: A registered model.
        tracked_fields: Previously stored/selected field names.

    Returns:
        The given names filtered down to the model's current approvable fields,
        preserving their original order.
    """
    valid = set(get_approvable_fields(model))
    return [name for name in tracked_fields if name in valid]
