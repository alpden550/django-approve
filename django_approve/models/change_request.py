from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
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
    status = models.CharField(
        max_length=10,
        choices=ApprovalStatusChoices.choices,
        default=ApprovalStatusChoices.PENDING,
    )
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="requested_change_fields")
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="approved_change_fields")

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
        ]

    def __str__(self) -> str:
        return f"{self.target} {self.field_name}"
