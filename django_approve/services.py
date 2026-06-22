from django.db import transaction

from django_approve.exceptions import ConflictError
from django_approve.models import ChangeRequestField
from django_approve.serializers import deserialize_value, serialize_value


@transaction.atomic
def apply_field(change_request: ChangeRequestField) -> None:
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
