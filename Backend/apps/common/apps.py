import re

from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _sqlite_unicode_like(pattern, value, escape=None):
    """Case-insensitive LIKE for SQLite that also folds non-ASCII (Cyrillic) letters.

    SQLite's built-in LIKE only folds ASCII, so «ейра» would not match «Ейра». PostgreSQL
    (the target database) already handles this via UPPER().
    """
    if pattern is None or value is None:
        return None
    regex, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if escape and ch == escape and i + 1 < len(pattern):
            regex.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        regex.append(".*" if ch == "%" else "." if ch == "_" else re.escape(ch))
        i += 1
    return re.fullmatch("".join(regex), str(value), re.IGNORECASE | re.DOTALL) is not None


def _install(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        connection.connection.create_function("LIKE", 2, _sqlite_unicode_like, deterministic=True)
        connection.connection.create_function("LIKE", 3, _sqlite_unicode_like, deterministic=True)


class CommonConfig(AppConfig):
    name = "apps.common"

    def ready(self):
        connection_created.connect(_install, dispatch_uid="ww_sqlite_unicode_like")
