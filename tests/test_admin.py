import pytest
from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, override_settings
from mixer.backend.django import mixer

from django_approve.admin.change_request import ChangeRequestFieldAdmin
from django_approve.admin.mixins import ApprovalAdminMixin
from django_approve.cons import ApprovalStatusChoices, ChangeTypeChoices
from django_approve.models import ApprovalConfig, ChangeRequestField
from django_approve.registry import ApprovalRegistry
from django_approve.serializers import compute_payload_hash, serialize_object
from tests.models import Sample, Widget

S = ApprovalStatusChoices

OLD_AMOUNT = 10
NEW_AMOUNT = 20


class SampleAdmin(ApprovalAdminMixin, admin.ModelAdmin):
    pass


class _FakeForm:
    def __init__(self, changed_data, cleaned_data):
        self.changed_data = changed_data
        self.cleaned_data = cleaned_data


def _request_by(requester):
    sample = mixer.blend(Sample)
    return mixer.blend(
        ChangeRequestField,
        content_type=ContentType.objects.get_for_model(Sample),
        object_id=sample.pk,
        field_name="amount",
        change_type=ChangeTypeChoices.UPDATE,
        old_value=1,
        new_value=2,
        status=ApprovalStatusChoices.PENDING,
        requested_by=requester,
    )


def _status_choices(change_admin, request, change_request):
    form_class = change_admin.get_form(request, obj=change_request)
    form = form_class(instance=change_request)
    return {value for value, _ in form.fields["status"].choices}


def _request_as(user):
    request = RequestFactory().get("/")
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


@pytest.mark.django_db
class TestChangeRequestFieldAdminStatusChoices:
    @pytest.fixture
    def change_admin(self):
        return ChangeRequestFieldAdmin(ChangeRequestField, AdminSite())

    @pytest.fixture
    def maker(self):
        return mixer.blend("auth.User")

    def test_author_sees_only_pending_and_cancelled(self, change_admin, maker):
        change_request = _request_by(maker)

        choices = _status_choices(change_admin, _request_as(maker), change_request)

        assert choices == {S.PENDING, S.CANCELLED}

    def test_reviewer_sees_pending_approved_rejected(self, change_admin, maker):
        change_request = _request_by(maker)
        checker = mixer.blend("auth.User")

        choices = _status_choices(change_admin, _request_as(checker), change_request)

        assert choices == {S.PENDING, S.APPROVED, S.REJECTED}

    def test_deleted_is_never_offered(self, change_admin, maker):
        change_request = _request_by(maker)
        checker = mixer.blend("auth.User")

        author_choices = _status_choices(change_admin, _request_as(maker), change_request)
        reviewer_choices = _status_choices(change_admin, _request_as(checker), change_request)

        assert S.DELETED not in author_choices
        assert S.DELETED not in reviewer_choices

    @override_settings(APPROVE_REQUIRE_DIFFERENT_USER=False)
    def test_author_can_self_approve_when_four_eyes_disabled(self, change_admin, maker):
        change_request = _request_by(maker)

        choices = _status_choices(change_admin, _request_as(maker), change_request)
        assert choices == {S.PENDING, S.APPROVED, S.CANCELLED}

    def test_terminal_status_is_not_reopenable_by_reviewer(self, change_admin, maker):
        change_request = _request_by(maker)
        change_request.status = S.REJECTED
        change_request.save(update_fields=["status"])
        checker = mixer.blend("auth.User")

        choices = _status_choices(change_admin, _request_as(checker), change_request)

        assert choices == {S.REJECTED}


@pytest.mark.django_db
class TestApprovalAdminMixinSaveModel:
    @pytest.fixture
    def sample_admin(self):
        return SampleAdmin(Sample, AdminSite())

    @pytest.fixture
    def tracked_amount(self, monkeypatch):
        reg = ApprovalRegistry()
        reg.register(Sample)
        monkeypatch.setattr("django_approve.fields.registry", reg)
        return mixer.blend(
            ApprovalConfig,
            content_type=ContentType.objects.get_for_model(Sample),
            tracked_fields=["amount"],
            is_enabled=True,
        )

    @pytest.fixture
    def maker(self):
        return mixer.blend("auth.User")

    def test_save_model_creates_pending_request_and_reverts_tracked_field(self, sample_admin, tracked_amount, maker):
        sample = mixer.blend(Sample, amount=OLD_AMOUNT)
        form = _FakeForm(changed_data=["amount"], cleaned_data={"amount": NEW_AMOUNT})
        sample.amount = NEW_AMOUNT

        sample_admin.save_model(_request_as(maker), sample, form, change=True)

        change_request = ChangeRequestField.objects.get(
            content_type=ContentType.objects.get_for_model(Sample), object_id=sample.pk
        )
        assert change_request.field_name == "amount"
        assert change_request.old_value == OLD_AMOUNT
        assert change_request.new_value == NEW_AMOUNT
        assert change_request.status == S.PENDING
        assert change_request.requested_by == maker
        assert sample.amount == OLD_AMOUNT

    def test_save_model_skips_untracked_field(self, sample_admin, maker):
        sample = mixer.blend(Sample, name="old")
        form = _FakeForm(changed_data=["name"], cleaned_data={"name": "new"})
        sample.name = "new"

        sample_admin.save_model(_request_as(maker), sample, form, change=True)

        assert not ChangeRequestField.objects.exists()
        sample.refresh_from_db()
        assert sample.name == "new"

    def test_save_model_does_not_duplicate_when_field_already_pending(self, sample_admin, tracked_amount, maker):
        sample = mixer.blend(Sample, amount=OLD_AMOUNT)
        winner = mixer.blend("auth.User")
        mixer.blend(
            ChangeRequestField,
            content_type=ContentType.objects.get_for_model(Sample),
            object_id=sample.pk,
            field_name="amount",
            change_type=ChangeTypeChoices.UPDATE,
            old_value=OLD_AMOUNT,
            new_value=NEW_AMOUNT,
            status=S.PENDING,
            requested_by=winner,
        )
        form = _FakeForm(changed_data=["amount"], cleaned_data={"amount": 99})
        sample.amount = 99
        request = _request_as(maker)

        sample_admin.save_model(request, sample, form, change=True)

        requests = ChangeRequestField.objects.filter(
            content_type=ContentType.objects.get_for_model(Sample), object_id=sample.pk
        )
        assert requests.count() == 1
        assert requests.get().requested_by == winner
        assert sample.amount == OLD_AMOUNT
        warnings = [m.message for m in request._messages]
        assert any("amount" in message for message in warnings)

    def test_get_readonly_fields_locks_pending_field(self, sample_admin, maker):
        sample = mixer.blend(Sample, amount=OLD_AMOUNT)
        mixer.blend(
            ChangeRequestField,
            content_type=ContentType.objects.get_for_model(Sample),
            object_id=sample.pk,
            field_name="amount",
            change_type=ChangeTypeChoices.UPDATE,
            old_value=OLD_AMOUNT,
            new_value=NEW_AMOUNT,
            status=S.PENDING,
            requested_by=maker,
        )

        readonly = sample_admin.get_readonly_fields(_request_as(maker), sample)

        assert "amount" in readonly


@pytest.mark.django_db
class TestChangeRequestFieldAdminQueryEfficiency:
    @pytest.fixture
    def change_admin(self):
        return ChangeRequestFieldAdmin(ChangeRequestField, AdminSite())

    def test_changelist_queryset_does_not_n_plus_one_on_target(self, change_admin, django_assert_max_num_queries):
        maker = mixer.blend("auth.User")
        for _ in range(5):
            _request_by(maker)

        request = _request_as(maker)
        with django_assert_max_num_queries(4):
            for change_request in change_admin.get_queryset(request):
                _ = change_request.target


class WidgetAdmin(ApprovalAdminMixin, admin.ModelAdmin):
    pass


@pytest.mark.django_db
class TestApprovalAdminMixinCreate:
    @pytest.fixture
    def widget_admin(self):
        return WidgetAdmin(Widget, AdminSite())

    @pytest.fixture
    def tracked_widget(self, monkeypatch):
        reg = ApprovalRegistry()
        reg.register(Widget)
        monkeypatch.setattr("django_approve.fields.registry", reg)
        monkeypatch.setattr("django_approve.admin.mixins.registry", reg)
        return mixer.blend(
            ApprovalConfig,
            content_type=ContentType.objects.get_for_model(Widget),
            tracked_fields=[],
            is_enabled=True,
        )

    @pytest.fixture
    def maker(self):
        return mixer.blend("auth.User")

    def _unsaved_widget(self):
        return Widget(name="w", quantity=3, owner=None, price=None, code=None)

    @override_settings(APPROVE_REQUIRE_CREATE_APPROVAL=True)
    def test_add_is_diverted_to_pending_create(self, widget_admin, tracked_widget, maker):
        obj = self._unsaved_widget()
        form = _FakeForm(changed_data=[], cleaned_data={})
        request = _request_as(maker)

        widget_admin.save_model(request, obj, form, change=False)

        assert obj.pk is None
        assert not Widget.objects.exists()
        cr = ChangeRequestField.objects.get(change_type=ChangeTypeChoices.CREATE)
        assert cr.payload["name"] == "w"
        assert cr.payload["quantity"] == 3
        assert cr.payload_hash == compute_payload_hash(cr.payload)
        assert cr.requested_by == maker
        assert request._approval_diverted is True

    @override_settings(APPROVE_REQUIRE_CREATE_APPROVAL=False)
    def test_add_writes_object_when_flag_off(self, widget_admin, tracked_widget, maker):
        obj = self._unsaved_widget()
        form = _FakeForm(changed_data=[], cleaned_data={})

        widget_admin.save_model(_request_as(maker), obj, form, change=False)

        assert obj.pk is not None
        assert Widget.objects.count() == 1
        assert not ChangeRequestField.objects.filter(change_type=ChangeTypeChoices.CREATE).exists()

    @override_settings(APPROVE_REQUIRE_CREATE_APPROVAL=True)
    def test_add_writes_object_when_model_untracked(self, widget_admin, maker):
        obj = self._unsaved_widget()
        form = _FakeForm(changed_data=[], cleaned_data={})

        widget_admin.save_model(_request_as(maker), obj, form, change=False)

        assert Widget.objects.count() == 1
        assert not ChangeRequestField.objects.filter(change_type=ChangeTypeChoices.CREATE).exists()

    @override_settings(APPROVE_REQUIRE_CREATE_APPROVAL=True)
    def test_duplicate_create_submit_warns_and_does_not_double(self, widget_admin, tracked_widget, maker):
        payload = serialize_object(Widget, self._unsaved_widget())
        mixer.blend(
            ChangeRequestField,
            content_type=ContentType.objects.get_for_model(Widget),
            object_id=None,
            field_name="",
            change_type=ChangeTypeChoices.CREATE,
            old_value=None,
            new_value=None,
            payload=payload,
            payload_hash=compute_payload_hash(payload),
            status=S.PENDING,
            requested_by=mixer.blend("auth.User"),
        )
        request = _request_as(maker)

        widget_admin.save_model(request, self._unsaved_widget(), form=_FakeForm([], {}), change=False)

        assert ChangeRequestField.objects.filter(change_type=ChangeTypeChoices.CREATE).count() == 1
        warnings = [m.message for m in request._messages]
        assert any("approval" in str(message).lower() for message in warnings)

    @override_settings(APPROVE_REQUIRE_CREATE_APPROVAL=True)
    def test_response_add_redirects_to_changelist_when_diverted(self, widget_admin, tracked_widget, maker):
        request = _request_as(maker)
        request._approval_diverted = True
        obj = self._unsaved_widget()

        response = widget_admin.response_add(request, obj)

        assert response.status_code == 302
        assert "widget" in response.url


def _pending_create(model, payload, requested_by):
    return mixer.blend(
        ChangeRequestField,
        content_type=ContentType.objects.get_for_model(model),
        object_id=None,
        field_name="",
        change_type=ChangeTypeChoices.CREATE,
        old_value=None,
        new_value=None,
        payload=payload,
        payload_hash=compute_payload_hash(payload),
        status=S.PENDING,
        requested_by=requested_by,
    )


@pytest.mark.django_db
class TestChangeRequestFieldAdminCreate:
    @pytest.fixture
    def change_admin(self):
        return ChangeRequestFieldAdmin(ChangeRequestField, AdminSite())

    def test_approving_create_writes_object(self, change_admin):
        maker = mixer.blend("auth.User")
        checker = mixer.blend("auth.User")
        cr = _pending_create(Widget, {"name": "w", "quantity": 3}, requested_by=maker)
        cr.status = S.APPROVED
        form = _FakeForm(changed_data=["status"], cleaned_data={})

        change_admin.save_model(_request_as(checker), cr, form, change=True)

        cr.refresh_from_db()
        assert cr.status == S.APPROVED
        assert Widget.objects.filter(name="w", quantity=3).exists()
        assert cr.object_id is not None

    def test_self_approval_of_create_is_blocked(self, change_admin):
        maker = mixer.blend("auth.User")
        cr = _pending_create(Widget, {"name": "w", "quantity": 3}, requested_by=maker)
        cr.status = S.APPROVED
        form = _FakeForm(changed_data=["status"], cleaned_data={})
        request = _request_as(maker)

        change_admin.save_model(request, cr, form, change=True)

        assert not Widget.objects.exists()
        cr.refresh_from_db()
        assert cr.status == S.PENDING

    def test_summary_renders_create_and_update(self, change_admin):
        maker = mixer.blend("auth.User")
        create_cr = _pending_create(Widget, {"name": "w", "quantity": 3}, requested_by=maker)
        update_cr = _request_by(maker)

        assert "Widget" in change_admin.summary(create_cr)
        assert "amount" in change_admin.summary(update_cr)

    def test_payload_fields_are_readonly(self, change_admin):
        assert "payload" in change_admin.readonly_fields
        assert "payload_hash" in change_admin.readonly_fields

    def test_admin_loads_payload_stylesheet(self, change_admin):
        assert "django_approve/change_request.css" in change_admin.Media.css["all"]

    def test_payload_context_for_create(self, change_admin):
        maker = mixer.blend("auth.User")
        cr = _pending_create(Widget, {"name": "w", "quantity": 3}, requested_by=maker)

        ctx = change_admin._payload_context(cr)

        assert ("name", "w") in ctx["payload_items"]
        assert ctx["payload_model"] == ContentType.objects.get_for_model(Widget).name

    def test_payload_context_empty_for_update(self, change_admin):
        maker = mixer.blend("auth.User")
        update_cr = _request_by(maker)

        assert change_admin._payload_context(update_cr) == {}

    def test_update_fieldsets_use_field_columns(self, change_admin):
        maker = mixer.blend("auth.User")
        update_cr = _request_by(maker)

        fieldsets = change_admin.get_fieldsets(_request_as(maker), update_cr)
        all_fields = [name for _, opts in fieldsets for name in opts["fields"]]

        assert "old_value" in all_fields
        assert "payload" not in all_fields
