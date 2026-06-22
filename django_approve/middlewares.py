from collections.abc import Callable

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils.html import format_html

from django_approve.config import conf
from django_approve.cons import ApprovalStatusChoices
from django_approve.models import ChangeRequestField


class PendingApprovalsNoticeMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self._maybe_notify(request)
        return self.get_response(request)

    @staticmethod
    def _maybe_notify(request: HttpRequest) -> None:
        if request.method != "GET" or not request.path.startswith("/admin/"):
            return

        if request.path != reverse("admin:index"):
            return

        user = getattr(request, "user", None)
        if user is None or not user.is_active or not user.groups.filter(name=conf.GROUP_NAME).exists():
            return

        pending = ChangeRequestField.objects.filter(
            status=ApprovalStatusChoices.PENDING,
        ).count()
        if not pending:
            return

        url = reverse("admin:django_approve_changerequestfield_changelist")
        messages.warning(
            request,
            format_html(
                'You have {} change request(s) awaiting review. <a href="{}?status__exact={}">Review now</a>.',
                pending,
                url,
                ApprovalStatusChoices.PENDING,
            ),
        )
