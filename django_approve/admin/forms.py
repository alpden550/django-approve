from typing import Any

from django import forms
from django.db.models import Model

from django_approve.fields import get_approvable_fields, prune_tracked_fields
from django_approve.models import ApprovalConfig


class ApprovalConfigForm(forms.ModelForm):
    tracked_fields = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = ApprovalConfig
        fields = ("content_type", "is_enabled", "tracked_fields")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        tracked_fields = self.fields["tracked_fields"]

        model = self._resolve_model()
        if model is None:
            # pyrefly: ignore [missing-attribute]
            tracked_fields.choices = []
            return

        candidates = get_approvable_fields(model=model)
        # pyrefly: ignore [missing-attribute]
        tracked_fields.choices = [(name, name) for name in candidates]
        if self.instance and self.instance.pk:
            valid = set(candidates)
            self.initial["tracked_fields"] = [name for name in self.instance.tracked_fields if name in valid]

    def _resolve_model(self) -> type[Model] | None:
        content_type = None

        if self.instance and self.instance.pk:
            content_type = self.instance.content_type
        elif "content_type" in self.data:
            from django.contrib.contenttypes.models import ContentType  # noqa: PLC0415

            try:
                content_type = ContentType.objects.get(pk=self.data["content_type"])
            except (ContentType.DoesNotExist, ValueError):
                return None

        return content_type.model_class() if content_type else None

    def clean_tracked_fields(self) -> list[str]:
        selected = self.cleaned_data.get("tracked_fields", [])

        model = self._resolve_model()
        if model is None:
            return []

        return prune_tracked_fields(model=model, tracked_fields=selected)
