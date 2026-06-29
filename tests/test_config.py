from django.test import override_settings

from django_approve.config import conf


class TestRequireCreateApproval:
    def test_defaults_to_false(self):
        assert conf.REQUIRE_CREATE_APPROVAL is False

    @override_settings(APPROVE_REQUIRE_CREATE_APPROVAL=True)
    def test_reads_override(self):
        assert conf.REQUIRE_CREATE_APPROVAL is True
