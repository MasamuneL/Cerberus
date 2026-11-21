"""Tests de atlas.py: hemisferios con un atlas sintético y `map_atlas` con transformación identidad.

Los rápidos no usan red ni corren el registro ANTs (se reemplaza `_register` por una afín identidad, o
`ants.registration` y la etapa afín en subproceso por dobles); los `slow` registran de verdad Data/001/t0.
"""

import hashlib
import io
import json
import math
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import ants
import nibabel as nib
import numpy as np
import pytest
from scipy.ndimage import distance_transform_edt

from cerberus_api import atlas, linear_reg
from cerberus_api.atlas import (
    WARN_LARGE_GTV,
    WARN_NO_BRAIN,
    WARN_ONLY_T1GD,
    affine_of,
    affine_qc,
    map_atlas,
    registration_warnings,
    select_sequences,
    split_hemispheres,
    which_to_invert,
)
from cerberus_api.config import REPO_ROOT, RegistrationMode
from cerberus_api.nifti import load_nifti
from cerberus_api.runtime import THREAD_ENV_VARS

LABELS = ["Background", "Brodmann area 4", "Putamen"]


def _synthetic_atlas() -> nib.Nifti1Image:
    """10×4×4 a 2 mm con x del mundo de -10 a +8: índice 1 en z>=1, índice 2 en x<=-6 (j=0, z=1), fondo en z=0."""
    data = np.zeros((10, 4, 4), np.int16)
    data[:, :, 1:] = 1
    data[:3, 0, 1] = 2
    affine = np.diag([2.0, 2.0, 2.0, 1.0])
    affine[:3, 3] = (-10, -4, -4)
    return nib.Nifti1Image(data, affine)


def test_split_hemispheres_encoding() -> None:
    img, entries = split_hemispheres(_synthetic_atlas(), LABELS)
    out = np.asarray(img.dataobj)
    assert out.dtype == np.uint8 and np.allclose(affine_of(img), affine_of(_synthetic_atlas()))
    # i=0..4 → x=-10..-2 (izquierdo); i=5..9 → x=0..8 (derecho; x=0 cuenta como derecho)
    assert (out[:, :, 0] == 0).all()
    assert (out[3:5, :, 1:] == 1).all() and (out[5:, :, 1:] == 101).all()
    assert (out[:3, 0, 1] == 2).all() and (out[:3, 1:, 1:] == 1).all()
    assert set(np.unique(out).tolist()) == {0, 1, 2, 101}
    assert entries == [
        (1, "Brodmann area 4", "izquierdo"),
        (2, "Putamen", "izquierdo"),
        (101, "Brodmann area 4", "derecho"),
    ]


def test_split_hemispheres_flipped_affine_without_labels() -> None:
    src = _synthetic_atlas()
    flipped = affine_of(src).copy()
    flipped[0, 0], flipped[0, 3] = -2.0, 8.0  # i=0 → x=8 (derecho), i=9 → x=-10 (izquierdo)
    img, entries = split_hemispheres(nib.Nifti1Image(np.asarray(src.dataobj), flipped))
    out = np.asarray(img.dataobj)
    assert (out[:5, :, 1:] >= 100).all() and (out[5:, :, 1:] < 100).all()
    assert (102, "2", "derecho") in entries and (2, "2", "izquierdo") not in entries


def test_split_hemispheres_rejects_large_indices() -> None:
    with pytest.raises(ValueError):
        split_hemispheres(nib.Nifti1Image(np.full((2, 2, 2), 120, np.int16), np.eye(4)))


@pytest.mark.parametrize(
    ("seqs", "expected"),
    [
        (("t1gd", "t1eg", "flair"), ("t1gd", "t1eg")),
        (("t1gd", "t1tse"), ("t1gd", "t1tse")),
        (("t1gd", "flair"), ("t1gd", "t1gd")),
        (("t1tse", "flair"), ("t1tse", "t1tse")),
        (("flair", "t1eg"), ("t1eg", "t1eg")),
    ],
)
def test_select_sequences(seqs: tuple[str, ...], expected: tuple[str, str]) -> None:
    assert select_sequences({s: Path(f"{s}.nii.gz") for s in seqs}) == expected


def test_select_sequences_without_t1_raises() -> None:
    with pytest.raises(ValueError):
        select_sequences({"flair": Path("f.nii.gz"), "gtv": Path("g.nii.gz")})


def test_which_to_invert() -> None:
    assert which_to_invert(["a/pat2mni_0GenericAffine.mat", "a/pat2mni_1InverseWarp.nii.gz"]) == [True, False]


# --- map_atlas con un registro falso (afín identidad) ----------------------------------------------------

# Grid del "paciente" alineado con el atlas sintético pero con x invertido: x del mundo = 8 - 2i
REF_AFFINE = np.array([[-2.0, 0, 0, 8.0], [0, 2.0, 0, -4.0], [0, 0, 2.0, -4.0], [0, 0, 0, 1]])


def _write(path: Path, data: np.ndarray) -> Path:
    nib.save(nib.Nifti1Image(data, REF_AFFINE), path)
    return path


def _study(tmp: Path, seqs: tuple[str, ...]) -> dict[str, Path]:
    tmp.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    for s in seqs:
        if s == "brain_mask":
            data = np.ones((10, 4, 4), np.uint8)
            data[:, 3, :] = 0
        elif s == "gtv":
            data = np.zeros((10, 4, 4), np.uint8)
            data[4:6, 1:3, 1:3] = 1
        else:
            data = np.random.default_rng(0).normal(100, 10, (10, 4, 4)).astype(np.float32)
        files[s] = _write(tmp / f"{s}.nii.gz", data)
    return files


@pytest.fixture
def fake_register(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Sustituye el atlas por el sintético y `_register` por una afín identidad; cuenta los registros."""
    import ants

    calls: list[int] = []

    def register(
        study_files: dict[str, Path],
        moving_seq: str,
        mni_dir: Path,
        models_dir: Path,
        tmp: Path,
        mode: RegistrationMode = "full",
        while_linear: Callable[[], None] | None = None,
    ) -> list[str]:
        calls.append(1)
        if while_linear is not None:
            while_linear()
        mni_dir.mkdir(parents=True, exist_ok=True)
        tx = mni_dir / "pat2mni_0GenericAffine.mat"
        ants.write_transform(ants.create_ants_transform(transform_type="AffineTransform", dimension=3), str(tx))
        meta = {"key": atlas._cache_key(study_files, moving_seq, mode), "invtransforms": [tx.name]}
        (mni_dir / atlas.CACHE_FILE).write_text(json.dumps(meta), encoding="utf-8")
        return [str(tx)]

    monkeypatch.setattr(atlas, "fetch_atlas", lambda models_dir: (_synthetic_atlas(), LABELS))
    monkeypatch.setattr(atlas, "_register", register)
    return calls


def test_map_atlas_identity(tmp_path: Path, fake_register: list[int]) -> None:
    files = _study(tmp_path / "s", ("t1gd", "t1eg", "brain_mask", "gtv"))
    res = map_atlas(files, tmp_path / "out", tmp_path / "models")

    assert res.label_path == tmp_path / "out" / "brodmann.nii.gz"
    assert res.reference_sequence == "t1gd"
    assert res.warnings == []
    assert "t1eg→MNI152 (GTV excluido del costo)" in res.registration
    img = load_nifti(res.label_path)
    assert np.allclose(affine_of(img), REF_AFFINE) and img.shape == (10, 4, 4)
    lab = np.asarray(img.dataobj)
    assert lab.dtype == np.uint8
    # Fondo del atlas (z=0) y fuera de brain_mask (j=3) en cero
    assert (lab[:, :, 0] == 0).all() and (lab[:, 3, :] == 0).all()
    # i=0..4 → x=8..0 (derecho); i=5..9 → x=-2..-10 (izquierdo); el índice 2 cae en x<=-6 → i=7..9
    assert (lab[:5, :3, 1:] == 101).all() and (lab[5:7, :3, 1:] == 1).all()
    assert (lab[7:, 0, 1] == 2).all() and (lab[7:, 1:3, 1:] == 1).all()
    assert res.entries == [
        (1, "Brodmann area 4", "izquierdo"),
        (2, "Putamen", "izquierdo"),
        (101, "Brodmann area 4", "derecho"),
    ]

    # Segunda corrida: reutiliza las transformaciones de out/mni
    map_atlas(files, tmp_path / "out", tmp_path / "models")
    assert len(fake_register) == 1
    # Si cambia la imagen móvil, se registra de nuevo
    _write(files["t1eg"], np.zeros((10, 4, 4), np.float32))
    map_atlas(files, tmp_path / "out", tmp_path / "models")
    assert len(fake_register) == 2


def test_map_atlas_registration_mode(tmp_path: Path, fake_register: list[int]) -> None:
    """El modo `fast` se anota en el texto, no reutiliza las transformaciones de `full` y viceversa."""
    files = _study(tmp_path / "s", ("t1gd", "t1eg", "brain_mask", "gtv"))
    out = tmp_path / "out"
    full = map_atlas(files, out, tmp_path / "m")
    assert "(rápido)" not in full.registration and full.registration.startswith("ANTs SyN t1eg→MNI152")

    fast = map_atlas(files, out, tmp_path / "m", "fast")
    assert fast.registration == full.registration + " (rápido)"
    assert len(fake_register) == 2  # la caché de `full` no sirve para `fast`

    map_atlas(files, out, tmp_path / "m", "fast")
    assert len(fake_register) == 2  # misma huella: se reutiliza
    map_atlas(files, out, tmp_path / "m", "full")
    assert len(fake_register) == 2  # cada modo tiene su directorio: `full` reutiliza mni/
    assert (out / "mni").is_dir() and (out / "mni_fast").is_dir()


def _pre_reg1_key(files: dict[str, Path], moving_seq: str) -> str:
    """Huella de `full` de HW3 (antes de REG1), tal como la calculaba `_cache_key`."""
    h = hashlib.sha256()
    for seq in (moving_seq, "brain_mask", "gtv"):
        st = files[seq].stat()
        h.update(f"{seq}:{files[seq].resolve()}:{st.st_size}:{st.st_mtime_ns};".encode())
    h.update(b"SyN:1.5:5.0:42")
    return h.hexdigest()


def test_cache_key_depends_on_mode_and_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = _study(tmp_path / "s", ("t1eg", "brain_mask", "gtv"))
    full = atlas._cache_key(files, "t1eg", "full")
    assert full != atlas._cache_key(files, "t1eg", "fast")
    assert full == atlas._cache_key(files, "t1eg")
    # REG1 versiona la huella: las transformaciones de antes (afín multihilo) ya no valen
    assert full != _pre_reg1_key(files, "t1eg")
    monkeypatch.setattr(atlas, "REGISTRATION_VERSION", atlas.REGISTRATION_VERSION + 1)
    assert atlas._cache_key(files, "t1eg", "full") != full


def test_map_atlas_reregisters_pre_reg1_cache(tmp_path: Path, fake_register: list[int]) -> None:
    """Un `mni/transforms.json` de HW3 (huella sin versión) se ignora y se registra de nuevo."""
    files = _study(tmp_path / "s", ("t1gd", "t1eg", "brain_mask", "gtv"))
    out = tmp_path / "out"
    mni = out / "mni"
    mni.mkdir(parents=True)
    tx = mni / "pat2mni_0GenericAffine.mat"
    ants.write_transform(ants.create_ants_transform(transform_type="AffineTransform", dimension=3), str(tx))
    old = {"key": _pre_reg1_key(files, "t1eg"), "invtransforms": [tx.name]}
    (mni / atlas.CACHE_FILE).write_text(json.dumps(old), encoding="utf-8")

    map_atlas(files, out, tmp_path / "m")
    assert len(fake_register) == 1
    meta = json.loads((mni / atlas.CACHE_FILE).read_text(encoding="utf-8"))
    assert meta["key"] == atlas._cache_key(files, "t1eg", "full")
    map_atlas(files, out, tmp_path / "m")
    assert len(fake_register) == 1  # la caché nueva sí se reutiliza


class FakeLinearStage:
    """Doble de `atlas.LinearStage`: escribe una afín identidad en vez de lanzar el subproceso."""

    instances: list["FakeLinearStage"] = []

    def __init__(self, tmp: Path, events: list[str]) -> None:
        self.tmp = tmp
        self.events = events
        self.args: dict[str, Any] = {}
        self.closed = False
        events.append("linear_start")

    def submit(self, args: dict[str, Any]) -> None:
        assert all(Path(args[k]).is_file() for k in ("fixed", "moving", "mask", "moving_mask"))
        self.args = args
        self.events.append("linear_submit")

    def result(self) -> str:
        self.events.append("linear_result")
        path = Path(self.args["outprefix"] + "0GenericAffine.mat")
        ants.write_transform(ants.create_ants_transform(transform_type="AffineTransform", dimension=3), str(path))
        return str(path)

    def close(self) -> None:
        self.closed = True


def _capture_registration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: RegistrationMode
) -> tuple[dict[str, object], tuple[float, ...], list[str], FakeLinearStage]:
    """Corre `_register` con dobles de la etapa afín y de `ants.registration`.

    Devuelve los kwargs del SyN, el spacing de la imagen móvil, el orden de las etapas y la etapa afín falsa.
    """
    seen: dict[str, object] = {}
    spacing: list[tuple[float, ...]] = []
    events: list[str] = []
    stages: list[FakeLinearStage] = []

    def make_stage(tmp: Path) -> FakeLinearStage:
        stage = FakeLinearStage(tmp, events)
        stages.append(stage)
        return stage

    def fake_registration(**kwargs: object) -> dict[str, list[str]]:
        events.append("syn")
        seen.update(kwargs)
        moving: Any = kwargs["moving"]
        spacing.append(tuple(float(z) for z in moving.spacing))
        out = Path(str(kwargs["outprefix"]))
        affine = out.parent / (out.name + "0GenericAffine.mat")
        ants.write_transform(ants.create_ants_transform(transform_type="AffineTransform", dimension=3), str(affine))
        warp = out.parent / (out.name + "1Warp.nii.gz")
        inv_warp = out.parent / (out.name + "1InverseWarp.nii.gz")
        warp.write_bytes(b"")
        inv_warp.write_bytes(b"")
        return {"fwdtransforms": [str(warp), str(affine)], "invtransforms": [str(affine), str(inv_warp)]}

    def fake_apply(**kwargs: Any) -> Any:
        # QC: la máscara de cerebro del paciente "deformada" = la de la plantilla (Dice 1)
        events.append("qc")
        return kwargs["fixed"]

    template = nib.Nifti1Image(np.ones((6, 6, 6), np.float32), np.eye(4))
    mask = nib.Nifti1Image(np.ones((6, 6, 6), np.uint8), np.eye(4))
    monkeypatch.setattr(atlas, "fetch_template", lambda models_dir: (template, mask))
    monkeypatch.setattr(atlas, "LinearStage", make_stage)
    monkeypatch.setattr(ants, "registration", fake_registration)
    monkeypatch.setattr(ants, "apply_transforms", fake_apply)

    study = tmp_path / "study"
    files = _study(study, ("t1eg", "brain_mask", "gtv"))
    work = tmp_path / "work"
    work.mkdir()
    atlas._register(
        files, "t1eg", tmp_path / "mni", tmp_path / "models", work, mode, while_linear=lambda: events.append("while")
    )
    return seen, spacing[0], events, stages[0]


def test_register_full_two_stages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`full`: afín en el subproceso (1 hilo) y luego SyNOnly multihilo con `initial_transform`; QC en el meta."""
    kwargs, spacing, events, stage = _capture_registration(monkeypatch, tmp_path, "full")
    assert events == ["linear_start", "linear_submit", "while", "linear_result", "syn", "qc"]
    assert stage.closed
    assert stage.args["random_seed"] == 42 and stage.args["outprefix"].endswith("linear_")
    assert set(kwargs) == {
        "fixed",
        "moving",
        "type_of_transform",
        "initial_transform",
        "outprefix",
        "mask",
        "moving_mask",
        "mask_all_stages",
        "random_seed",
    }
    assert kwargs["type_of_transform"] == "SyNOnly" and kwargs["mask_all_stages"] is True
    assert kwargs["initial_transform"] == [stage.args["outprefix"] + "0GenericAffine.mat"]
    assert kwargs["random_seed"] == 42
    assert np.allclose(spacing, (1.5, 1.5, 1.5))
    meta = json.loads((tmp_path / "mni" / atlas.CACHE_FILE).read_text(encoding="utf-8"))
    assert meta["registration_mode"] == "full" and meta["type_of_transform"] == "SyN"
    assert meta["registration_version"] == atlas.REGISTRATION_VERSION
    assert meta["invtransforms"] == ["pat2mni_0GenericAffine.mat", "pat2mni_1InverseWarp.nii.gz"]
    qc = meta["qc"]
    assert qc["det"] == pytest.approx(1.0) and qc["rotation_deg"] == pytest.approx(0.0, abs=1e-6)
    assert qc["brain_dice"] == pytest.approx(1.0)
    # Cerebro del paciente: 10×3×4 vóxeles de 2 mm = 960 mm³ (≈, remuestreado a 1.5 mm); plantilla 6³ de 1 mm = 216 mm³
    assert qc["volume_ratio"] == pytest.approx(960 / 216, rel=0.35)
    assert qc["scale"] == pytest.approx(qc["det"] / qc["volume_ratio"], rel=1e-3)


def test_register_fast_changes_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    profile = atlas.REGISTRATION_PROFILES["fast"]
    kwargs, spacing, events, _ = _capture_registration(monkeypatch, tmp_path, "fast")
    assert events[:5] == ["linear_start", "linear_submit", "while", "linear_result", "syn"]
    assert kwargs["type_of_transform"] == "SyNOnly"
    assert all(kwargs[k] == v for k, v in profile.extra_kwargs.items())
    assert kwargs["mask_all_stages"] is True and kwargs["random_seed"] == 42
    assert np.allclose(spacing, (profile.spacing_mm,) * 3) and profile.spacing_mm > atlas.MOVING_SPACING_MM


def test_register_closes_linear_stage_on_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Si falla la preparación, el subproceso se cierra igual (no queda un hijo esperando stdin)."""
    stages: list[FakeLinearStage] = []

    def make_stage(tmp: Path) -> FakeLinearStage:
        stages.append(FakeLinearStage(tmp, []))
        return stages[-1]

    def boom(models_dir: Path) -> Any:
        raise OSError("sin plantilla")

    monkeypatch.setattr(atlas, "LinearStage", make_stage)
    monkeypatch.setattr(atlas, "fetch_template", boom)
    files = _study(tmp_path / "s", ("t1eg", "brain_mask"))
    with pytest.raises(OSError):
        atlas._register(files, "t1eg", tmp_path / "mni", tmp_path / "m", tmp_path)
    assert stages[0].closed and not (tmp_path / "mni").exists()


# --- Etapa afín en subproceso ----------------------------------------------------------------------------


class _RecordingStdin(io.StringIO):
    """stdin que conserva lo escrito después de `close()`."""

    written = ""

    def close(self) -> None:
        self.written = self.getvalue()
        super().close()


class _FakePopen:
    """Doble de `subprocess.Popen` que registra comando y entorno y simula la salida del hijo."""

    def __init__(self, cmd: list[str], *, stdout_text: str, code: int, **kwargs: Any) -> None:
        self.cmd = cmd
        self.kwargs = kwargs
        self.stdin = _RecordingStdin()
        self.stdout = io.StringIO(stdout_text)
        self.returncode: int | None = None
        self._code = code
        self.killed = False

    def wait(self) -> int:
        self.returncode = self._code
        return self._code

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def _patch_popen(monkeypatch: pytest.MonkeyPatch, stdout_text: str, code: int) -> list[_FakePopen]:
    procs: list[_FakePopen] = []

    def popen(cmd: list[str], **kwargs: Any) -> _FakePopen:
        procs.append(_FakePopen(cmd, stdout_text=stdout_text, code=code, **kwargs))
        return procs[-1]

    monkeypatch.setattr(atlas.subprocess, "Popen", popen)
    return procs


def test_linear_stage_one_thread_env_and_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mat = tmp_path / "linear_0GenericAffine.mat"
    mat.write_bytes(b"x")
    procs = _patch_popen(monkeypatch, f"aviso\n{mat}\n", 0)
    monkeypatch.setenv("ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS", "8")

    stage = atlas.LinearStage(tmp_path)
    proc = procs[0]
    assert proc.cmd == [sys.executable, "-m", "cerberus_api.linear_reg"]
    env = proc.kwargs["env"]
    assert all(env[v] == "1" for v in THREAD_ENV_VARS)
    stage.submit({"fixed": "f.nii.gz"})
    assert json.loads(proc.stdin.written) == {"fixed": "f.nii.gz"} and proc.stdin.closed
    assert stage.result() == str(mat)
    stage.close()
    assert not proc.killed


def test_linear_stage_failure_raises_and_close_kills(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_popen(monkeypatch, "", 1)
    stage = atlas.LinearStage(tmp_path)
    (tmp_path / "linear_stderr.txt").write_text("Traceback: boom", encoding="utf-8")
    with pytest.raises(RuntimeError, match="etapa afín"):
        stage.result()
    stage.close()

    procs = _patch_popen(monkeypatch, "", 0)
    stage = atlas.LinearStage(tmp_path)
    stage.close()  # sigue vivo (no se esperó): se mata
    assert procs[0].killed


def test_linear_stage_real_subprocess_reports_child_error(tmp_path: Path) -> None:
    """Fontanería real (stdin, stderr a archivo, código de salida) con un hijo que falla al leer imágenes."""
    stage = atlas.LinearStage(tmp_path)
    try:
        missing = str(tmp_path / "no_existe.nii.gz")
        stage.submit(
            {"fixed": missing, "moving": missing, "mask": missing, "moving_mask": missing, "outprefix": "x_"}
            | {"random_seed": 42}
        )
        with pytest.raises(RuntimeError, match="código 1"):
            stage.result()
    finally:
        stage.close()


def test_linear_reg_runs_affine_stage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`linear_reg` replica la etapa afín del "SyN" de ANTsPy (solo cambia el número de hilos)."""
    seen: dict[str, Any] = {}

    def fake_registration(**kwargs: Any) -> dict[str, list[str]]:
        seen.update(kwargs)
        return {"fwdtransforms": [kwargs["outprefix"] + "0GenericAffine.mat"]}

    monkeypatch.setattr(ants, "registration", fake_registration)
    monkeypatch.setattr(ants, "image_read", lambda path: path)
    args = {"fixed": "f", "moving": "m", "mask": "fm", "moving_mask": "mm", "outprefix": "p_", "random_seed": 42}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(args)))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    linear_reg.main([])
    assert out.getvalue().strip() == "p_0GenericAffine.mat"
    assert seen["type_of_transform"] == "Affine" and seen["random_seed"] == 42
    assert seen["mask"] == "fm" and seen["moving_mask"] == "mm"
    assert seen["aff_iterations"] == (2100, 1200, 1200, 0)
    assert seen["aff_shrink_factors"] == (4, 2, 2, 1) and seen["aff_smoothing_sigmas"] == (3, 2, 1, 0)
    assert seen["aff_random_sampling_rate"] == 0.2 and seen["aff_metric"] == "mattes"


# --- QC del registro -------------------------------------------------------------------------------------


def _rot_x(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def test_affine_qc_synthetic_matrices() -> None:
    det, rot = affine_qc(np.eye(3))
    assert det == pytest.approx(1.0) and rot == pytest.approx(0.0, abs=1e-6)
    det, rot = affine_qc(_rot_x(22.0))
    assert det == pytest.approx(1.0) and rot == pytest.approx(22.0)
    # La escala y la cizalla no cambian la rotación de la descomposición polar
    det, rot = affine_qc(_rot_x(10.0) @ np.diag([0.8, 0.9, 0.85]))
    assert det == pytest.approx(0.8 * 0.9 * 0.85) and rot == pytest.approx(10.0, abs=1e-6)
    det, _ = affine_qc(np.diag([0.5, 0.5, 0.5]))
    assert det == pytest.approx(0.125)


def test_registration_warnings_thresholds() -> None:
    ok = {"det": 0.6, "rotation_deg": 22.0, "scale": 0.91, "brain_dice": 0.92}
    assert registration_warnings(ok) == []
    assert registration_warnings({}) == []
    low = registration_warnings({**ok, "scale": 0.5})
    assert len(low) == 1 and "×0.50" in low[0] and "0.7–1.4" in low[0]
    assert len(registration_warnings({**ok, "scale": 1.6})) == 1
    rot = registration_warnings({**ok, "rotation_deg": atlas.MAX_ROTATION_DEG + 5})
    assert len(rot) == 1 and "rota" in rot[0]
    bad = registration_warnings({**ok, "brain_dice": atlas.MIN_BRAIN_DICE - 0.1})
    assert len(bad) == 1 and "Dice" in bad[0]
    assert len(registration_warnings({"scale": 2.0, "rotation_deg": 90.0, "brain_dice": 0.1})) == 3


def test_map_atlas_adds_qc_warnings_from_cache(tmp_path: Path, fake_register: list[int]) -> None:
    """Los avisos de QC salen de `transforms.json`, también cuando se reutiliza la caché."""
    files = _study(tmp_path / "s", ("t1gd", "t1eg", "brain_mask", "gtv"))
    out = tmp_path / "out"
    assert map_atlas(files, out, tmp_path / "m").warnings == []
    meta_path = out / "mni" / atlas.CACHE_FILE
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["qc"] = {"det": 1.0, "rotation_deg": 45.0, "scale": 1.0, "brain_dice": 0.5}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    res = map_atlas(files, out, tmp_path / "m")
    assert len(fake_register) == 1
    assert res.warnings == registration_warnings(meta["qc"]) and len(res.warnings) == 2


def test_map_atlas_warnings(tmp_path: Path, fake_register: list[int]) -> None:
    files = _study(tmp_path / "s", ("t1gd", "flair"))
    res = map_atlas(files, tmp_path / "o1", tmp_path / "m")
    assert res.warnings == [WARN_NO_BRAIN, WARN_ONLY_T1GD]
    assert "excluido" not in res.registration

    files = _study(tmp_path / "s2", ("t1tse", "brain_mask", "gtv"))
    _write(files["gtv"], np.ones((10, 4, 4), np.uint8))
    res = map_atlas(files, tmp_path / "o2", tmp_path / "m")
    assert res.reference_sequence == "t1tse"
    assert res.warnings == [WARN_LARGE_GTV]


def test_map_atlas_without_t1_raises(tmp_path: Path, fake_register: list[int]) -> None:
    with pytest.raises(ValueError):
        map_atlas(_study(tmp_path / "s", ("flair", "gtv")), tmp_path / "o", tmp_path / "m")
    assert fake_register == []


# --- Real: 001/t0 ----------------------------------------------------------------------------------------


def _files(study_dir: Path) -> dict[str, Path]:
    return {p.name.split("_", 2)[2].removesuffix(".nii.gz"): p for p in study_dir.glob("*.nii.gz")}


@pytest.mark.slow
def test_real_mapping_on_data(tmp_path: Path) -> None:
    study = REPO_ROOT / "Data" / "001" / "t0"
    if not study.is_dir():
        pytest.skip("Sin Data/001/t0")
    pytest.importorskip("ants")
    files = _files(study)

    start = time.perf_counter()
    res = map_atlas(files, tmp_path, REPO_ROOT / "models")
    elapsed = time.perf_counter() - start

    ref = load_nifti(files["t1gd"])
    img = load_nifti(res.label_path)
    assert res.reference_sequence == "t1gd"
    assert np.allclose(affine_of(img), affine_of(ref)) and img.shape == ref.shape
    lab = np.asarray(img.dataobj)
    values = set(np.unique(lab).tolist()) - {0}
    assert values <= {v for v, _, _ in res.entries} and len(values) >= 30
    assert (tmp_path / "mni" / atlas.CACHE_FILE).is_file()

    # Etiqueta en el centroide del GTV o la más cercana a <= 15 mm
    gtv = np.asarray(load_nifti(files["gtv"]).dataobj) > 0.5
    centroid = np.round(np.argwhere(gtv).mean(axis=0)).astype(int)
    zooms = np.asarray(ref.header.get_zooms()[:3], dtype=float)
    reach = np.ceil(15 / zooms).astype(int)
    lo = np.maximum(centroid - reach, 0)
    hi = centroid + reach + 1
    win = lab[lo[0] : hi[0], lo[1] : hi[1], lo[2] : hi[2]]
    assert (win > 0).any()
    dist = np.asarray(distance_transform_edt(win == 0, sampling=zooms))
    c = centroid - lo
    assert float(dist[c[0], c[1], c[2]]) <= 15

    names = {v: (n, h) for v, n, h in res.entries}
    vals, counts = np.unique(lab[gtv], return_counts=True)
    top = sorted(((int(n), int(v)) for v, n in zip(vals, counts, strict=True) if v != 0), reverse=True)[:5]
    print(f"\nmap_atlas 001/t0: {elapsed:.1f} s · {len(values)} etiquetas · {res.registration} · {res.warnings}")
    for n, v in top:
        print(f"  {v:3d} {names[v][0]} ({names[v][1]}): {n} vóxeles GTV")


@pytest.mark.slow
def test_real_registration_is_reproducible(tmp_path: Path) -> None:
    """REG1: dos registros de 001/t0 desde cero dan transformaciones y atlas bit a bit iguales."""
    study = REPO_ROOT / "Data" / "001" / "t0"
    if not study.is_dir():
        pytest.skip("Sin Data/001/t0")
    files = _files(study)
    digests = []
    for run in ("a", "b"):
        res = map_atlas(files, tmp_path / run, REPO_ROOT / "models")
        mni = tmp_path / run / "mni"
        digests.append(
            [hashlib.sha256(p.read_bytes()).hexdigest() for p in (mni / "pat2mni_0GenericAffine.mat", res.label_path)]
        )
        qc = json.loads((mni / atlas.CACHE_FILE).read_text(encoding="utf-8"))["qc"]
        assert registration_warnings(qc) == []
    assert digests[0] == digests[1]
