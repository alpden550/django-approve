from collections import Counter

from django.contrib import admin, messages
from django.contrib.auth.models import AbstractBaseUser
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from django_approve.admin.filters import TargetModelFilter
from django_approve.config import conf
from django_approve.cons import ApprovalStatusChoices, ChangeTypeChoices
from django_approve.exceptions import ConflictError, SelfApprovalError
from django_approve.models.change_request import ChangeRequestField
from django_approve.services import apply_change


@admin.register(ChangeRequestField)
class ChangeRequestFieldAdmin(admin.ModelAdmin):
    list_display = (
        "content_type__model",
        "target",
        "change_type",
        "status",
        "summary",
        "field_name",
        "old_value",
        "new_value",
        "requested_by",
        "approved_by",
    )
    list_filter = ("status", "change_type", TargetModelFilter)
    readonly_fields = (
        "created",
        "content_type",
        "object_id",
        "target",
        "field_name",
        "change_type",
        "old_value",
        "new_value",
        "payload_display",
        "payload",
        "payload_hash",
        "requested_by",
        "approved_by",
    )
    actions = ("approve", "reject")
    list_select_related = ("content_type", "requested_by", "approved_by")

    _META_FIELDS = ("content_type", "object_id", "target", "change_type", "requested_by", "approved_by", "created")

    def get_queryset(self, request: HttpRequest) -> QuerySet[ChangeRequestField]:
        return super().get_queryset(request).prefetch_related("target")

    def get_fieldsets(self, request, obj=None):
        if obj is not None and obj.change_type == ChangeTypeChoices.CREATE:
            return (
                (None, {"fields": ("payload_display", "status")}),
                ("Request", {"fields": self._META_FIELDS}),
                ("Raw payload", {"classes": ("collapse",), "fields": ("payload", "payload_hash")}),
            )
        return (
            (None, {"fields": ("field_name", "old_value", "new_value", "status")}),
            ("Request", {"fields": self._META_FIELDS}),
        )

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    @staticmethod
    def _allowed_statuses(obj: ChangeRequestField, user: AbstractBaseUser) -> list[tuple[str, str]]:
        """Status choices selectable in the form for the given user.

        A terminal request is locked to its current status. For a `pending`
        request: `rejected` is the reviewer's verb (hidden from the author,
        whose withdrawal verb is `cancelled`); `approved` is also hidden from
        the author while four-eyes is on; `cancelled` is hidden from reviewers.
        `deleted` is system-only and never offered.
        """
        if obj.status != ApprovalStatusChoices.PENDING:
            return [(obj.status, ApprovalStatusChoices(obj.status).label)]

        excluded = {ApprovalStatusChoices.DELETED.value}
        is_author = obj.requested_by_id == user.pk  # pyrefly: ignore [missing-attribute]
        if is_author:
            excluded.add(ApprovalStatusChoices.REJECTED.value)
            if conf.REQUIRE_DIFFERENT_USER:
                excluded.add(ApprovalStatusChoices.APPROVED.value)
        else:
            excluded.add(ApprovalStatusChoices.CANCELLED.value)

        return [choice for choice in ApprovalStatusChoices.choices if choice[0] not in excluded]

    _SUMMARY_MAX_LEN = 80

    @admin.display(description="Summary")
    def summary(self, obj: ChangeRequestField) -> str:
        if obj.change_type == ChangeTypeChoices.CREATE:
            model = obj.content_type.model_class().__name__ if obj.content_type else "?"
            items = ", ".join(f"{name}={value}" for name, value in (obj.payload or {}).items())
            text = f"+ {model} ({items})"
            return text if len(text) <= self._SUMMARY_MAX_LEN else f"{text[: self._SUMMARY_MAX_LEN - 3]}…"
        return f"{obj.field_name}: {obj.old_value} → {obj.new_value}"

    @admin.display(description="Requested object")
    def payload_display(self, obj: ChangeRequestField) -> str:
        if not obj.payload:
            return "—"
        cell = "padding:6px 12px;border-bottom:1px solid var(--border-color)"
        head = f"{cell};background:var(--darkened-bg);font-weight:600;text-align:left"
        rows = format_html_join(
            "",
            f'<tr><th style="{head}">{{}}</th><td style="{cell}"><code>{{}}</code></td></tr>',
            ((name, value) for name, value in obj.payload.items()),
        )
        return format_html(
            '<table style="border-collapse:collapse;border:1px solid var(--border-color)">'
            f'<thead><tr><th style="{head}">Field</th><th style="{head}">Requested value</th></tr></thead>'
            "<tbody>{}</tbody></table>",
            rows,
        )

    def get_form(self, request, obj=None, change=False, **kwargs):  # noqa: FBT002
        form_class = super().get_form(request, obj, change=change, **kwargs)
        if obj is None:
            return form_class

        allowed = self._allowed_statuses(obj, request.user)

        class RestrictedStatusForm(form_class):
            def __init__(self, *args, **inner_kwargs):
                super().__init__(*args, **inner_kwargs)
                self.fields["status"].choices = allowed  # pyrefly: ignore [missing-attribute]

        return RestrictedStatusForm

    def save_model(self, request, obj, form, change) -> None:
        if "status" not in form.changed_data:
            super().save_model(request, obj, form, change)
            return

        obj.approved_by = request.user
        if obj.status == ApprovalStatusChoices.APPROVED:
            try:
                apply_change(change_request=obj, reviewer=request.user)  # pyrefly: ignore [bad-argument-type]
            except (ConflictError, SelfApprovalError) as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
                return
        super().save_model(request, obj, form, change)

    @staticmethod
    def _apply_one(change_request: ChangeRequestField, reviewer: AbstractBaseUser) -> str:
        try:
            apply_change(change_request=change_request, reviewer=reviewer)
        except ConflictError:
            return "conflict"
        except SelfApprovalError:
            return "blocked"

        change_request.status = ApprovalStatusChoices.APPROVED
        change_request.approved_by = reviewer  # pyrefly: ignore [bad-assignment]
        change_request.save(update_fields=["status", "approved_by", "updated"])
        return "applied"

    @admin.action(description="Approve selected change requests")
    def approve(self, request: HttpRequest, queryset: QuerySet[ChangeRequestField]) -> None:
        outcomes = Counter(
            self._apply_one(change_request, request.user)  # pyrefly: ignore [bad-argument-type]
            for change_request in queryset.filter(status=ApprovalStatusChoices.PENDING)
        )
        msg = f"Approved & applied: {outcomes['applied']}"
        if outcomes["conflict"]:
            msg += f"; skipped (conflict): {outcomes['conflict']}"
        if outcomes["blocked"]:
            msg += f"; skipped (self-approval): {outcomes['blocked']}"
        self.message_user(request, msg)

    @admin.action(description="Reject selected change requests")
    def reject(self, request: HttpRequest, queryset: QuerySet[ChangeRequestField]) -> None:
        updated = queryset.filter(status=ApprovalStatusChoices.PENDING).update(
            status=ApprovalStatusChoices.REJECTED,
            approved_by=request.user,
            updated=timezone.now(),
        )
        self.message_user(request, f"Rejected: {updated}")
