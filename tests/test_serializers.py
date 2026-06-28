import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from hypothesis import given
from hypothesis import strategies as st
from mixer.backend.django import mixer

from django_approve.serializers import deserialize_value, serialize_value
from tests.models import Sample


@given(value=st.dates(min_value=datetime.date(1900, 1, 1), max_value=datetime.date(2100, 1, 1)))
def test_date_field_roundtrip(value):
    serialized = serialize_value(Sample, "event_date", value)
    assert deserialize_value(Sample, "event_date", serialized) == value


@given(
    value=st.decimals(
        min_value=Decimal("-99999999.99"),
        max_value=Decimal("99999999.99"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_decimal_field_roundtrip(value):
    serialized = serialize_value(Sample, "price", value)
    assert deserialize_value(Sample, "price", serialized) == value


def test_none_roundtrip():
    assert serialize_value(Sample, "event_date", None) is None
    assert deserialize_value(Sample, "event_date", None) is None


def test_fk_serializes_to_pk(db):
    owner = mixer.blend(User)
    sample = mixer.blend(Sample, owner=owner)

    assert serialize_value(Sample, "owner", sample.owner) == owner.pk


def test_fk_deserializes_to_instance(db):
    owner = mixer.blend(User)

    resolved = deserialize_value(Sample, "owner", owner.pk)

    assert resolved == owner


def test_fk_deserialize_raises_when_target_deleted(db):
    owner = mixer.blend(User)
    owner_pk = owner.pk
    owner.delete()

    with pytest.raises(User.DoesNotExist):
        deserialize_value(Sample, "owner", owner_pk)


class TestObjectSerializers:
    def test_serialize_object_snapshots_candidate_fields(self, db):
        owner = mixer.blend(User)
        sample = mixer.blend(Sample, name="n", amount=7, owner=owner, event_date=None, price=None)

        from django_approve.serializers import serialize_object

        payload = serialize_object(Sample, sample)

        assert payload["name"] == "n"
        assert payload["amount"] == 7
        assert payload["owner"] == owner.pk
        assert "attachment" not in payload  # FileField excluded
        assert "tags" not in payload  # M2M excluded
        assert "id" not in payload  # pk excluded

    def test_deserialize_object_round_trip(self, db):
        owner = mixer.blend(User)
        sample = mixer.blend(Sample, name="n", amount=7, owner=owner, event_date=None, price=None)

        from django_approve.serializers import deserialize_object, serialize_object

        payload = serialize_object(Sample, sample)
        kwargs = deserialize_object(Sample, payload)

        assert kwargs["name"] == "n"
        assert kwargs["amount"] == 7
        assert kwargs["owner"] == owner

    def test_deserialize_object_raises_when_fk_missing(self, db):
        from django_approve.serializers import deserialize_object

        with pytest.raises(User.DoesNotExist):
            deserialize_object(Sample, {"owner": 99999999})

    def test_compute_payload_hash_is_key_order_independent(self):
        from django_approve.serializers import compute_payload_hash

        assert compute_payload_hash({"a": 1, "b": 2}) == compute_payload_hash({"b": 2, "a": 1})

    def test_compute_payload_hash_differs_on_value_change(self):
        from django_approve.serializers import compute_payload_hash

        assert compute_payload_hash({"a": 1}) != compute_payload_hash({"a": 2})
