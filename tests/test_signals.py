import pytest
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete
from django.test import override_settings
from mixer.backend.django import mixer

from django_approve.config import conf
from django_approve.cons import ApprovalStatusChoices, ChangeTypeChoices
from django_approve.models import ApprovalConfig, ChangeRequestField
from django_approve.registry import ApprovalRegistry
from django_approve.signals import (
    cleanup_orphan_requests,
    ensure_approval_group,
    sync_approval_configs,
)
from tests.models import Sample

EXPECTED_CODENAMES = {
    "view_changerequestfield",
    "change_changerequestfield",
    "view_approvalconfig",
    "change_approvalconfig",
}


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


@pytest.mark.django_db
class TestOrphanCleanup:
    @pytest.fixture(autouse=True)
    def orphan_cleanup(self, monkeypatch):
        reg = ApprovalRegistry()
        reg.register(Sample)
        monkeypatch.setattr("django_approve.signals.registry", reg)
        post_delete.connect(cleanup_orphan_requests, sender=Sample)
        yield
        post_delete.disconnect(cleanup_orphan_requests, sender=Sample)

    def test_deleting_target_marks_pending_request_deleted(self):
        sample = mixer.blend(Sample)
        request = _request_for(sample)

        sample.delete()

        request.refresh_from_db()
        assert request.status == ApprovalStatusChoices.DELETED

    def test_orphan_cleanup_keeps_terminal_requests(self):
        sample = mixer.blend(Sample)
        approved = _request_for(sample, status=ApprovalStatusChoices.APPROVED)
        rejected = _request_for(sample, status=ApprovalStatusChoices.REJECTED)

        sample.delete()

        approved.refresh_from_db()
        rejected.refresh_from_db()
        assert approved.status == ApprovalStatusChoices.APPROVED
        assert rejected.status == ApprovalStatusChoices.REJECTED

    def test_orphan_cleanup_scoped_to_deleted_object(self):
        sample = mixer.blend(Sample)
        other = mixer.blend(Sample)
        survivor = _request_for(other)

        sample.delete()

        survivor.refresh_from_db()
        assert survivor.status == ApprovalStatusChoices.PENDING


@pytest.mark.django_db
class TestSyncApprovalConfigs:
    @pytest.fixture
    def registered_sample(self, monkeypatch):
        reg = ApprovalRegistry()
        reg.register(Sample, fields=["amount", "name"])
        monkeypatch.setattr("django_approve.signals.registry", reg)
        monkeypatch.setattr("django_approve.fields.registry", reg)
        return reg

    def test_sync_creates_config_for_registered_model(self, registered_sample):
        sync_approval_configs(sender=None)

        config = ApprovalConfig.objects.get(content_type=ContentType.objects.get_for_model(Sample))
        assert config.tracked_fields == []

    def test_sync_prunes_tracked_fields_no_longer_approvable(self, registered_sample):
        config = mixer.blend(
            ApprovalConfig,
            content_type=ContentType.objects.get_for_model(Sample),
            tracked_fields=["amount", "owner"],
        )

        sync_approval_configs(sender=None)

        config.refresh_from_db()
        assert config.tracked_fields == ["amount"]

    def test_sync_deletes_orphaned_enabled_configs(self):
        orphan = mixer.blend(
            ApprovalConfig,
            content_type=ContentType.objects.get_for_model(Sample),
            is_enabled=True,
        )

        sync_approval_configs(sender=None)

        assert not ApprovalConfig.objects.filter(pk=orphan.pk).exists()


@pytest.mark.django_db
class TestEnsureApprovalGroup:
    def test_creates_group_with_permissions(self):
        Group.objects.filter(name=conf.GROUP_NAME).delete()

        ensure_approval_group(sender=None)

        group = Group.objects.get(name=conf.GROUP_NAME)
        codenames = set(group.permissions.values_list("codename", flat=True))
        assert codenames == EXPECTED_CODENAMES

    @override_settings(APPROVE_AUTO_CREATE_GROUP=False)
    def test_skips_when_disabled(self):
        Group.objects.filter(name=conf.GROUP_NAME).delete()

        ensure_approval_group(sender=None)

        assert not Group.objects.filter(name=conf.GROUP_NAME).exists()

    def test_resets_unexpected_permissions(self):
        group, _ = Group.objects.get_or_create(name=conf.GROUP_NAME)
        group.permissions.set(Permission.objects.exclude(codename__in=["view_changerequestfield"]))

        ensure_approval_group(sender=None)

        codenames = set(group.permissions.values_list("codename", flat=True))
        assert codenames == EXPECTED_CODENAMES
