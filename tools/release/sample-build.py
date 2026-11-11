#!/usr/bin/env python3
"""Construye el artefacto público D3c, determinista y limitado a cuatro NIfTI.

No publica ni descarga. El manifest base fija las huellas heredadas de Git LFS;
una carpeta con otros bytes no puede convertirse accidentalmente en la demo.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import stat
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import BinaryIO

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from cerberus_api.sample import (  # noqa: E402
    SAMPLE_VERSION,
    SampleError,
    SampleFile,
    _https_url,
    _study_directory,
    file_digest,
    load_manifest,
    secure_directory,
    verify_file,
)


def build_sample(data: Path, output: Path, manifest_path: Path, *, url: str | None = None) -> dict[str, object]:
    """Verifica fuentes fijadas y escribe TAR sin timestamps, UIDs, rutas personales ni otros datos."""
    manifest = load_manifest(manifest_path)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if url is not None:
        _https_url(url)
        raw["archive"]["url"] = url
    if output.exists() or output.is_symlink():
        raise SampleError("El artefacto de salida ya existe; elija un archivo nuevo.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with secure_directory(data, create=False) as data_fd:
        # Abrir por directorios protegidos también impide usar fuentes externas mediante symlinks.
        with _study_directory(data_fd, create=False) as study_fd:
            if study_fd is None:
                raise SampleError("No existe la muestra pública 001/t0 en el directorio de entrada.")
            sources: list[tuple[SampleFile, BinaryIO]] = []
            try:
                for entry in manifest.files:
                    fd = os.open(
                        entry.path.rsplit("/", 1)[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=study_fd
                    )
                    source = os.fdopen(fd, "rb")
                    sources.append((entry, source))
                    if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                        raise SampleError("Las fuentes deben ser archivos regulares.")
                    verify_file(source, entry)
                    source.seek(0)
                with tempfile.NamedTemporaryFile(prefix=".sample-build-", dir=output.parent, delete=False) as temporary:
                    temporary_path = Path(temporary.name)
                    try:
                        with tarfile.open(fileobj=temporary, mode="w", format=tarfile.USTAR_FORMAT) as bundle:
                            for entry, source in sources:
                                info = tarfile.TarInfo(entry.path)
                                info.size = entry.size
                                info.mode = 0o644
                                info.mtime = 0
                                info.uid = info.gid = 0
                                info.uname = info.gname = ""
                                bundle.addfile(info, source)
                        temporary.flush()
                        os.fsync(temporary.fileno())
                        temporary.seek(0)
                        size, digest = file_digest(temporary.file)
                        raw["archive"]["size"] = size
                        raw["archive"]["sha256"] = digest
                        raw["version"] = SAMPLE_VERSION
                        raw["files"] = [dataclasses.asdict(entry) for entry in manifest.files]
                        os.link(temporary_path, output)
                    finally:
                        temporary_path.unlink(missing_ok=True)
            finally:
                for _, source in sources:
                    source.close()
    # El artefacto está completo; reemplazar el manifest de desarrollo es una acción explícita de build.
    manifest_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return raw


def main(argv: list[str] | None = None) -> int:
    """CLI de preparación de release, sin publicación implícita."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("sample-manifest.json"))
    parser.add_argument("--url", help="URL HTTPS final del artefacto; no se consulta.")
    args = parser.parse_args(argv)
    try:
        raw = build_sample(args.data, args.output, args.manifest, url=args.url)
    except (SampleError, OSError):
        print("No se pudo construir la muestra: revise bytes públicos, rutas y permisos.", file=sys.stderr)
        return 1
    archive = raw["archive"]
    print(json.dumps({"version": SAMPLE_VERSION, "archive": archive}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
