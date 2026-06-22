from typing import TYPE_CHECKING, Any

from django_approve.registry import register

if TYPE_CHECKING:
    from django_approve.admin import ApprovalAdminMixin

__all__ = ["ApprovalAdminMixin", "register"]


def __getattr__(name: str) -> Any:
    """Lazily expose ApprovalAdminMixin from the package root."""
    if name == "ApprovalAdminMixin":
        from django_approve.admin import ApprovalAdminMixin  # noqa: PLC0415

        return ApprovalAdminMixin

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
