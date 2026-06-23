import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from django_approve.fields import get_approvable_fields, get_candidate_fields, prune_tracked_fields
from django_approve.registry import ApprovalRegistry
from tests.models import Sample

EXPECTED_CANDIDATES = ["name", "amount", "owner", "event_date", "price"]
FIELD_NAME_POOL = [*EXPECTED_CANDIDATES, "invalid", "missing", "unknown"]


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


@pytest.fixture
def registered_sample(monkeypatch):
    reg = ApprovalRegistry()
    reg.register(Sample)
    monkeypatch.setattr("django_approve.fields.registry", reg)
    return reg


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(tracked_fields=st.lists(st.sampled_from(FIELD_NAME_POOL)))
def test_prune_tracked_fields_keeps_only_approvable_names_in_order(registered_sample, tracked_fields):
    valid = set(get_approvable_fields(Sample))

    pruned = prune_tracked_fields(Sample, tracked_fields)

    assert pruned == [name for name in tracked_fields if name in valid]


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(tracked_fields=st.lists(st.sampled_from(FIELD_NAME_POOL)))
def test_prune_tracked_fields_is_idempotent(registered_sample, tracked_fields):
    once = prune_tracked_fields(Sample, tracked_fields)

    assert prune_tracked_fields(Sample, once) == once
