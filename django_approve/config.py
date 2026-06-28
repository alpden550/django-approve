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

    @property
    def REQUIRE_DIFFERENT_USER(self) -> bool:  # noqa: N802
        return _get("REQUIRE_DIFFERENT_USER", default=True)

    @property
    def REQUIRE_CREATE_APPROVAL(self) -> bool:  # noqa: N802
        return _get("REQUIRE_CREATE_APPROVAL", default=False)


conf = AppSettings()
