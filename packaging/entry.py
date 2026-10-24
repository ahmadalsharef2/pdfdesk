"""PyInstaller entry point (pdfdesk.cli uses relative imports, so it can't be the script itself)."""
from pdfdesk.cli import main

raise SystemExit(main())
