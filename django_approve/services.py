from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction

from django_approve.config import conf
from django_approve.cons import ApprovalStatusChoices
from django_approve.exceptions import ConflictError, SelfApprovalError
from django_approve.models import ChangeRequestField
from django_approve.serializers import deserialize_value, serialize_value


def _lock_target(target_cls: type[models.Model], object_id: int | None, field_name: str) -> models.Model:
    try:
        return target_cls.objects.select_for_update().get(pk=object_id)
    except ObjectDoesNotExist as exc:
        msg = f"Target of field '{field_name}' no longer exists."
        raise ConflictError(msg) from exc


@transaction.atomic
def apply_field(change_request: ChangeRequestField, reviewer: AbstractBaseUser) -> None:
    if change_request.status != ApprovalStatusChoices.PENDING:
        msg = f"Field '{change_request.field_name}' is no longer pending."
        raise ConflictError(msg)

    # pyrefly: ignore [missing-attribute]
    if conf.REQUIRE_DIFFERENT_USER and change_request.requested_by_id == reviewer.pk:
        msg = f"Field '{change_request.field_name}' cannot be approved by its own requester."
        raise SelfApprovalError(msg)

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
