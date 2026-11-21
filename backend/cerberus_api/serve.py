"""Lanzador de la API con host y puerto de `Settings` (docs/PLAN_MVP.md §23).

    uv run python -m cerberus_api.serve --reload

Lee `CERBERUS_API_HOST` y `CERBERUS_API_PORT` (por defecto 127.0.0.1:8000).
"""

import argparse
from collections.abc import Sequence

import uvicorn

from cerberus_api.config import get_settings


def main(argv: Sequence[str] | None = None) -> None:
    """Arranca uvicorn; con `--reload` vigila solo `backend/`."""
    parser = argparse.ArgumentParser(description="Arranca la API de Cerberus.")
    parser.add_argument("--reload", action="store_true", help="recarga al cambiar el código de backend/")
    args = parser.parse_args(argv)

    settings = get_settings()
    uvicorn.run(
        "cerberus_api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=args.reload,
        reload_dirs=["backend"] if args.reload else None,
    )


if __name__ == "__main__":
    main()
