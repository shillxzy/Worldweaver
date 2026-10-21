"""Private image uploads (portraits, avatars, book covers).

Images are validated by content (not by file name), size-limited, downscaled and re-encoded,
which strips metadata and any trailing payload. Files get random names and are served only
through authenticated API views — never from a public media URL.
"""
import uuid
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.http import HttpResponse
from PIL import Image, UnidentifiedImageError
from rest_framework.exceptions import NotFound, ValidationError

ALLOWED_IMAGE_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
MAX_PIXELS = 40_000_000


def process_image(upload, field, max_side=1024):
    """Validate an uploaded image and return (bytes, extension)."""
    if upload is None:
        raise ValidationError({field: "Файл не передано."})
    if upload.size > settings.WW_MAX_PORTRAIT_BYTES:
        raise ValidationError({field: f"Файл завеликий (максимум {settings.WW_MAX_PORTRAIT_BYTES // 1024 // 1024} МБ)."})
    try:
        with Image.open(upload) as probe:
            probe.verify()
        upload.seek(0)
        with Image.open(upload) as img:
            fmt = img.format
            if fmt not in ALLOWED_IMAGE_FORMATS:
                raise ValidationError({field: "Дозволені формати: JPEG, PNG, WEBP."})
            if img.width * img.height > MAX_PIXELS:
                raise ValidationError({field: "Зображення має завелику роздільну здатність."})
            img.thumbnail((max_side, max_side))
            if fmt == "JPEG" and img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            buffer = BytesIO()
            img.save(buffer, format=fmt)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError({field: "Файл не є коректним зображенням."}) from exc
    return buffer.getvalue(), ALLOWED_IMAGE_FORMATS[fmt]


def replace_image(instance, field_name, upload, max_side=1024, extra_update_fields=()):
    """Store a processed upload in ``instance.<field_name>`` and delete the previous file."""
    content, ext = process_image(upload, field_name, max_side)
    field = getattr(instance, field_name)
    old = field.name if field else None
    field.save(f"{uuid.uuid4().hex}.{ext}", ContentFile(content), save=False)
    instance.save(update_fields=[field_name, *extra_update_fields])
    if old:
        field.storage.delete(old)


def clear_image(instance, field_name, extra_update_fields=()):
    field = getattr(instance, field_name)
    if field:
        field.delete(save=False)
    setattr(instance, field_name, None)
    instance.save(update_fields=[field_name, *extra_update_fields])


def image_response(field, missing_message):
    """Return the stored image. Files are small (downscaled on upload), so they are read fully
    instead of streamed — this also avoids holding the file open (Windows file locks)."""
    if not field:
        raise NotFound(missing_message)
    ext = field.name.rsplit(".", 1)[-1].lower()
    with field.open("rb") as fh:
        response = HttpResponse(fh.read(), content_type="image/" + {"jpg": "jpeg"}.get(ext, ext))
    response["Cache-Control"] = "private, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    return response
