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
