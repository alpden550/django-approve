import pytest
from django.db import models

from django_approve.exceptions import AlreadyRegisteredError
from django_approve.registry import ApprovalRegistry, register


class Alpha(models.Model):
    class Meta:
        abstract = True


class Beta(models.Model):
    class Meta:
        abstract = True


def test_register_defaults_to_all_fields():
    reg = ApprovalRegistry()

    reg.register(Alpha)

    assert reg.is_registered(Alpha)
    assert reg.get_whitelist(Alpha) == "__all__"


def test_register_stores_explicit_whitelist():
    reg = ApprovalRegistry()

    reg.register(Alpha, fields=["a", "b"])

    assert reg.get_whitelist(Alpha) == ["a", "b"]


def test_register_returns_the_model():
    reg = ApprovalRegistry()

    assert reg.register(Alpha) is Alpha


def test_duplicate_registration_raises():
    reg = ApprovalRegistry()
    reg.register(Alpha)

    with pytest.raises(AlreadyRegisteredError, match="Alpha"):
        reg.register(Alpha)


def test_get_models_lists_registered_in_order():
    reg = ApprovalRegistry()

    reg.register(Alpha)
    reg.register(Beta)

    assert reg.get_models() == [Alpha, Beta]


@pytest.fixture
def fresh_registry(monkeypatch):
    reg = ApprovalRegistry()
    monkeypatch.setattr("django_approve.registry.registry", reg)
    return reg


def test_register_as_bare_decorator(fresh_registry):
    @register
    class Gamma(models.Model):
        class Meta:
            abstract = True

    assert fresh_registry.is_registered(Gamma)
    assert fresh_registry.get_whitelist(Gamma) == "__all__"


def test_register_as_decorator_with_fields(fresh_registry):
    @register(fields=["x"])
    class Delta(models.Model):
        class Meta:
            abstract = True

    assert fresh_registry.get_whitelist(Delta) == ["x"]


def test_register_direct_call(fresh_registry):
    register(Alpha, fields=["y"])

    assert fresh_registry.get_whitelist(Alpha) == ["y"]
