import pytest
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory
from mixer.backend.django import mixer

from django_approve.config import conf
from django_approve.cons import ApprovalStatusChoices, ChangeTypeChoices
from django_approve.middlewares import PendingApprovalsNoticeMiddleware
from django_approve.models import ChangeRequestField
from tests.models import Sample


def _request_to(path, user):
    request = RequestFactory().get(path)
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def _approver(*, is_active=True):
    approver = mixer.blend("auth.User", is_active=is_active)
    group, _ = Group.objects.get_or_create(name=conf.GROUP_NAME)
    approver.groups.add(group)
    return approver


def _pending_request():
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
    )


@pytest.mark.django_db
class TestPendingApprovalsNoticeMiddleware:
    @pytest.fixture
    def middleware(self):
        return PendingApprovalsNoticeMiddleware(get_response=lambda request: "response")

    def test_notifies_approver_of_pending_requests_on_admin_index(self, middleware):
        approver = _approver()
        _pending_request()
        request = _request_to("/admin/", approver)

        middleware(request)

        messages = list(request._messages)
        assert len(messages) == 1
        assert "1 change request" in str(messages[0])

    def test_no_notice_without_pending_requests(self, middleware):
        approver = _approver()
        request = _request_to("/admin/", approver)

        middleware(request)

        assert not list(request._messages)

    def test_no_notice_for_non_approver(self, middleware):
        user = mixer.blend("auth.User", is_active=True)
        _pending_request()
        request = _request_to("/admin/", user)

        middleware(request)

        assert not list(request._messages)

    def test_no_notice_outside_admin_index(self, middleware):
        approver = _approver()
        _pending_request()
        request = _request_to("/admin/login/", approver)

        middleware(request)

        assert not list(request._messages)

    def test_no_notice_for_inactive_approver(self, middleware):
        approver = _approver(is_active=False)
        _pending_request()
        request = _request_to("/admin/", approver)

        middleware(request)

        assert not list(request._messages)
