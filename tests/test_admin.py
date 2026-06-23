import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, override_settings
from mixer.backend.django import mixer

from django_approve.admin.change_request import ChangeRequestFieldAdmin
from django_approve.cons import ApprovalStatusChoices, ChangeTypeChoices
from django_approve.models import ChangeRequestField
from tests.models import Sample

S = ApprovalStatusChoices


@pytest.fixture
def change_admin():
    return ChangeRequestFieldAdmin(ChangeRequestField, AdminSite())


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

    # four-eyes off lets the author self-approve, but `rejected` stays a reviewer-only verb
    assert choices == {S.PENDING, S.APPROVED, S.CANCELLED}
