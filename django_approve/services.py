from typing import Any

from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, models, transaction

from django_approve.config import conf
from django_approve.cons import ApprovalStatusChoices, ChangeTypeChoices
from django_approve.exceptions import ConflictError, SelfApprovalError
from django_approve.models import ChangeRequestField
from django_approve.serializers import (
    deserialize_object,
    deserialize_value,
    serialize_value,
)


def _lock_target(target_cls: type[models.Model], object_id: int | None, field_name: str) -> models.Model:
    try:
        return target_cls.objects.select_for_update().get(pk=object_id)
    except ObjectDoesNotExist as exc:
        msg = f"Target of field '{field_name}' no longer exists."
        raise ConflictError(msg) from exc


def _guard(change_request: ChangeRequestField, reviewer: AbstractBaseUser) -> None:
    persisted_status = (
        type(change_request)
        .objects.select_for_update()
        .filter(pk=change_request.pk)
        .values_list("status", flat=True)
        .first()
    )
    if persisted_status != ApprovalStatusChoices.PENDING:
        msg = f"Change request {change_request.pk} is no longer pending."
        raise ConflictError(msg)

    requester_id = change_request.requested_by_id  # pyrefly: ignore [missing-attribute]
    if conf.REQUIRE_DIFFERENT_USER and requester_id == reviewer.pk:
        msg = f"Change request {change_request.pk} cannot be approved by its own requester."
        raise SelfApprovalError(msg)


@transaction.atomic
def apply_field(change_request: ChangeRequestField, reviewer: AbstractBaseUser) -> None:
    _guard(change_request, reviewer)

    target_cls = change_request.content_type.model_class()  # pyrefly: ignore [missing-attribute]
    obj = _lock_target(target_cls, change_request.object_id, change_request.field_name)

    field = target_cls._meta.get_field(change_request.field_name)
    attr = field.attname if field.is_relation else field.name

    current = serialize_value(target_cls, field.name, getattr(obj, attr))
    if current != change_request.old_value:
        msg = f"Field '{field.name}' changed since the request was made."
        raise ConflictError(msg)

    try:
        value = deserialize_value(target_cls, change_request.field_name, change_request.new_value)
    except ObjectDoesNotExist as exc:
        msg = f"Field '{field.name}' references a target that no longer exists."
        raise ConflictError(msg) from exc
    setattr(obj, attr, value)
    obj.save(update_fields=[attr])


def build_create_instance(model: type[models.Model], payload: dict[str, Any]) -> models.Model:
    """Reconstruct and validate a model instance from a create payload.

    Raises:
        ObjectDoesNotExist: a referenced relation no longer exists.
        ValidationError: the rebuilt instance fails `full_clean` (e.g. a
            required field the snapshot could not capture).
    """
    obj = model(**deserialize_object(model, payload))
    obj.full_clean()
    return obj


@transaction.atomic
def apply_create(change_request: ChangeRequestField, reviewer: AbstractBaseUser) -> None:
    _guard(change_request, reviewer)

    model = change_request.content_type.model_class()  # pyrefly: ignore [missing-attribute]
    try:
        obj = build_create_instance(model, change_request.payload)  # pyrefly: ignore [bad-argument-type]
        obj.save()
    except ObjectDoesNotExist as exc:
        msg = "Create request references a target that no longer exists."
        raise ConflictError(msg) from exc
    except (ValidationError, IntegrityError) as exc:
        msg = f"Object could not be created: {exc}"
        raise ConflictError(msg) from exc

    change_request.object_id = obj.pk
    change_request.save(update_fields=["object_id", "updated"])


def apply_change(change_request: ChangeRequestField, reviewer: AbstractBaseUser) -> None:
    if change_request.change_type == ChangeTypeChoices.CREATE:
        apply_create(change_request, reviewer)
    else:
        apply_field(change_request, reviewer)
