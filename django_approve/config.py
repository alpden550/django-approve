from django.conf import settings

PREFIX = "APPROVE_"


def _get[T](name: str, default: T) -> T:
    return getattr(settings, f"{PREFIX}{name}", default)


class AppSettings:
    @property
    def AUTO_CREATE_GROUP(self) -> bool:  # noqa: N802
        return _get("AUTO_CREATE_GROUP", default=True)

    @property
    def GROUP_NAME(self) -> str:  # noqa: N802
        return _get("GROUP_NAME", default="Approvals")


conf = AppSettings()
