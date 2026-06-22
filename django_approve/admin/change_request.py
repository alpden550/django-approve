from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest

from django_approve.admin.filters import TargetModelFilter
from django_approve.cons import ApprovalStatusChoices
from django_approve.exceptions import ConflictError
from django_approve.models.change_request import ChangeRequestField
from django_approve.services import apply_field


@admin.register(ChangeRequestField)
class ChangeRequestFieldAdmin(admin.ModelAdmin):
    list_display = (
        "content_type__model",
        "target",
        "change_type",
        "status",
        "field_name",
        "old_value",
        "new_value",
        "requested_by",
        "approved_by",
    )
    list_filter = ("status", "change_type", TargetModelFilter)
    readonly_fields = (
        "content_type",
        "object_id",
        "target",
        "field_name",
        "change_type",
        "old_value",
        "new_value",
        "requested_by",
        "approved_by",
    )
    actions = ("approve", "reject")
    list_select_related = ("content_type", "requested_by", "approved_by")

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def save_model(self, request, obj, form, change) -> None:
        if "status" in form.changed_data:
            obj.approved_by = request.user
        super().save_model(request, obj, form, change)

        status_changed = "status" in form.changed_data
        if status_changed and obj.status == ApprovalStatusChoices.APPROVED:
            try:
                apply_field(change_request=obj)
            except ConflictError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)

    @admin.action(description="Approve selected change requests")
    def approve(self, request: HttpRequest, queryset: QuerySet[ChangeRequestField]) -> None:
        applied, conflicts = 0, 0
        for change_request in queryset.filter(status=ApprovalStatusChoices.PENDING):
            try:
                apply_field(change_request=change_request)
            except ConflictError:
                conflicts += 1
                continue

            change_request.status = ApprovalStatusChoices.APPROVED
            change_request.approved_by = request.user  # pyrefly: ignore [bad-assignment]
            change_request.save(update_fields=["status", "approved_by", "updated"])
            applied += 1

        msg = f"Approved & applied: {applied}"
        if conflicts:
            msg += f"; skipped (conflict): {conflicts}"
        self.message_user(request, msg)

    @admin.action(description="Reject selected change requests")
    def reject(self, request: HttpRequest, queryset: QuerySet[ChangeRequestField]) -> None:
        updated = queryset.filter(status=ApprovalStatusChoices.PENDING).update(
            status=ApprovalStatusChoices.REJECTED,
            approved_by=request.user,
        )
        self.message_user(request, f"Rejected: {updated}")
