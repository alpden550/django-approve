from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from django_approve.cons import ApprovalStatusChoices, ChangeTypeChoices

User = get_user_model()


class ChangeRequestField(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    content_type = models.ForeignKey("contenttypes.ContentType", on_delete=models.SET_NULL, null=True)
    object_id = models.PositiveBigIntegerField(null=True)
    target = GenericForeignKey("content_type", "object_id")
    field_name = models.CharField(max_length=255)
    change_type = models.CharField(max_length=10, choices=ChangeTypeChoices.choices)
    old_value = models.JSONField(null=True)
    new_value = models.JSONField(null=True)
    payload = models.JSONField(null=True, blank=True)
    payload_hash = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=ApprovalStatusChoices.choices,
        default=ApprovalStatusChoices.PENDING,
    )
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_change_fields",
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_change_fields",
    )

    class Meta:
        verbose_name = "change request field"
        verbose_name_plural = "change request fields"
        ordering = ("-created",)
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("content_type", "object_id", "field_name"),
                condition=Q(status=ApprovalStatusChoices.PENDING),
                name="uniq_pending_lock_per_object_field",
            ),
            models.UniqueConstraint(
                fields=("content_type", "payload_hash"),
                condition=Q(status=ApprovalStatusChoices.PENDING),
                name="uniq_pending_create_per_payload",
            ),
            models.CheckConstraint(
                name="changerequest_shape_by_change_type",
                condition=(
                    (
                        Q(change_type=ChangeTypeChoices.UPDATE)
                        & Q(payload__isnull=True)
                        & Q(payload_hash__isnull=True)
                        & ~Q(field_name="")
                        & Q(object_id__isnull=False)
                    )
                    | (
                        Q(change_type=ChangeTypeChoices.CREATE)
                        & Q(payload__isnull=False)
                        & Q(payload_hash__isnull=False)
                        & Q(field_name="")
                        & Q(old_value__isnull=True)
                        & Q(new_value__isnull=True)
                    )
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.target} {self.field_name}"

    def clean(self) -> None:
        super().clean()
        if self.change_type == ChangeTypeChoices.CREATE:
            self._clean_create()
        elif self.change_type == ChangeTypeChoices.UPDATE:
            self._clean_update()

    def _clean_create(self) -> None:
        if not isinstance(self.payload, dict):
            raise ValidationError({"payload": "Create requests require a payload dict."})
        forbidden = (self.field_name, self.object_id, self.old_value, self.new_value)
        if any(value not in (None, "") for value in forbidden):
            msg = "Create requests must not set field_name/object_id/old_value/new_value."
            raise ValidationError(msg)

    def _clean_update(self) -> None:
        if self.payload is not None or self.payload_hash is not None:
            raise ValidationError({"payload": "Update requests must not carry a payload."})
        if not self.field_name:
            raise ValidationError({"field_name": "Update requests require a field_name."})
