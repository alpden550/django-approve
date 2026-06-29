from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Model
from django.http import HttpResponseRedirect
from django.urls import reverse

from django_approve.config import conf
from django_approve.cons import ApprovalStatusChoices, ChangeTypeChoices
from django_approve.fields import get_tracked_fields
from django_approve.models import ChangeRequestField
from django_approve.registry import registry
from django_approve.serializers import (
    compute_payload_hash,
    serialize_object,
    serialize_value,
)
from django_approve.services import build_create_instance

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
            if conf.REQUIRE_CREATE_APPROVAL and self._is_tracked(obj.__class__):
                self._divert_create(request, obj)
                return
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

    @staticmethod
    def _is_tracked(model: type[Model]) -> bool:
        if not registry.is_registered(model):
            return False
        return bool(get_tracked_fields(model))

    def _divert_create(self, request, obj) -> None:
        request._approval_diverted = True
        payload = serialize_object(obj.__class__, obj)
        try:
            build_create_instance(obj.__class__, payload)
        except (ValidationError, ObjectDoesNotExist) as exc:
            request._approval_error = True
            self.message_user(
                request,
                f"Cannot submit for approval: {exc}",
                level=messages.ERROR,
            )
            return
        try:
            with transaction.atomic():
                ChangeRequestField.objects.create(
                    content_type=ContentType.objects.get_for_model(obj.__class__),
                    object_id=None,
                    field_name="",
                    change_type=ChangeTypeChoices.CREATE,
                    payload=payload,
                    payload_hash=compute_payload_hash(payload),
                    status=ApprovalStatusChoices.PENDING,
                    requested_by=request.user,
                )
        except IntegrityError:
            self.message_user(
                request,
                "An identical creation is already awaiting approval.",
                level=messages.WARNING,
            )
            return
        self.message_user(request, f"Submitted for approval (create): {obj.__class__.__name__}")

    def save_related(self, request, form, formsets, change) -> None:
        if getattr(request, "_approval_diverted", False):
            return
        super().save_related(request, form, formsets, change)

    def log_addition(self, request, obj, message):  # pyrefly: ignore [bad-override]
        if getattr(request, "_approval_diverted", False):
            return None
        return super().log_addition(request, obj, message)

    def response_add(self, request, obj, post_url_continue=None):
        if getattr(request, "_approval_diverted", False):
            if getattr(request, "_approval_error", False):
                return HttpResponseRedirect(request.path)
            url_name = f"{self.admin_site.name}:{obj._meta.app_label}_{obj._meta.model_name}_changelist"
            return HttpResponseRedirect(reverse(url_name))
        return super().response_add(request, obj, post_url_continue=post_url_continue)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["approval_pending"] = list(
            self._pending_qs(self.get_object(request, object_id)),
        )
        return super().change_view(request, object_id, form_url, extra_context)
