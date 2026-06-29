import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from django_approve.cons import ApprovalStatusChoices, ChangeTypeChoices
from django_approve.models import ChangeRequestField
from tests.models import Sample


def _ct():
    return ContentType.objects.get_for_model(Sample)


@pytest.mark.django_db
class TestChangeRequestStr:
    def test_create_str_names_the_model(self):
        cr = ChangeRequestField(
            content_type=_ct(),
            field_name="",
            change_type=ChangeTypeChoices.CREATE,
            payload={"amount": 1},
        )
        assert str(cr) == f"Create {_ct().name}"


@pytest.mark.django_db
class TestChangeRequestClean:
    def test_update_row_with_payload_is_invalid(self):
        cr = ChangeRequestField(
            content_type=_ct(),
            object_id=1,
            field_name="amount",
            change_type=ChangeTypeChoices.UPDATE,
            payload={"amount": 1},
        )
        with pytest.raises(ValidationError):
            cr.clean()

    def test_create_row_without_payload_is_invalid(self):
        cr = ChangeRequestField(
            content_type=_ct(),
            field_name="",
            change_type=ChangeTypeChoices.CREATE,
            payload=None,
        )
        with pytest.raises(ValidationError):
            cr.clean()

    def test_create_row_with_field_name_is_invalid(self):
        cr = ChangeRequestField(
            content_type=_ct(),
            field_name="amount",
            change_type=ChangeTypeChoices.CREATE,
            payload={"amount": 1},
        )
        with pytest.raises(ValidationError):
            cr.clean()

    def test_valid_create_row_passes_clean(self):
        cr = ChangeRequestField(
            content_type=_ct(),
            field_name="",
            change_type=ChangeTypeChoices.CREATE,
            payload={"amount": 1},
            payload_hash="abc",
        )
        cr.clean()  # shape-only validation; clean_fields/db are covered separately

    def test_applied_create_row_with_object_id_passes_clean(self):
        cr = ChangeRequestField(
            content_type=_ct(),
            object_id=42,
            field_name="",
            change_type=ChangeTypeChoices.CREATE,
            payload={"amount": 1},
            payload_hash="abc",
            status=ApprovalStatusChoices.APPROVED,
        )
        cr.clean()

    def test_valid_update_row_passes_clean(self):
        cr = ChangeRequestField(
            content_type=_ct(),
            object_id=1,
            field_name="amount",
            change_type=ChangeTypeChoices.UPDATE,
            old_value=1,
            new_value=2,
        )
        cr.clean()


@pytest.mark.django_db
class TestChangeRequestConstraints:
    def _make_create(self, payload_hash, status=ApprovalStatusChoices.PENDING):
        # Bypass full_clean (which would catch shape issues earlier) to hit the DB constraint.
        return ChangeRequestField(
            content_type=_ct(),
            field_name="",
            change_type=ChangeTypeChoices.CREATE,
            payload={"amount": 1},
            payload_hash=payload_hash,
            status=status,
        )

    def test_check_constraint_rejects_create_without_payload(self):
        bad = ChangeRequestField(
            content_type=_ct(),
            field_name="",
            change_type=ChangeTypeChoices.CREATE,
            payload=None,
            payload_hash=None,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            bad.save()

    def test_create_lock_blocks_identical_pending_payload(self):
        self._make_create("hash-1").save()
        with pytest.raises(IntegrityError), transaction.atomic():
            self._make_create("hash-1").save()

    def test_create_lock_allows_distinct_payload(self):
        self._make_create("hash-1").save()
        self._make_create("hash-2").save()
        assert ChangeRequestField.objects.filter(change_type=ChangeTypeChoices.CREATE).count() == 2

    def test_create_lock_ignores_terminal_rows(self):
        self._make_create("hash-1", status=ApprovalStatusChoices.APPROVED).save()
        self._make_create("hash-1", status=ApprovalStatusChoices.PENDING).save()
        assert ChangeRequestField.objects.filter(payload_hash="hash-1").count() == 2
