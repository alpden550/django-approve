import hashlib
import json
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Field, Model

from django_approve.fields import get_candidate_fields


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


def serialize_object(model: type[Model], instance: Model) -> dict[str, Any]:
    """Snapshot all create-eligible fields of an instance into JSON primitives."""
    return {name: serialize_value(model, name, getattr(instance, name)) for name in get_candidate_fields(model)}


def deserialize_object(model: type[Model], payload: dict[str, Any]) -> dict[str, Any]:
    """Build kwargs for model(**kwargs); FK values resolve to instances (may raise ObjectDoesNotExist)."""
    return {name: deserialize_value(model, name, raw) for name, raw in payload.items()}


def compute_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
