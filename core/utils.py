"""Small helpers shared across apps."""

from django.db import IntegrityError, transaction
from django.utils import timezone


def next_sequence_code(model, prefix: str, field: str = "code", width: int = 4) -> str:
    """
    Build a per-year running ticket number, for example INC-2026-0001.

    The counter restarts each year so numbers stay short and readable when
    cross-referencing paper records.
    """
    stem = f"{prefix}-{timezone.localdate().year}-"
    last = (
        model.objects.filter(**{f"{field}__startswith": stem})
        .order_by(f"-{field}")
        .values_list(field, flat=True)
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(str(last).rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            seq = model.objects.filter(**{f"{field}__startswith": stem}).count() + 1
    return f"{stem}{seq:0{width}d}"


def save_with_generated_code(instance, prefix: str, field: str = "code", attempts: int = 5):
    """
    Save a record, generating its number when missing.

    Two people creating a ticket at the same moment can generate the same
    number; the unique constraint rejects the clash and this loop retries
    with the next one.
    """
    for attempt in range(attempts):
        if not getattr(instance, field, None):
            setattr(instance, field, next_sequence_code(type(instance), prefix, field))
        try:
            with transaction.atomic():
                instance.save()
            return instance
        except IntegrityError:
            if attempt == attempts - 1:
                raise
            setattr(instance, field, "")
    return instance
