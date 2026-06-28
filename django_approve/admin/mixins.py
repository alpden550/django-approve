from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
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
    """Diverts admin edits to tracked fields into pending `ChangeRequestField` rows.

    Only intercepts saves made through this admin; calling `.save()` directly
    from code bypasses the approval flow entirely.
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
        readonly = list(super().get_readonly_fields(request, obj))
        readonly += [name for name in sorted(self._locked_fields(obj)) if name not in readonly]
        return tuple(readonly)

    def save_model(self, request, obj, form, change) -> None:
        if not change:
            super().save_model(request, obj, form, change)
            return

        tracked = set(get_tracked_fields(model=obj.__class__))
        changed_tracked = [name for name in form.changed_data if name in tracked]
        if not changed_tracked:
            super().save_model(request, obj, form, change)
            return

        self._divert_tracked_fields(request, obj, form, changed_tracked)
        super().save_model(request, obj, form, change)

    def _divert_tracked_fields(self, request, obj, form, changed_tracked: list[str]) -> None:
        original = obj.__class__.objects.get(pk=obj.pk)

        submitted: list[str] = []
        conflicted: list[str] = []
        for name in changed_tracked:
            created = self._create_pending(request, obj, form, original, name)
            (submitted if created else conflicted).append(name)
            # Keep the old value so Django's save doesn't write the new one to the row.
            setattr(obj, name, getattr(original, name))

        if submitted:
            self.message_user(request, f"Submitted for approval: {', '.join(submitted)}")
        if conflicted:
            self.message_user(
                request,
                f"Already awaiting approval, not resubmitted: {', '.join(conflicted)}",
                level=messages.WARNING,
            )

    @staticmethod
    def _create_pending(request, obj, form, original, name: str) -> bool:
        """Create a pending request for one field; return False if one already exists.

        A pending request for this field may already exist (concurrent edit); the partial
        unique constraint rejects the duplicate. The insert runs in its own savepoint, so a
        conflict on one field doesn't poison the others or the admin transaction.
        """
        try:
            with transaction.atomic():
                ChangeRequestField.objects.create(
                    content_type=ContentType.objects.get_for_model(obj.__class__),
                    object_id=obj.pk,
                    field_name=name,
                    change_type=ChangeTypeChoices.UPDATE,
                    old_value=serialize_value(obj.__class__, name, getattr(original, name)),
                    new_value=serialize_value(obj.__class__, name, form.cleaned_data[name]),
                    status=ApprovalStatusChoices.PENDING,
                    requested_by=request.user,
                )
        except IntegrityError:
            return False
        return True

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["approval_pending"] = list(
            self._pending_qs(self.get_object(request, object_id)),
        )
        return super().change_view(request, object_id, form_url, extra_context)
