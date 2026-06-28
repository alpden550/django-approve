# django-approve-flow

> Moderate edits in the Django admin — a change to a tracked model field isn't
> saved directly, it waits for a second person's approval (four-eyes /
> maker-checker).

[![CI](https://github.com/alpden550/django-approve/actions/workflows/ci.yml/badge.svg)](https://github.com/alpden550/django-approve/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/django-approve-flow.svg)](https://pypi.org/project/django-approve-flow/)
[![Python versions](https://img.shields.io/pypi/pyversions/django-approve-flow.svg)](https://pypi.org/project/django-approve-flow/)
[![Django](https://img.shields.io/badge/django-5%2B-092e20.svg)](https://www.djangoproject.com/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Granularity is per field, not per object.** A single save touching three
tracked fields creates three independent requests, each with its own status and
its own reviewer. There is no batch / "change set" model — grouping is purely a
UX artifact (one "Submitted for approval: a, b, c" message).

## How it works

1. **Register** a model to make its fields *eligible* for approval.
2. **Pick** which eligible fields are actually *tracked*, in the admin.
3. **Add the admin mixin.** Editing a tracked field now creates an approval
   request instead of writing the value.
4. A **reviewer** approves or rejects each request — per field, independently.

See [Screenshots](#screenshots) for what this looks like in the admin.

## Installation

```bash
pip install django-approve-flow
```

```python
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django_approve",
]
```

Run `migrate`. This creates the `ApprovalConfig` / `ChangeRequestField` tables,
syncs an `ApprovalConfig` row per registered model, and creates the `Approvals`
group with `view` / `change` permissions on both models.

Optionally, add the middleware to show reviewers an *"N change request(s)
awaiting review"* banner on the admin index:

```python
MIDDLEWARE = [
    "django_approve.middlewares.PendingApprovalsNoticeMiddleware",
]
```

It only fires on `GET /admin/`, for active users in the `Approvals` group, and
only when at least one `pending` request exists.

## Usage

### 1. Register a model

```python
from django_approve.registry import register

@register
class Employee(models.Model):
    name = models.CharField(max_length=255)
    salary = models.DecimalField(max_digits=10, decimal_places=2)
    manager = models.ForeignKey("self", null=True, on_delete=models.SET_NULL)
```

Bare `@register` makes *every* eligible field a candidate. A field is eligible
when it is concrete and editable, and is **not**:

- the primary key,
- non-editable,
- an `auto_now` / `auto_now_add` timestamp,
- a `FileField` / `ImageField` (files and M2M are out of scope for v1).

To narrow the set further, pass `fields` — it is intersected with the eligible
candidates:

```python
@register(fields=["salary", "manager"])
class Employee(models.Model):
    ...
```

Registering only makes a field *eligible* — nothing is tracked yet.

### 2. Pick tracked fields in the admin

Each registered model gets an `ApprovalConfig` row (synced automatically on
`migrate`). In the `ApprovalConfig` admin, check which candidate fields should
actually go through the approval flow — this is `tracked_fields`, a subset of
the candidates. Rows can't be added or deleted by hand; they only come from the
sync.

### 3. Add the admin mixin

```python
from django_approve import ApprovalAdminMixin

@admin.register(Employee)
class EmployeeAdmin(ApprovalAdminMixin, admin.ModelAdmin):
    ...
```

From here on, editing a tracked field through this admin no longer writes it
directly:

- The change is diverted into a `ChangeRequestField(status=pending)` with the
  old / new value serialized, and the in-memory value is reverted before
  saving. Untracked fields save normally in the same request.
- While a request is pending, the field is locked (`get_readonly_fields`) and
  the change form shows a "Pending approval" block above it.
- A reviewer (member of the `Approvals` group) sees a banner on the admin
  index, then works through pending rows in the `ChangeRequestField` changelist
  — **Approve** or **Reject**, per field, independently. Both are also
  available as bulk actions: select multiple pending rows and run **Approve
  selected** / **Reject selected** in one go.

> [!WARNING]
> **Locking only happens in the admin.** The whole flow — diverting edits,
> locking fields, showing the pending block — lives in `ApprovalAdminMixin`.
> Calling `.save()` from code (management commands, Celery tasks, shell, DRF)
> bypasses it entirely and writes straight to the row. For the same guarantee
> outside the admin, call `apply_field` yourself or add your own guard — there
> is no model-level enforcement.

## Statuses

| Status      | Meaning                                                                                                       |
| ----------- | ------------------------------------------------------------------------------------------------------------ |
| `pending`   | Awaiting review. Field is locked.                                                                             |
| `approved`  | Applied to the target in the same atomic transaction as the status change. There is no separate "applied" state. |
| `rejected`  | Reviewer declined the change. Reviewer-only verb.                                                             |
| `cancelled` | The author withdrew the request. Author-only verb.                                                           |
| `deleted`   | The target was deleted while the request was pending. Set automatically via `post_delete`; never a manual choice. |

A pending request can only move forward, and the role restricts the available
choices:

- the **author** can `cancel`, but never `approve` / `reject` their own request
  (when `APPROVE_REQUIRE_DIFFERENT_USER` is on);
- a **reviewer** can `approve` / `reject`, but not `cancel` someone else's
  request.

If the target's current value no longer matches the recorded `old_value` at
approval time (someone else changed it in the meantime), approval fails with a
`ConflictError` shown as an admin message — the request stays `pending` and
nothing is applied.

## Settings

All settings are optional; defaults are shown.

```python
APPROVE_AUTO_CREATE_GROUP = True       # create/maintain the Approvals group via post_migrate
APPROVE_GROUP_NAME = "Approvals"       # group name; membership = reviewer
APPROVE_REQUIRE_DIFFERENT_USER = True  # four-eyes: block self-approval (SelfApprovalError)
```

`APPROVE_AUTO_CREATE_GROUP` only controls whether the package manages the
group's permissions on `migrate`; it never adds or removes users.

## Supported field types (v1)

Any concrete, editable field is supported, with two serialization paths:

- **Relations** (`ForeignKey`, `OneToOneField`) — stored as the related
  object's `.pk`, restored via `related_model._base_manager.get(pk=...)`; raises
  `ConflictError` instead of `DoesNotExist` if the target was deleted before
  approval.
- **Everything else** — stored via `field.get_prep_value()` encoded with
  `DjangoJSONEncoder` (covers `str` / `int` / `bool`, `Decimal`, `date` /
  `datetime` / `time` / `timedelta`, `UUID`, `JSONField`, …), restored via
  `field.to_python()`.

Out of scope for v1: `FileField` / `ImageField`, `ManyToManyField`, and (as for
any tracked field) the primary key, non-editable, and `auto_now` /
`auto_now_add` fields.

## Screenshots

<details>
<summary>ApprovalConfig: pick tracked fields per model</summary>

![Approval configurations changelist](docs/screenshots/configurations.png)
![Picking tracked fields for a model](docs/screenshots/tracked_fields.png)

</details>

<details>
<summary>Locked field and pending-approval block on the change form</summary>

![Locked fields with a pending-approval block](docs/screenshots/model.png)

</details>

<details>
<summary>Reviewer: admin-index banner + ChangeRequestField changelist</summary>

![Pending-requests banner on the admin index](docs/screenshots/approvers.png)
![Change request fields changelist](docs/screenshots/requests.png)

</details>

## Development

```bash
poetry install
poetry run pytest
poetry run ruff check .
```
