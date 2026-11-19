"""Tests de la configuración del pipeline de fine-tuning (docs/PLAN_PIPELINE_FINETUNING.md §3, §5, §6, ticket FT0)."""

import copy
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from cerberus_training.config import (
    CHANNEL_ORDER,
    REPO_ROOT,
    ConfigError,
    TrainConfig,
    dump_config,
    load_config,
    resolve_config,
    write_resolved_config,
)

EXAMPLE = REPO_ROOT / "configs" / "training" / "gtv_binary.json"


def _example_data() -> dict[str, Any]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _mutated(tmp_path: Path, *keys: str, value: Any) -> Path:
    data = copy.deepcopy(_example_data())
    node = data
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value
    return _write(tmp_path, data)


def test_example_validates_with_plan_defaults() -> None:
    cfg = load_config(EXAMPLE)
    assert cfg.schema_version == 1
    assert cfg.channels.order == CHANNEL_ORDER == ("T1c", "T1", "T2", "FLAIR")
    assert cfg.channels.preferences["T1"] == ("t1eg", "t1tse")
    assert cfg.channels.t2star_policy == "disabled"
    assert (cfg.split.seed, cfg.split.train, cfg.split.val, cfg.split.test) == (42, 0.70, 0.15, 0.15)
    assert cfg.preprocess.spacing_mm == 1.0
    assert cfg.preprocess.patch_size == (96, 96, 96)
    assert (cfg.preprocess.batch_size, cfg.preprocess.grad_accum_steps) == (1, 4)
    assert cfg.preprocess.pos_neg_ratio == (1, 1)
    assert cfg.preprocess.num_workers == 0
    assert cfg.training.learning_rate == 1e-4 and cfg.training.weight_decay == 1e-5
    assert cfg.training.max_epochs == 100 and cfg.training.early_stopping_patience == 15
    assert cfg.training.threshold == 0.5 and cfg.training.loss == "dice_bce"
    assert cfg.paths.work_dir == Path("storage/training")


def test_defaults_match_example() -> None:
    """Los valores por defecto del esquema coinciden con el ejemplo (salvo device/amp, que son del hardware)."""
    data = _example_data()
    minimal = {k: data[k] for k in ("schema_version", "paths", "weights")}
    minimal["paths"] = {"data_root": data["paths"]["data_root"]}
    from_defaults = TrainConfig.model_validate(minimal)
    from_example = load_config(EXAMPLE)
    assert from_defaults.model_copy(update={"training": from_example.training}) == from_example


def test_missing_file_and_invalid_json(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="No se pudo leer"):
        load_config(tmp_path / "no_existe.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{no json", encoding="utf-8")
    with pytest.raises(ConfigError, match="no es JSON válido"):
        load_config(bad)
    lst = tmp_path / "list.json"
    lst.write_text("[]", encoding="utf-8")
    with pytest.raises(ConfigError, match="objeto JSON"):
        load_config(lst)


@pytest.mark.parametrize(
    "keys",
    [(), ("paths",), ("channels",), ("split",), ("preprocess",), ("weights",), ("training",), ("seeds",)],
)
def test_extra_fields_rejected_at_every_level(tmp_path: Path, keys: tuple[str, ...]) -> None:
    data = _example_data()
    node = data
    for key in keys:
        node = node[key]
    node["campo_inventado"] = 1
    with pytest.raises(ConfigError, match="campo_inventado"):
        load_config(_write(tmp_path, data))


def test_schema_version_required_and_checked(tmp_path: Path) -> None:
    data = _example_data()
    del data["schema_version"]
    with pytest.raises(ConfigError, match="schema_version"):
        load_config(_write(tmp_path, data))
    with pytest.raises(ConfigError, match="schema_version"):
        load_config(_mutated(tmp_path, "schema_version", value=2))


@pytest.mark.parametrize(
    ("train", "val", "test"),
    [(0.7, 0.2, 0.2), (0.5, 0.2, 0.2), (1.0, 0.0, 0.0), (0.8, 0.2, 0.0), (1.2, -0.1, -0.1)],
)
def test_split_ratios_must_sum_to_one_and_be_positive(tmp_path: Path, train: float, val: float, test: float) -> None:
    path = _mutated(tmp_path, "split", value={"seed": 42, "train": train, "val": val, "test": test})
    with pytest.raises(ConfigError, match="split"):
        load_config(path)


@pytest.mark.parametrize(
    "sha",
    ["", "abc", "g" * 64, "0" * 63, "0" * 65, "0" * 62 + "zz"],
)
def test_sha256_must_be_64_hex(tmp_path: Path, sha: str) -> None:
    with pytest.raises(ConfigError, match="sha256"):
        load_config(_mutated(tmp_path, "weights", "sha256", value=sha))


def test_sha256_is_normalized_and_required(tmp_path: Path) -> None:
    cfg = load_config(_mutated(tmp_path, "weights", "sha256", value="  " + "AB" * 32 + " "))
    assert cfg.weights.sha256 == "ab" * 32
    data = _example_data()
    del data["weights"]["sha256"]
    with pytest.raises(ConfigError, match="sha256"):
        load_config(_write(tmp_path, data))


@pytest.mark.parametrize(
    ("keys", "value"),
    [
        (("preprocess", "spacing_mm"), 0),
        (("preprocess", "spacing_mm"), -1.0),
        (("preprocess", "patch_size"), [96, 96, 0]),
        (("preprocess", "patch_size"), [96, 96]),
        (("preprocess", "patch_size"), [100, 96, 96]),  # no múltiplo de 8
        (("preprocess", "batch_size"), 0),
        (("preprocess", "grad_accum_steps"), -4),
        (("preprocess", "pos_neg_ratio"), [1, 0]),
        (("preprocess", "num_workers"), -1),
        (("preprocess", "cache_limit_gb"), 0),
        (("training", "learning_rate"), 0),
        (("training", "weight_decay"), -1e-5),
        (("training", "max_epochs"), 0),
        (("training", "early_stopping_patience"), 0),
        (("training", "threshold"), 1.0),
        (("training", "threshold"), 0.0),
        (("training", "device"), "tpu"),
        (("training", "freeze_modules"), ["a", "a"]),
        (("training", "freeze_modules"), [" "]),
    ],
)
def test_invalid_values_rejected(tmp_path: Path, keys: tuple[str, ...], value: Any) -> None:
    with pytest.raises(ConfigError, match=keys[-1]):
        load_config(_mutated(tmp_path, *keys, value=value))


def test_amp_requires_cuda(tmp_path: Path) -> None:
    data = _example_data()
    data["training"].update(device="cpu", amp=True)
    with pytest.raises(ConfigError, match="amp"):
        load_config(_write(tmp_path, data))
    data["training"].update(device="cpu", amp=False)
    assert load_config(_write(tmp_path, data)).training.device == "cpu"


@pytest.mark.parametrize(
    "order",
    [["T1", "T1c", "T2", "FLAIR"], ["T1c", "T1", "T2"], ["T1c", "T1", "T2", "FLAIR", "ADC"]],
)
def test_channel_order_is_fixed(tmp_path: Path, order: list[str]) -> None:
    with pytest.raises(ConfigError, match="canales"):
        load_config(_mutated(tmp_path, "channels", "order", value=order))


def test_t2star_never_substitutes_t2(tmp_path: Path) -> None:
    prefs = copy.deepcopy(_example_data()["channels"]["preferences"])
    prefs["T2"] = ["t2tse", "t2star"]
    with pytest.raises(ConfigError, match="T2\\*"):
        load_config(_mutated(tmp_path, "channels", "preferences", value=prefs))
    with pytest.raises(ConfigError, match="t2star_policy"):
        load_config(_mutated(tmp_path, "channels", "t2star_policy", value="substitute"))


def test_channel_preferences_validated(tmp_path: Path) -> None:
    prefs = copy.deepcopy(_example_data()["channels"]["preferences"])
    prefs["T1"] = ["t1tse", "t1eg"]  # el orden de preferencia importa: t1eg primero
    with pytest.raises(ConfigError, match="perfil estricto"):
        load_config(_mutated(tmp_path, "channels", "preferences", value=prefs))
    prefs["T1"] = ["../x"]
    with pytest.raises(ConfigError, match="desconocida"):
        load_config(_mutated(tmp_path, "channels", "preferences", value=prefs))
    del prefs["FLAIR"]
    with pytest.raises(ConfigError, match="exactamente"):
        load_config(_mutated(tmp_path, "channels", "preferences", value=prefs))


def test_error_message_lists_location_in_spanish(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_config(_mutated(tmp_path, "training", "max_epochs", value=0))
    message = str(exc_info.value)
    assert "Configuración inválida" in message and "training.max_epochs" in message


def test_resolve_makes_paths_absolute(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()
    cfg = load_config(EXAMPLE)
    resolved = resolve_config(cfg, tmp_path)
    assert resolved.paths.work_dir == tmp_path / "storage" / "training"
    assert resolved.weights.path == tmp_path / "models" / "brats_mri_segmentation" / "models" / "model.pt"
    assert resolved.paths.data_root.is_absolute()
    assert cfg.paths.work_dir == Path("storage/training")  # la original no cambia (inmutable)


def test_resolved_config_round_trip(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()
    cfg = load_config(EXAMPLE)
    out = write_resolved_config(cfg, tmp_path / "runs" / "r1" / "config.resolved.json", base_dir=tmp_path)
    again = load_config(out)
    assert again == resolve_config(cfg, tmp_path)
    assert dump_config(again) == out.read_text(encoding="utf-8")
    # Idempotente: resolver lo ya resuelto no cambia nada.
    assert resolve_config(again, tmp_path) == again


def test_write_resolved_never_overwrites(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()
    cfg = load_config(EXAMPLE)
    out = tmp_path / "config.resolved.json"
    write_resolved_config(cfg, out, base_dir=tmp_path)
    before = out.read_text(encoding="utf-8")
    with pytest.raises(ConfigError, match="No se sobrescribe"):
        write_resolved_config(cfg, out, base_dir=tmp_path)
    assert out.read_text(encoding="utf-8") == before
    assert [p.name for p in tmp_path.iterdir()] == ["config.resolved.json"]  # sin temporales huérfanos


def test_config_is_frozen() -> None:
    cfg = load_config(EXAMPLE)
    with pytest.raises(ValueError):
        cfg.training.max_epochs = 1  # type: ignore[misc]


def test_config_and_cli_import_without_torch_or_monai() -> None:
    """Importar config y CLI no debe cargar torch/MONAI (imports perezosos, sin GPU ni red)."""
    code = (
        "import sys\n"
        "import cerberus_training, cerberus_training.config, cerberus_training.device, cerberus_training.__main__\n"
        "heavy = sorted(m for m in sys.modules if m.split('.')[0] in {'torch', 'monai', 'nibabel', 'scipy'})\n"
        "assert not heavy, heavy\n"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("data_root", "work_dir"),
    [
        ("/datos/cfb", "/datos/cfb"),  # igual
        ("/datos/cfb", "/datos/cfb/trabajo"),  # work_dir dentro de data_root
        ("/datos/cfb/sub", "/datos/cfb"),  # work_dir contiene a data_root
        ("/datos/cfb", "/datos/otro/../cfb"),  # igual tras normalizar
        ("storage", "storage/training"),  # relativas contra la raíz del repo
        ("storage/training/datos", "storage/training"),
    ],
)
def test_work_dir_must_be_disjoint_from_data_root(tmp_path: Path, data_root: str, work_dir: str) -> None:
    data = _example_data()
    data["paths"] = {"data_root": data_root, "work_dir": work_dir}
    with pytest.raises(ConfigError, match="work_dir"):
        load_config(_write(tmp_path, data))


def test_disjoint_siblings_with_common_prefix_are_accepted(tmp_path: Path) -> None:
    data = _example_data()
    data["paths"] = {"data_root": "/datos/cfb", "work_dir": "/datos/cfb-trabajo"}  # prefijo de texto, no de ruta
    assert load_config(_write(tmp_path, data)).paths.work_dir == Path("/datos/cfb-trabajo")


def test_resolve_rechecks_disjointness_against_base_dir(tmp_path: Path) -> None:
    """Con otra `base_dir` dos rutas relativas pueden pasar a solaparse; `resolve_config` lo revalida."""
    cfg = load_config(EXAMPLE).model_copy(
        update={"paths": load_config(EXAMPLE).paths.model_copy(update={"data_root": Path("/datos/x")})}
    )
    ok = resolve_config(cfg, tmp_path)
    assert ok.paths.data_root == Path("/datos/x").resolve()
    overlapping = cfg.paths.model_copy(update={"data_root": Path("/datos/x"), "work_dir": Path("/datos/x/w")})
    with pytest.raises(ConfigError, match="work_dir"):
        resolve_config(cfg.model_copy(update={"paths": overlapping}), tmp_path)


@pytest.mark.parametrize("keys", [("paths", "data_root"), ("paths", "work_dir"), ("weights", "path")])
@pytest.mark.parametrize("value", ["", "."])
def test_empty_or_dot_paths_rejected(tmp_path: Path, keys: tuple[str, str], value: str) -> None:
    with pytest.raises(ConfigError, match=keys[-1]):
        load_config(_mutated(tmp_path, *keys, value=value))


@pytest.mark.parametrize(
    "keys", [("split", "seed"), ("seeds", "training"), ("seeds", "augmentation"), ("seeds", "head_init")]
)
@pytest.mark.parametrize("value", [-1, 2**32, 2**64])
def test_seed_range(tmp_path: Path, keys: tuple[str, str], value: int) -> None:
    with pytest.raises(ConfigError, match=keys[-1]):
        load_config(_mutated(tmp_path, *keys, value=value))


@pytest.mark.parametrize("value", [0, 2**32 - 1])
def test_seed_range_bounds_accepted(tmp_path: Path, value: int) -> None:
    assert load_config(_mutated(tmp_path, "split", "seed", value=value)).split.seed == value


@pytest.mark.parametrize(
    ("keys", "value"),
    [
        (("preprocess", "batch_size"), True),
        (("preprocess", "batch_size"), "1"),
        (("training", "learning_rate"), "1e-4"),
        (("training", "amp"), "yes"),
        (("training", "amp"), 1),
        (("preprocess", "patch_size"), [96.0, 96.0, 96.0]),
        (("preprocess", "cache_enabled"), "true"),
        (("split", "seed"), True),
        (("split", "seed"), 42.0),
        (("seeds", "deterministic"), "true"),
        (("schema_version"), True),
        (("paths", "work_dir"), 5),
    ],
)
def test_strict_json_rejects_coercions(tmp_path: Path, keys: tuple[str, ...] | str, value: Any) -> None:
    path_keys = (keys,) if isinstance(keys, str) else keys
    with pytest.raises(ConfigError, match=path_keys[-1]):
        load_config(_mutated(tmp_path, *path_keys, value=value))


def test_strict_json_still_accepts_lists_as_tuples_and_strings_as_paths() -> None:
    cfg = load_config(EXAMPLE)
    assert isinstance(cfg.preprocess.patch_size, tuple) and isinstance(cfg.paths.data_root, Path)
    assert isinstance(cfg.channels.preferences["T1"], tuple) and isinstance(cfg.training.freeze_modules, tuple)


def test_non_utf8_file_is_config_error(tmp_path: Path) -> None:
    bad = tmp_path / "latin1.json"
    bad.write_bytes('{"schema_version": 1, "nota": "añadido"}'.encode("latin-1"))
    with pytest.raises(ConfigError, match="UTF-8"):
        load_config(bad)


def test_cli_non_utf8_exits_two_without_traceback(tmp_path: Path) -> None:
    bad = tmp_path / "latin1.json"
    bad.write_bytes(b"\xff\xfe{")
    result = subprocess.run(
        [sys.executable, "-m", "cerberus_training", "validate", "--config", str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2 and "Traceback" not in result.stderr and "UTF-8" in result.stderr


def test_write_resolved_wraps_os_errors(tmp_path: Path) -> None:
    cfg = load_config(EXAMPLE)
    blocker = tmp_path / "es_un_archivo"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(ConfigError, match="No se pudo crear"):
        write_resolved_config(cfg, blocker / "config.resolved.json", base_dir=tmp_path)
    if os.name == "posix" and os.geteuid() != 0:
        locked = tmp_path / "solo_lectura"
        locked.mkdir()
        locked.chmod(0o500)
        try:
            with pytest.raises(ConfigError, match="No se pudo crear"):
                write_resolved_config(cfg, locked / "config.resolved.json", base_dir=tmp_path)
        finally:
            locked.chmod(0o700)


@pytest.mark.skipif(os.name != "posix", reason="permisos POSIX")
def test_write_resolved_permissions_are_0644(tmp_path: Path) -> None:
    previous = os.umask(0o022)
    try:
        out = write_resolved_config(load_config(EXAMPLE), tmp_path / "c.json", base_dir=tmp_path)
    finally:
        os.umask(previous)
    assert stat.S_IMODE(out.stat().st_mode) == 0o644


def test_resolved_paths_are_normalized(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()
    data = _example_data()
    data["paths"] = {"data_root": "/datos/cfb/../cfb", "work_dir": "storage/./training/../training"}
    resolved = resolve_config(load_config(_write(tmp_path, data)), tmp_path)
    assert resolved.paths.data_root == Path("/datos/cfb").resolve()
    assert resolved.paths.work_dir == tmp_path / "storage" / "training"
