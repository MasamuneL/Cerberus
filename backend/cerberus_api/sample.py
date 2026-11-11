"""Preparación conservadora de la muestra pública CFB-GBM (D3c).

El manifest de la release fija bytes y SHA-256. Se valida todo antes de publicar
archivos mediante enlaces exclusivos; una interrupción se puede reintentar.
No se utiliza Git LFS ni se ejecutan comandos del host.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import gzip
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from http.client import HTTPMessage
from pathlib import Path
from typing import IO, BinaryIO

from cerberus_api.sequences import validate_patient, validate_sequence, validate_timepoint

CHUNK = 1024 * 1024
SAMPLE_VERSION = "cfb-gbm-001-t0-v1"
SAMPLE_SEQUENCES = ("brain_mask", "flair", "gtv", "t1gd")
LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class SampleError(ValueError):
    """Error recuperable sin reemplazar datos existentes."""


@dataclass(frozen=True)
class SampleFile:
    """Archivo del manifest con ruta validada antes de construir un Path."""

    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class SampleManifest:
    """Contrato de descarga fijado por la release."""

    version: str
    url: str
    size: int
    sha256: str
    files: tuple[SampleFile, ...]


def validate_sample_path(value: object) -> str:
    """Admite únicamente NIfTI de la muestra 001/t0, sin separadores ambiguos."""
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        raise SampleError("Ruta de muestra inválida.")
    parts = value.split("/")
    if len(parts) != 3:
        raise SampleError("La muestra debe pertenecer a 001/t0.")
    patient, timepoint, filename = parts
    try:
        validate_patient(patient)
        validate_timepoint(timepoint)
        match = re.fullmatch(r"1_t0_(.+)\.nii\.gz", filename)
        if patient != "001" or timepoint != "t0" or match is None:
            raise ValueError
        sequence = validate_sequence(match.group(1))
        if sequence not in SAMPLE_SEQUENCES:
            raise ValueError
    except ValueError as exc:
        raise SampleError("Archivo ajeno a la muestra pública 001/t0.") from exc
    return value


def _size(value: object) -> int:
    """Valida tamaños positivos sin aceptar booleanos ni límites desmesurados."""
    if type(value) is not int or not 0 < value <= 4 * 1024**3:
        raise SampleError("Tamaño inválido en el manifest de muestra.")
    return value


def _sha256(value: object) -> str:
    """Valida la representación SHA-256 canónica."""
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise SampleError("SHA-256 inválido en el manifest de muestra.")
    return value


def _https_url(value: object) -> str:
    """Solo admite HTTPS sin credenciales, query ni fragmento."""
    if not isinstance(value, str) or any(c.isspace() for c in value):
        raise SampleError("URL de muestra inválida; se requiere HTTPS.")
    try:
        url = urllib.parse.urlsplit(value)
        port = url.port
    except ValueError as exc:
        raise SampleError("URL de muestra inválida.") from exc
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or port not in (None, 443)
    ):
        raise SampleError("URL de muestra inválida; se requiere HTTPS sin credenciales.")
    return value


def load_manifest(path: Path) -> SampleManifest:
    """Lee el contrato local; no realiza conexiones de red."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("format") != 1 or raw.get("version") != SAMPLE_VERSION:
            raise SampleError("Versión de manifest de muestra no compatible.")
        archive = raw["archive"]
        entries = raw["files"]
        if not isinstance(archive, dict) or not isinstance(entries, list):
            raise SampleError("Estructura de manifest de muestra inválida.")
        files = tuple(
            SampleFile(validate_sample_path(entry["path"]), _size(entry["size"]), _sha256(entry["sha256"]))
            for entry in entries
        )
        expected = {f"001/t0/1_t0_{seq}.nii.gz" for seq in SAMPLE_SEQUENCES}
        if len(files) != len(expected) or {entry.path for entry in files} != expected:
            raise SampleError("El manifest debe declarar exactamente los cuatro NIfTI de 001/t0.")
        archive_size = _size(archive["size"])
        if archive_size < sum(entry.size for entry in files):
            raise SampleError("Tamaño del artefacto menor que sus archivos.")
        return SampleManifest(
            SAMPLE_VERSION, _https_url(archive["url"]), archive_size, _sha256(archive["sha256"]), files
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SampleError("No se pudo leer el manifest de muestra de la release.") from exc


def file_digest(stream: IO[bytes]) -> tuple[int, str]:
    """Calcula tamaño y SHA-256 por bloques, sin cargar el volumen en memoria."""
    digest = hashlib.sha256()
    size = 0
    while block := stream.read(CHUNK):
        size += len(block)
        digest.update(block)
    return size, digest.hexdigest()


def verify_file(stream: BinaryIO, entry: SampleFile) -> None:
    """Detecta LFS, bytes distintos y cabeceras ajenas a NIfTI gzip."""
    prefix = stream.read(128)
    if prefix.startswith(LFS_PREFIX):
        raise SampleError("Se encontró un puntero Git LFS; se requieren los NIfTI reales.")
    stream.seek(0)
    if file_digest(stream) != (entry.size, entry.sha256):
        raise SampleError(
            "Muestra existente distinta o corrupta. Consérvela y use CERBERUS_SAMPLE_MODE=none para datos propios."
        )
    stream.seek(0)
    try:
        with gzip.GzipFile(fileobj=stream) as compressed:
            header = compressed.read(352)
        if len(header) != 352 or (header[344:348] != b"n+1\x00" and header[4:12] != b"n+2\x00\r\n\x1a\n"):
            raise SampleError("El archivo de muestra no contiene una cabecera NIfTI válida.")
    except (OSError, EOFError) as exc:
        raise SampleError("NIfTI comprimido inválido o truncado.") from exc


@contextlib.contextmanager
def secure_directory(path: Path, *, create: bool = True) -> Iterator[int]:
    """Abre cada directorio sin seguir symlinks, también en ancestros de Data."""
    absolute = path.absolute()
    fd = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in absolute.parts[1:]:
            if component in ("", ".", ".."):
                raise SampleError("Directorio de datos inválido.")
            if create:
                try:
                    os.mkdir(component, mode=0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    except OSError as exc:
        raise SampleError("No se puede abrir Data: revise permisos, directorios y enlaces simbólicos.") from exc
    finally:
        os.close(fd)


@contextlib.contextmanager
def _study_directory(data_fd: int, *, create: bool) -> Iterator[int | None]:
    """Accede a la carpeta fija de la muestra sin seguir enlaces simbólicos."""
    fds: list[int] = []
    current = data_fd
    try:
        for component in ("001", "t0"):
            if create:
                try:
                    os.mkdir(component, mode=0o755, dir_fd=current)
                except FileExistsError:
                    pass
            try:
                current = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            except FileNotFoundError:
                yield None
                return
            fds.append(current)
        yield current
    except OSError as exc:
        raise SampleError(
            "001/t0 debe contener directorios reales y permitir escritura; no se siguen symlinks."
        ) from exc
    finally:
        for fd in reversed(fds):
            os.close(fd)


def _missing_files(data_fd: int, manifest: SampleManifest) -> list[SampleFile]:
    """Valida todos los existentes antes de permitir una descarga o publicación."""
    missing: list[SampleFile] = []
    with _study_directory(data_fd, create=False) as study_fd:
        if study_fd is None:
            return list(manifest.files)
        for entry in manifest.files:
            try:
                fd = os.open(entry.path.rsplit("/", 1)[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=study_fd)
            except FileNotFoundError:
                missing.append(entry)
                continue
            except OSError as exc:
                raise SampleError("Archivo de muestra inaccesible o symlink; no se reemplazó ningún archivo.") from exc
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise SampleError("La muestra contiene un archivo especial; se requieren archivos regulares.")
                verify_file(stream, entry)
    return missing


class _HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub puede redirigir a su CDN, siempre mediante HTTPS."""

    def redirect_request(
        self, req: urllib.request.Request, fp: IO[bytes], code: int, msg: str, headers: HTTPMessage, newurl: str
    ) -> urllib.request.Request | None:
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise SampleError("La descarga intentó abandonar HTTPS.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_archive(manifest: SampleManifest, output: BinaryIO) -> None:
    """Descarga acotada al tamaño declarado; nunca informa URLs firmadas o errores remotos."""
    opener = urllib.request.build_opener(_HTTPSRedirect())
    digest = hashlib.sha256()
    received = 0
    try:
        with opener.open(manifest.url, timeout=60) as response:
            while block := response.read(CHUNK):
                received += len(block)
                if received > manifest.size:
                    raise SampleError("El artefacto supera el tamaño declarado.")
                output.write(block)
                digest.update(block)
            output.flush()
            os.fsync(output.fileno())
    except (OSError, urllib.error.URLError) as exc:
        raise SampleError(
            "No se pudo descargar la muestra. Revise red y disponibilidad de la release; vuelva a intentar."
        ) from exc
    if (received, digest.hexdigest()) != (manifest.size, manifest.sha256):
        raise SampleError("Artefacto de muestra incompleto o corrupto; vuelva a intentar.")


def extract_archive(archive: BinaryIO, staging_fd: int, manifest: SampleManifest) -> None:
    """Extrae solo archivos regulares declarados, sin extractall ni rutas del TAR."""
    expected = {entry.path: entry for entry in manifest.files}
    seen: set[str] = set()
    try:
        with tarfile.open(fileobj=archive, mode="r:") as bundle:
            for member in bundle:
                name = validate_sample_path(member.name)
                if name not in expected or name in seen or not member.isfile() or member.linkname:
                    raise SampleError("El artefacto contiene entradas duplicadas, enlaces o archivos no declarados.")
                entry = expected[name]
                if member.size != entry.size or member.pax_headers or member.sparse is not None:
                    raise SampleError("Tamaño o formato TAR no permitido.")
                source = bundle.extractfile(member)
                if source is None:
                    raise SampleError("Entrada TAR incompleta.")
                # El nombre ya pasó por cerberus_api.sequences; nunca se usan rutas de extracción libres.
                filename = name.rsplit("/", 1)[1]
                fd = os.open(filename, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o644, dir_fd=staging_fd)
                with source, os.fdopen(fd, "wb+") as output:
                    shutil.copyfileobj(source, output, CHUNK)
                    output.flush()
                    os.fsync(output.fileno())
                    output.seek(0)
                    verify_file(output, entry)
                seen.add(name)
        if seen != set(expected):
            raise SampleError("Faltan archivos de muestra en el artefacto.")
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise SampleError("Artefacto TAR inválido o interrumpido; vuelva a intentar.") from exc


@contextlib.contextmanager
def temporary_directory(data_fd: int) -> Iterator[int]:
    """Temporal en el mismo filesystem, creado y retirado por descriptor sin seguir enlaces."""
    name = ".cerberus-sample-" + secrets.token_hex(16)
    os.mkdir(name, mode=0o700, dir_fd=data_fd)
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=data_fd)
    try:
        yield fd
    finally:
        os.close(fd)
        shutil.rmtree(name, dir_fd=data_fd)


def ensure_sample(manifest_path: Path, data: Path, *, mode: str = "auto") -> str:
    """Instala la muestra tras validarla; repetir con datos válidos nunca consulta red."""
    if mode == "none":
        return "Muestra omitida explícitamente (CERBERUS_SAMPLE_MODE=none)."
    if mode != "auto":
        raise SampleError("CERBERUS_SAMPLE_MODE debe ser auto o none.")
    manifest = load_manifest(manifest_path)
    with secure_directory(data) as data_fd:
        lock_fd = os.open(
            ".cerberus-sample.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=data_fd
        )
        with os.fdopen(lock_fd, "rb+") as lock:
            if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
                raise SampleError("El bloqueo de muestra debe ser un archivo regular.")
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SampleError("Otra preparación de muestra sigue activa; espere y vuelva a intentar.") from exc
            missing = _missing_files(data_fd, manifest)
            if not missing:
                return "Muestra 001/t0 verificada; sin descarga."
            required = manifest.size + sum(entry.size for entry in manifest.files) + 16 * CHUNK
            if os.fstatvfs(data_fd).f_bavail * os.fstatvfs(data_fd).f_frsize < required:
                raise SampleError(f"Espacio insuficiente para preparar muestra: se requieren {required} bytes libres.")
            with temporary_directory(data_fd) as staging_fd:
                archive_fd = os.open(
                    "sample.tar", os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=staging_fd
                )
                with os.fdopen(archive_fd, "wb+") as archive:
                    download_archive(manifest, archive)
                    archive.seek(0)
                    extract_archive(archive, staging_fd, manifest)
                # Revalidar después de la descarga detecta escrituras concurrentes ajenas al bloqueo.
                missing = _missing_files(data_fd, manifest)
                with _study_directory(data_fd, create=True) as study_fd:
                    assert study_fd is not None
                    for entry in missing:
                        filename = entry.path.rsplit("/", 1)[1]
                        try:
                            os.link(
                                filename, filename, src_dir_fd=staging_fd, dst_dir_fd=study_fd, follow_symlinks=False
                            )
                        except FileExistsError as exc:
                            raise SampleError(
                                "Apareció un archivo durante la preparación; se conservó sin reemplazar."
                            ) from exc
                    os.fsync(study_fd)
            return "Muestra 001/t0 preparada y verificada."


def main(argv: list[str] | None = None) -> int:
    """Entrada para el inicializador de Compose; errores sin rutas privadas ni URLs remotas."""
    parser = argparse.ArgumentParser(description="Preparar muestra pública CFB-GBM sin reemplazar datos.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(ensure_sample(args.manifest, args.data, mode=os.environ.get("CERBERUS_SAMPLE_MODE", "auto")))
        return 0
    except SampleError as exc:
        print(f"Muestra: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("Muestra: fallo de E/S; revise permisos y espacio.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Muestra: preparación cancelada; puede volver a intentar.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
