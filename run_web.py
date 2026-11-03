"""
ChronosMatch Web Trading Terminal Runner Entry Point.
Runs the institutional dark trading dashboard at http://127.0.0.1:8000/
"""
import sys
import os

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_app.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable?"
        ) from exc
    print("=" * 65)
    print("  CHRONOSMATCH INSTITUTIONAL WEB TRADING TERMINAL")
    print("=" * 65)
    print("  Engine Mode:     Native Cython LOB (<QdIBQ 29-byte zero-copy)")
    print("  Localhost URL:   http://127.0.0.1:8000/")
    print("  Health API:      http://127.0.0.1:8000/api/health/")
    print("  Market Feed API: http://127.0.0.1:8000/api/market-data/")
    print("=" * 65)
    print("Starting development server at http://127.0.0.1:8000/ ...")
    print("Press Ctrl+C to stop.\n")
    args = [sys.argv[0], "runserver", "127.0.0.1:8000", "--noreload"]
    execute_from_command_line(args)
