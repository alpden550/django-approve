from django.contrib import admin
from django.contrib.contenttypes.models import ContentType

from django_approve.models import ChangeRequestField


class TargetModelFilter(admin.SimpleListFilter):
    title = "target model"
    parameter_name = "target_model"

    # pyrefly: ignore [bad-override]
    def lookups(self, request, model_admin):
        ct_ids = ChangeRequestField.objects.values_list("content_type", flat=True).distinct()
        return [(ct.pk, ct.name) for ct in ContentType.objects.filter(pk__in=ct_ids)]

    def queryset(self, request, queryset):
        value = self.value()
        return queryset.filter(content_type_id=value) if value else queryset
