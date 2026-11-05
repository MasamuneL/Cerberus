"""Fixtures compartidas: NIfTI sintéticos con la convención de Data/ (docs/PLAN_MVP.md §6)."""

from collections.abc import Callable, Sequence
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

MakeNifti = Callable[..., Path]
MakeStudy = Callable[..., Path]
_AUTH_ENV_NAMES = (
    "AUTH_MODE",
    "APP_ORIGIN",
    "OIDC_ISSUER_URL",
    "OIDC_BACKCHANNEL_URL",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
    "AUTH_COOKIE_SECURE",
    "AUTH_IDLE_TIMEOUT_SECONDS",
    "AUTH_ABSOLUTE_TIMEOUT_SECONDS",
)
_AUTH_ENV_PATCH = pytest.StashKey[pytest.MonkeyPatch]()


def pytest_configure(config: pytest.Config) -> None:
    """Aísla auth antes de que la colección importe `main.app` y cachee `Settings`."""
    patch = pytest.MonkeyPatch()
    for name in _AUTH_ENV_NAMES:
        patch.delenv(f"CERBERUS_{name}", raising=False)
    config.stash[_AUTH_ENV_PATCH] = patch


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restaura el entorno si pytest se ejecuta dentro de otro proceso Python."""
    patch = config.stash.get(_AUTH_ENV_PATCH, None)
    if patch is not None:
        patch.undo()


@pytest.fixture(autouse=True)
def _clean_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """El entorno OIDC de una demo no debe activar auth en las pruebas existentes."""
    for name in _AUTH_ENV_NAMES:
        monkeypatch.delenv(f"CERBERUS_{name}", raising=False)


# Cubo de GTV conocido (10×10×10 vóxeles) y caja de cerebro más grande, en índices de vóxel
GTV_SLICE = (slice(10, 20), slice(10, 20), slice(5, 15))
BRAIN_SLICE = (slice(2, 38), slice(2, 38), slice(1, 19))


def _write_nifti(path: Path, data: np.ndarray, zooms: Sequence[float] = (0.5, 0.5, 1.0)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    affine = np.diag([*zooms, 1.0])
    nib.save(nib.Nifti1Image(data, affine), path)
    return path


@pytest.fixture
def make_nifti() -> MakeNifti:
    """`make_nifti(path, data, zooms=(0.5, 0.5, 1.0))` → escribe un NIfTI con affine diagonal."""
    return _write_nifti


@pytest.fixture
def make_study() -> MakeStudy:
    """`make_study(root, patient="001", timepoint="t0", seqs=(...), shape=(40, 40, 20), zooms=...)`.

    Escribe `root/<patient>/<timepoint>/<int(patient)>_<timepoint>_<seq>.nii.gz`.
    `gtv` = cubo GTV_SLICE, `brain_mask` = caja BRAIN_SLICE, resto = ruido float32 dentro del cerebro.
    Devuelve el directorio del estudio.
    """

    def _make(
        root: Path,
        patient: str = "001",
        timepoint: str = "t0",
        seqs: Sequence[str] = ("t1gd", "flair", "gtv", "brain_mask"),
        shape: tuple[int, int, int] = (40, 40, 20),
        zooms: Sequence[float] = (0.5, 0.5, 1.0),
    ) -> Path:
        study_dir = root / patient / timepoint
        rng = np.random.default_rng(0)
        for seq in seqs:
            if seq == "gtv":
                data = np.zeros(shape, np.uint8)
                data[GTV_SLICE] = 1
            elif seq == "brain_mask":
                data = np.zeros(shape, np.uint8)
                data[BRAIN_SLICE] = 1
            else:
                data = np.zeros(shape, np.float32)
                data[BRAIN_SLICE] = rng.normal(100, 10, data[BRAIN_SLICE].shape)
                data[GTV_SLICE] += 50
            _write_nifti(study_dir / f"{int(patient)}_{timepoint}_{seq}.nii.gz", data, zooms)
        return study_dir

    return _make
