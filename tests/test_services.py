import pytest
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from mixer.backend.django import mixer

from django_approve.cons import ApprovalStatusChoices, ChangeTypeChoices
from django_approve.exceptions import SelfApprovalError
from django_approve.models import ChangeRequestField
from django_approve.services import apply_field
from tests.models import Sample

OLD_AMOUNT = 10
NEW_AMOUNT = 20


@pytest.fixture
def sample(db):
    return mixer.blend(Sample, amount=OLD_AMOUNT)


def _make_request(sample, requested_by, *, old_value=OLD_AMOUNT, new_value=NEW_AMOUNT):
    return mixer.blend(
        ChangeRequestField,
        content_type=ContentType.objects.get_for_model(Sample),
        object_id=sample.pk,
        field_name="amount",
        change_type=ChangeTypeChoices.UPDATE,
        old_value=old_value,
        new_value=new_value,
        status=ApprovalStatusChoices.PENDING,
        requested_by=requested_by,
        approved_by=None,
    )


def test_apply_field_blocks_self_approval(sample):
    maker = mixer.blend(User)
    change_request = _make_request(sample, requested_by=maker)

    with pytest.raises(SelfApprovalError):
        apply_field(change_request=change_request, reviewer=maker)

    sample.refresh_from_db()
    assert sample.amount == OLD_AMOUNT


def test_apply_field_allows_different_reviewer(sample):
    maker = mixer.blend(User)
    checker = mixer.blend(User)
    change_request = _make_request(sample, requested_by=maker)

    apply_field(change_request=change_request, reviewer=checker)

    sample.refresh_from_db()
    assert sample.amount == NEW_AMOUNT


@override_settings(APPROVE_REQUIRE_DIFFERENT_USER=False)
def test_apply_field_allows_self_approval_when_disabled(sample):
    maker = mixer.blend(User)
    change_request = _make_request(sample, requested_by=maker)

    apply_field(change_request=change_request, reviewer=maker)

    sample.refresh_from_db()
    assert sample.amount == NEW_AMOUNT
