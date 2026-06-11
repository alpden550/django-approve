from collections.abc import Callable
from typing import overload

from django.db import models

from django_approve.exceptions import AlreadyRegisteredError


class ApprovalRegistry:
    """Holds models opted into approval and their candidate-field whitelist.

    The whitelist bounds that field an approver may later mark as tracked; it
    is the developer's opt-in. "__all__" means every eligible field.
    """

    def __init__(self) -> None:
        self._whitelists: dict[type[models.Model], str | list[str]] = {}

    def register(self, model: type[models.Model], fields: str | list[str] = "__all__") -> type[models.Model]:
        if model in self._whitelists:
            raise AlreadyRegisteredError(model.__name__)

        self._whitelists[model] = fields
        return model

    def is_registered(self, model: type[models.Model]) -> bool:
        return model in self._whitelists

    def get_models(self) -> list[type[models.Model]]:
        return list(self._whitelists)

    def get_whitelist(self, model: type[models.Model]) -> str | list[str]:
        return self._whitelists[model]


registry = ApprovalRegistry()


@overload
def register[M: models.Model](model: type[M], *, fields: str | list[str] = ...) -> type[M]: ...


@overload
def register[M: models.Model](model: None = ..., *, fields: str | list[str] = ...) -> Callable[[type[M]], type[M]]: ...


def register(
    model: type[models.Model] | None = None,
    *,
    fields: str | list[str] = "__all__",
) -> type[models.Model] | Callable[[type[models.Model]], type[models.Model]]:
    """Register a model for the approval workflow.

    Works as a direct call register(MyModel, fields=[...]) or as a class
    decorator @register(fields=[...]).

    Args:
        model: The model class, or None when used as a decorator factory.
        fields: Whitelist of field names the approver may track, or "__all__".

    Returns:
        The model class, or a decorator when the model is None.
    """
    if model is None:

        def decorator(cls: type[models.Model]) -> type[models.Model]:
            return registry.register(cls, fields=fields)

        return decorator

    return registry.register(model, fields=fields)
