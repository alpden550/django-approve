from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction

from django_approve.config import conf
from django_approve.exceptions import ConflictError, SelfApprovalError
from django_approve.models import ChangeRequestField
from django_approve.serializers import deserialize_value, serialize_value


@transaction.atomic
def apply_field(change_request: ChangeRequestField, reviewer: AbstractBaseUser) -> None:
    # pyrefly: ignore [missing-attribute]
    if conf.REQUIRE_DIFFERENT_USER and change_request.requested_by_id == reviewer.pk:
        msg = f"Field '{change_request.field_name}' cannot be approved by its own requester."
        raise SelfApprovalError(msg)

    target_cls = change_request.content_type.model_class()  # pyrefly: ignore [missing-attribute]
    obj = target_cls.objects.select_for_update().get(pk=change_request.object_id)

    field = target_cls._meta.get_field(change_request.field_name)
    attr = field.attname if field.is_relation else field.name

    current = serialize_value(target_cls, field.name, getattr(obj, field.name))
    if current != change_request.old_value:
        msg = f"Field '{field.name}' changed since the request was made."
        raise ConflictError(msg)

    value = deserialize_value(target_cls, change_request.field_name, change_request.new_value)
    setattr(obj, attr, value)
    obj.save(update_fields=[attr])
