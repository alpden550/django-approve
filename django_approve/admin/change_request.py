from django.contrib import admin

from django_approve.admin.filters import TargetModelFilter
from django_approve.cons import ApprovalStatusChoices
from django_approve.models.change_request import ChangeRequestField


@admin.register(ChangeRequestField)
class ChangeRequestFieldAdmin(admin.ModelAdmin):
    list_display = ("target", "change_type", "status", "requested_by", "field_name", "old_value", "new_value")
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

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def save_model(self, request, obj, form, change) -> None:
        if "status" in form.changed_data:
            obj.approved_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Approve selected change requests")
    def approve(self, request, queryset) -> None:
        updated = queryset.filter(status=ApprovalStatusChoices.PENDING).update(
            status=ApprovalStatusChoices.APPROVED,
            approved_by=request.user,
        )
        self.message_user(request, f"Approved: {updated}")

    @admin.action(description="Reject selected change requests")
    def reject(self, request, queryset) -> None:
        updated = queryset.filter(status=ApprovalStatusChoices.PENDING).update(
            status=ApprovalStatusChoices.REJECTED,
            approved_by=request.user,
        )
        self.message_user(request, f"Rejected: {updated}")
