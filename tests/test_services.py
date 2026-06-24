import pytest
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from mixer.backend.django import mixer

from django_approve.cons import ApprovalStatusChoices, ChangeTypeChoices
from django_approve.exceptions import ConflictError, SelfApprovalError
from django_approve.models import ChangeRequestField
from django_approve.services import apply_field
from tests.models import Sample

OLD_AMOUNT = 10
NEW_AMOUNT = 20


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


@pytest.mark.django_db
class TestApplyField:
    @pytest.fixture
    def sample(self):
        return mixer.blend(Sample, amount=OLD_AMOUNT)

    def test_apply_field_blocks_self_approval(self, sample):
        maker = mixer.blend(User)
        change_request = _make_request(sample, requested_by=maker)

        with pytest.raises(SelfApprovalError):
            apply_field(change_request=change_request, reviewer=maker)

        sample.refresh_from_db()
        assert sample.amount == OLD_AMOUNT

    def test_apply_field_allows_different_reviewer(self, sample):
        maker = mixer.blend(User)
        checker = mixer.blend(User)
        change_request = _make_request(sample, requested_by=maker)

        apply_field(change_request=change_request, reviewer=checker)

        sample.refresh_from_db()
        assert sample.amount == NEW_AMOUNT

    @override_settings(APPROVE_REQUIRE_DIFFERENT_USER=False)
    def test_apply_field_allows_self_approval_when_disabled(self, sample):
        maker = mixer.blend(User)
        change_request = _make_request(sample, requested_by=maker)

        apply_field(change_request=change_request, reviewer=maker)

        sample.refresh_from_db()
        assert sample.amount == NEW_AMOUNT

    def test_apply_field_raises_conflict_when_fk_target_deleted(self, sample):
        maker = mixer.blend(User)
        checker = mixer.blend(User)
        new_owner = mixer.blend(User)
        new_owner_pk = new_owner.pk
        change_request = mixer.blend(
            ChangeRequestField,
            content_type=ContentType.objects.get_for_model(Sample),
            object_id=sample.pk,
            field_name="owner",
            change_type=ChangeTypeChoices.UPDATE,
            old_value=sample.owner_id,
            new_value=new_owner_pk,
            status=ApprovalStatusChoices.PENDING,
            requested_by=maker,
            approved_by=None,
        )
        new_owner.delete()

        with pytest.raises(ConflictError):
            apply_field(change_request=change_request, reviewer=checker)

    def test_apply_field_raises_conflict_when_object_deleted(self, sample):
        maker = mixer.blend(User)
        checker = mixer.blend(User)
        change_request = _make_request(sample, requested_by=maker)
        sample.delete()

        with pytest.raises(ConflictError):
            apply_field(change_request=change_request, reviewer=checker)

    def test_apply_field_rejects_non_pending_request(self, sample):
        maker = mixer.blend(User)
        checker = mixer.blend(User)
        change_request = _make_request(sample, requested_by=maker)
        change_request.status = ApprovalStatusChoices.REJECTED
        change_request.save(update_fields=["status"])

        with pytest.raises(ConflictError):
            apply_field(change_request=change_request, reviewer=checker)

        sample.refresh_from_db()
        assert sample.amount == OLD_AMOUNT

    def test_apply_field_does_not_fetch_old_fk_target(self, sample, django_assert_max_num_queries):
        maker = mixer.blend(User)
        checker = mixer.blend(User)
        new_owner = mixer.blend(User)
        change_request = mixer.blend(
            ChangeRequestField,
            content_type=ContentType.objects.get_for_model(Sample),
            object_id=sample.pk,
            field_name="owner",
            change_type=ChangeTypeChoices.UPDATE,
            old_value=sample.owner_id,
            new_value=new_owner.pk,
            status=ApprovalStatusChoices.PENDING,
            requested_by=maker,
            approved_by=None,
        )

        with django_assert_max_num_queries(5):
            apply_field(change_request=change_request, reviewer=checker)
