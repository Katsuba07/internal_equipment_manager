#!/usr/bin/env python
"""Command-line utility for administrative tasks."""
import os
import sys


def _force_utf8_console():
    """
    Force the console to UTF-8.

    Windows Command Prompt defaults to the cp1252 code page, which cannot
    encode many characters and aborts commands mid-run with UnicodeEncodeError.
    Setting it here makes every management command safe.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main():
    """Run administrative tasks."""
    _force_utf8_console()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Could not import Django. Activate the virtual environment (.venv) "
            "and run: pip install -r requirements.txt"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
