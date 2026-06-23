import pytest
from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, override_settings
from mixer.backend.django import mixer

from django_approve.admin.change_request import ChangeRequestFieldAdmin
from django_approve.admin.mixins import ApprovalAdminMixin
from django_approve.cons import ApprovalStatusChoices, ChangeTypeChoices
from django_approve.models import ApprovalConfig, ChangeRequestField
from django_approve.registry import ApprovalRegistry
from tests.models import Sample

S = ApprovalStatusChoices

OLD_AMOUNT = 10
NEW_AMOUNT = 20


class SampleAdmin(ApprovalAdminMixin, admin.ModelAdmin):
    pass


class _FakeForm:
    def __init__(self, changed_data, cleaned_data):
        self.changed_data = changed_data
        self.cleaned_data = cleaned_data


@pytest.fixture
def change_admin():
    return ChangeRequestFieldAdmin(ChangeRequestField, AdminSite())


@pytest.fixture
def sample_admin():
    return SampleAdmin(Sample, AdminSite())


@pytest.fixture
def tracked_amount(db, monkeypatch):
    reg = ApprovalRegistry()
    reg.register(Sample)
    monkeypatch.setattr("django_approve.fields.registry", reg)
    return mixer.blend(
        ApprovalConfig,
        content_type=ContentType.objects.get_for_model(Sample),
        tracked_fields=["amount"],
        is_enabled=True,
    )


@pytest.fixture
def maker(db):
    return mixer.blend("auth.User")


def _request_by(requester):
    sample = mixer.blend(Sample)
    return mixer.blend(
        ChangeRequestField,
        content_type=ContentType.objects.get_for_model(Sample),
        object_id=sample.pk,
        field_name="amount",
        change_type=ChangeTypeChoices.UPDATE,
        old_value=1,
        new_value=2,
        status=ApprovalStatusChoices.PENDING,
        requested_by=requester,
    )


def _status_choices(change_admin, request, change_request):
    form_class = change_admin.get_form(request, obj=change_request)
    form = form_class(instance=change_request)
    return {value for value, _ in form.fields["status"].choices}


def _request_as(user):
    request = RequestFactory().get("/")
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def test_author_sees_only_pending_and_cancelled(change_admin, maker):
    change_request = _request_by(maker)

    choices = _status_choices(change_admin, _request_as(maker), change_request)

    assert choices == {S.PENDING, S.CANCELLED}


def test_reviewer_sees_pending_approved_rejected(change_admin, maker):
    change_request = _request_by(maker)
    checker = mixer.blend("auth.User")

    choices = _status_choices(change_admin, _request_as(checker), change_request)

    assert choices == {S.PENDING, S.APPROVED, S.REJECTED}


def test_deleted_is_never_offered(change_admin, maker):
    change_request = _request_by(maker)
    checker = mixer.blend("auth.User")

    author_choices = _status_choices(change_admin, _request_as(maker), change_request)
    reviewer_choices = _status_choices(change_admin, _request_as(checker), change_request)

    assert S.DELETED not in author_choices
    assert S.DELETED not in reviewer_choices


@override_settings(APPROVE_REQUIRE_DIFFERENT_USER=False)
def test_author_can_self_approve_when_four_eyes_disabled(change_admin, maker):
    change_request = _request_by(maker)

    choices = _status_choices(change_admin, _request_as(maker), change_request)
    assert choices == {S.PENDING, S.APPROVED, S.CANCELLED}


def test_save_model_creates_pending_request_and_reverts_tracked_field(sample_admin, tracked_amount, maker):
    sample = mixer.blend(Sample, amount=OLD_AMOUNT)
    form = _FakeForm(changed_data=["amount"], cleaned_data={"amount": NEW_AMOUNT})
    sample.amount = NEW_AMOUNT

    sample_admin.save_model(_request_as(maker), sample, form, change=True)

    change_request = ChangeRequestField.objects.get(
        content_type=ContentType.objects.get_for_model(Sample), object_id=sample.pk
    )
    assert change_request.field_name == "amount"
    assert change_request.old_value == OLD_AMOUNT
    assert change_request.new_value == NEW_AMOUNT
    assert change_request.status == S.PENDING
    assert change_request.requested_by == maker
    assert sample.amount == OLD_AMOUNT


def test_save_model_skips_untracked_field(sample_admin, maker, db):
    sample = mixer.blend(Sample, name="old")
    form = _FakeForm(changed_data=["name"], cleaned_data={"name": "new"})
    sample.name = "new"

    sample_admin.save_model(_request_as(maker), sample, form, change=True)

    assert not ChangeRequestField.objects.exists()
    sample.refresh_from_db()
    assert sample.name == "new"


def test_get_readonly_fields_locks_pending_field(sample_admin, maker):
    sample = mixer.blend(Sample, amount=OLD_AMOUNT)
    mixer.blend(
        ChangeRequestField,
        content_type=ContentType.objects.get_for_model(Sample),
        object_id=sample.pk,
        field_name="amount",
        change_type=ChangeTypeChoices.UPDATE,
        old_value=OLD_AMOUNT,
        new_value=NEW_AMOUNT,
        status=S.PENDING,
        requested_by=maker,
    )

    readonly = sample_admin.get_readonly_fields(_request_as(maker), sample)

    assert "amount" in readonly
