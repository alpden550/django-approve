from django.db import models


class ChangeTypeChoices(models.TextChoices):
    UPDATE = "update", "update"
    CREATE = "create", "create"
    DELETE = "delete", "delete"


class ApprovalStatusChoices(models.TextChoices):
    PENDING = "pending", "pending"
    APPROVED = "approved", "approved"
    REJECTED = "rejected", "rejected"
    CANCELLED = "cancelled", "cancelled"
    DELETED = "deleted", "deleted"
