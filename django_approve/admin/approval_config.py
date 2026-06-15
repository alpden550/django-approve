from django.contrib import admin

from django_approve.admin.forms import ApprovalConfigForm
from django_approve.models import ApprovalConfig


@admin.register(ApprovalConfig)
class ApprovalConfigAdmin(admin.ModelAdmin):
    form = ApprovalConfigForm
    list_display = ("content_type", "is_enabled", "tracked_fields")
    list_filter = ("is_enabled",)
    list_select_related = ("content_type",)
    readonly_fields = ("content_type",)
