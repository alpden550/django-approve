import pytest
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete
from mixer.backend.django import mixer

from django_approve.cons import ApprovalStatusChoices, ChangeTypeChoices
from django_approve.models import ChangeRequestField
from django_approve.registry import ApprovalRegistry
from django_approve.signals import cleanup_orphan_requests
from tests.models import Sample


@pytest.fixture
def orphan_cleanup(monkeypatch):
    reg = ApprovalRegistry()
    reg.register(Sample)
    monkeypatch.setattr("django_approve.signals.registry", reg)
    post_delete.connect(cleanup_orphan_requests, sender=Sample)
    yield
    post_delete.disconnect(cleanup_orphan_requests, sender=Sample)


def _request_for(obj, status=ApprovalStatusChoices.PENDING):
    return mixer.blend(
        ChangeRequestField,
        content_type=ContentType.objects.get_for_model(type(obj)),
        object_id=obj.pk,
        field_name="amount",
        change_type=ChangeTypeChoices.UPDATE,
        old_value=1,
        new_value=2,
        status=status,
    )


@pytest.mark.usefixtures("orphan_cleanup")
def test_deleting_target_marks_pending_request_deleted(db):
    sample = mixer.blend(Sample)
    request = _request_for(sample)

    sample.delete()

    request.refresh_from_db()
    assert request.status == ApprovalStatusChoices.DELETED


@pytest.mark.usefixtures("orphan_cleanup")
def test_orphan_cleanup_keeps_terminal_requests(db):
    sample = mixer.blend(Sample)
    approved = _request_for(sample, status=ApprovalStatusChoices.APPROVED)
    rejected = _request_for(sample, status=ApprovalStatusChoices.REJECTED)

    sample.delete()

    approved.refresh_from_db()
    rejected.refresh_from_db()
    assert approved.status == ApprovalStatusChoices.APPROVED
    assert rejected.status == ApprovalStatusChoices.REJECTED


@pytest.mark.usefixtures("orphan_cleanup")
def test_orphan_cleanup_scoped_to_deleted_object(db):
    sample = mixer.blend(Sample)
    other = mixer.blend(Sample)
    survivor = _request_for(other)

    sample.delete()

    survivor.refresh_from_db()
    assert survivor.status == ApprovalStatusChoices.PENDING
