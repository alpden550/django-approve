from typing import TYPE_CHECKING

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model

from django_approve.cons import ApprovalStatusChoices, ChangeTypeChoices
from django_approve.fields import get_tracked_fields
from django_approve.models import ChangeRequestField
from django_approve.serializers import serialize_value

_Base = object
if TYPE_CHECKING:
    from django.contrib import admin

    _Base = admin.ModelAdmin


class ApprovalAdminMixin(_Base):
    """
    Mixin for approval-based modification of model instances in a Django admin interface.

    This class integrates approval workflows into the Django admin panel by managing
    tracked fields, pending change requests, and ensuring readonly states for locked fields.
    It allows administrators to submit field changes for approval before modifying the
    underlying model instance.

    Attributes:
        change_form_template (str): Path to the template used for rendering the change
            form in the admin interface.
    """

    change_form_template = "django_approve/target_change_form.html"

    @staticmethod
    def _pending_qs(obj: Model | None):
        if obj is None or obj.pk is None:
            return ChangeRequestField.objects.none()

        content_type = ContentType.objects.get_for_model(obj.__class__)
        return ChangeRequestField.objects.filter(
            content_type=content_type,
            object_id=obj.pk,
            status=ApprovalStatusChoices.PENDING,
        )

    def _locked_fields(self, obj: Model | None) -> set[str]:
        return set(self._pending_qs(obj).values_list("field_name", flat=True))

    def get_readonly_fields(self, request, obj=None):
        readonly = set(super().get_readonly_fields(request, obj))
        return tuple(readonly | self._locked_fields(obj))

    def save_model(self, request, obj, form, change) -> None:
        if not change:
            super().save_model(request, obj, form, change)
            return

        tracked = set(get_tracked_fields(model=obj.__class__))
        changed_tracked = [name for name in form.changed_data if name in tracked]
        if not changed_tracked:
            super().save_model(request, obj, form, change)
            return

        content_type = ContentType.objects.get_for_model(obj.__class__)
        original = obj.__class__.objects.get(pk=obj.pk)

        for name in changed_tracked:
            ChangeRequestField.objects.create(
                content_type=content_type,
                object_id=obj.pk,
                field_name=name,
                change_type=ChangeTypeChoices.UPDATE,
                old_value=serialize_value(obj.__class__, name, getattr(original, name)),
                new_value=serialize_value(obj.__class__, name, form.cleaned_data[name]),
                status=ApprovalStatusChoices.PENDING,
                requested_by=request.user,
            )
            # Revert tracked changes
            setattr(obj, name, getattr(original, name))

        super().save_model(request, obj, form, change)
        self.message_user(request, f"Submitted for approval: {', '.join(changed_tracked)}")

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["approval_pending"] = list(
            self._pending_qs(self.get_object(request, object_id)),
        )
        return super().change_view(request, object_id, form_url, extra_context)
