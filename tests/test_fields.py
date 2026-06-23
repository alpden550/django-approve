import pytest

from django_approve.fields import get_approvable_fields, get_candidate_fields
from django_approve.registry import ApprovalRegistry
from tests.models import Sample

EXPECTED_CANDIDATES = ["name", "amount", "owner", "event_date", "price"]


def test_candidate_fields_are_concrete_editable_supported():
    assert get_candidate_fields(Sample) == EXPECTED_CANDIDATES


@pytest.mark.parametrize("excluded", ["id", "created", "updated", "readonly", "attachment", "tags"])
def test_candidate_fields_exclude(excluded):
    assert excluded not in get_candidate_fields(Sample)


@pytest.fixture
def fresh_registry(monkeypatch):
    reg = ApprovalRegistry()
    monkeypatch.setattr("django_approve.fields.registry", reg)
    return reg


def test_approvable_fields_all_when_unrestricted(fresh_registry):
    fresh_registry.register(Sample)

    assert get_approvable_fields(Sample) == EXPECTED_CANDIDATES


def test_approvable_fields_intersect_whitelist_preserving_candidate_order(fresh_registry):
    fresh_registry.register(Sample, fields=["amount", "name", "missing"])

    assert get_approvable_fields(Sample) == ["name", "amount"]
