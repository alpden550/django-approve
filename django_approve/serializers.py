import json
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Field, Model


def serialize_value(model: type[Model], field_name: str, value: Any) -> Any:
    field: Field = model._meta.get_field(field_name)  # pyrefly: ignore [bad-assignment]
    if value is None:
        return None

    if field.is_relation:
        return value.pk if isinstance(value, Model) else value

    return json.loads(json.dumps(field.get_prep_value(value), cls=DjangoJSONEncoder))


def deserialize_value(model: type[Model], field_name: str, raw: Any) -> Any:
    field: Field = model._meta.get_field(field_name)  # pyrefly: ignore [bad-assignment]
    if raw is None:
        return None

    if field.is_relation:
        related_model = field.related_model
        if related_model is None:
            return raw
        return related_model._base_manager.get(pk=raw)

    return field.to_python(raw)
