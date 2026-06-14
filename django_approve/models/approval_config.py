from django.db import models


class ApprovalConfig(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    is_enabled = models.BooleanField(default=True)
    content_type = models.OneToOneField("contenttypes.ContentType", on_delete=models.CASCADE)
    tracked_fields = models.JSONField(default=list)

    class Meta:
        verbose_name = "approval configuration"
        verbose_name_plural = "approval configurations"

    def __str__(self) -> str:
        return f"{self.content_type} approval configuration"
