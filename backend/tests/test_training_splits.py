"""Tests de la partición por paciente FT1 (docs/PLAN_PIPELINE_FINETUNING.md §4 puntos 4-6).

Usan registros de inventario sintéticos (diccionarios), sin NIfTI, red ni `Data/001`.
"""

import hashlib
import json
import stat
from pathlib import Path
from typing import Any

import pytest

import cerberus_training.splits as splits_mod
from cerberus_training.config import SplitConfig
from cerberus_training.splits import (
    PARTITIONS,
    SplitError,
    build_splits,
    largest_remainder,
    load_splits,
    write_or_reuse_splits,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def record(patient: str, timepoint: str = "t0", eligible: bool = True, shared: str | None = None) -> dict[str, Any]:
    """Registro mínimo con los campos que usa `splits`; `shared` fuerza el hash del FLAIR (duplicado)."""
    sid = f"{patient}_{timepoint}"
    channels = {
        c: {"sequence": s, "sha256": _sha(f"{sid}{c}")}
        for c, s in (("T1c", "t1gd"), ("T1", "t1eg"), ("T2", "t2tse"), ("FLAIR", "flair"))
    }
    if shared is not None:
        channels["FLAIR"]["sha256"] = _sha(shared)
    return {
        "schema_version": 1,
        "study_id": sid,
        "patient": patient,
        "timepoint": timepoint,
        "stratum": "baseline" if timepoint == "t0" else "follow_up",
        "channels": channels,
        "selected_sequences": {c: v["sequence"] for c, v in channels.items()},
        "label": {"empty": False},
        "brain_mask": None,
        "eligible": eligible,
    }


def cohort(n: int, follow_up_every: int = 3) -> list[dict[str, Any]]:
    records = []
    for i in range(1, n + 1):
        records.append(record(f"{i:03d}"))
        if i % follow_up_every == 0:
            records.append(record(f"{i:03d}", "t1"))
    return records


def partition_of(payload: dict[str, Any]) -> dict[str, str]:
    return {p: name for name in PARTITIONS for p in payload["partitions"][name]["patients"]}


@pytest.mark.parametrize(
    ("n", "expected"),
    [(3, [1, 1, 1]), (4, [2, 1, 1]), (10, [7, 2, 1]), (20, [14, 3, 3]), (100, [70, 15, 15]), (7, [5, 1, 1])],
)
def test_largest_remainder(n: int, expected: list[int]) -> None:
    assert largest_remainder(n, (0.7, 0.15, 0.15)) == expected


def test_largest_remainder_needs_three() -> None:
    with pytest.raises(SplitError):
        largest_remainder(2, (0.7, 0.15, 0.15))


def test_split_is_deterministic_and_seed_dependent() -> None:
    records = cohort(30)
    a, b = build_splits(records, SplitConfig()), build_splits(list(reversed(records)), SplitConfig())
    assert a == b and a["split_sha256"] == b["split_sha256"]
    other = build_splits(records, SplitConfig(seed=7))
    assert other["partitions"] != a["partitions"]


@pytest.mark.parametrize("n", range(3, 41))
def test_partitions_non_empty_disjoint_and_complete(n: int) -> None:
    payload = build_splits(cohort(n), SplitConfig())
    members = [payload["partitions"][name]["patients"] for name in PARTITIONS]
    assert all(members)
    flat = [p for part in members for p in part]
    assert len(flat) == len(set(flat)) == n
    assert [len(m) for m in members] == largest_remainder(n, (0.7, 0.15, 0.15))


def test_all_timepoints_of_a_patient_share_partition() -> None:
    payload = build_splits(cohort(20, follow_up_every=1), SplitConfig())
    where = partition_of(payload)
    for name in PARTITIONS:
        for sid in payload["partitions"][name]["studies"]:
            assert where[sid.split("_")[0]] == name
    total = sum(payload["report"][n]["strata"].get("follow_up", 0) for n in PARTITIONS)
    assert total == 20


def test_ineligible_studies_ignored() -> None:
    records = [*cohort(5), record("006", eligible=False), record("001", "t5", eligible=False)]
    payload = build_splits(records, SplitConfig())
    assert "006" not in partition_of(payload)
    assert all("001_t5" not in payload["partitions"][n]["studies"] for n in PARTITIONS)
    assert payload["eligible_studies"] == 6


def test_duplicates_never_cross_partitions() -> None:
    records = cohort(20)
    # 003 y 017 comparten un FLAIR idéntico; 017 y 020 otro: los tres quedan juntos (union-find transitivo).
    records = [r for r in records if r["patient"] not in ("003", "017", "020")]
    records += [record("003", shared="a"), record("017", shared="a"), record("020", "t0", shared="b")]
    records += [record("017", "t1", shared="b")]
    for seed in range(15):
        payload = build_splits(records, SplitConfig(seed=seed))
        where = partition_of(payload)
        assert where["003"] == where["017"] == where["020"]
        assert payload["merged_groups"] == [["003", "017", "020"]]
        assert len(payload["duplicates"]) == 2
        assert {d["partition"] for d in payload["duplicates"]} == {where["003"]}
        assert all(payload["partitions"][n]["patients"] for n in PARTITIONS)


def test_too_few_patients_fails() -> None:
    with pytest.raises(SplitError, match="al menos 3"):
        build_splits([record("001"), record("001", "t1"), record("002")], SplitConfig())
    with pytest.raises(SplitError, match="al menos 3"):
        build_splits([*cohort(2), record("003", eligible=False)], SplitConfig())


def test_too_few_independent_groups_fails() -> None:
    records = [record("001", shared="x"), record("002", shared="x"), record("003")]
    with pytest.raises(SplitError, match="grupo"):
        build_splits(records, SplitConfig())


def test_pretraining_overlap_recorded() -> None:
    assert build_splits(cohort(5), SplitConfig())["pretraining_overlap"] == "unknown"
    assert build_splits(cohort(5), SplitConfig(pretraining_overlap="verified"))["pretraining_overlap"] == "verified"


def test_report_is_descriptive() -> None:
    payload = build_splits(cohort(10), SplitConfig())
    rep = payload["report"]
    assert sum(rep[n]["patients"] for n in PARTITIONS) == 10
    assert sum(rep[n]["studies"] for n in PARTITIONS) == 13
    assert all(rep[n]["channels"]["T1"] == {"t1eg": rep[n]["studies"]} for n in PARTITIONS)


def test_existing_identical_is_reused(tmp_path: Path) -> None:
    out = tmp_path / "splits.json"
    payload = build_splits(cohort(10), SplitConfig())
    assert write_or_reuse_splits(payload, out) is False
    assert stat.S_IMODE(out.stat().st_mode) == 0o444  # inmutable
    before = out.read_bytes()
    assert write_or_reuse_splits(build_splits(cohort(10), SplitConfig()), out) is True
    assert out.read_bytes() == before
    assert load_splits(out)["split_sha256"] == payload["split_sha256"]


@pytest.mark.parametrize(
    ("records", "config", "reason"),
    [
        (cohort(11), SplitConfig(), "eligible_records_sha256"),
        (cohort(10), SplitConfig(seed=1), "seed"),
        (cohort(10), SplitConfig(train=0.6, val=0.2, test=0.2), "ratios"),
    ],
)
def test_existing_different_fails(
    tmp_path: Path, records: list[dict[str, Any]], config: SplitConfig, reason: str
) -> None:
    out = tmp_path / "splits.json"
    write_or_reuse_splits(build_splits(cohort(10), SplitConfig()), out)
    before = out.read_bytes()
    with pytest.raises(SplitError, match=reason):
        write_or_reuse_splits(build_splits(records, config), out)
    assert out.read_bytes() == before


def test_tampered_split_detected(tmp_path: Path) -> None:
    out = tmp_path / "splits.json"
    payload = build_splits(cohort(10), SplitConfig())
    write_or_reuse_splits(payload, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    data["partitions"]["test"]["patients"].append("999")
    out.chmod(0o644)
    out.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SplitError, match="editado"):
        write_or_reuse_splits(payload, out)


def test_large_merged_group_keeps_duplicates_together_and_warns() -> None:
    # 17 de 20 pacientes comparten un FLAIR idéntico: un grupo de 17 no cabe en la cuota de train (14).
    records = [record(f"{i:03d}", shared="mismo") for i in range(1, 18)] + [record(f"{i:03d}") for i in (18, 19, 20)]
    for seed in range(10):
        payload = build_splits(records, SplitConfig(seed=seed))
        where = partition_of(payload)
        assert len({where[f"{i:03d}"] for i in range(1, 18)}) == 1
        assert all(payload["partitions"][n]["patients"] for n in PARTITIONS)
        assert payload["warnings"] and "cuota" in payload["warnings"][0]


def test_moderate_merged_group_warns_only_beyond_tolerance() -> None:
    # 15 de 20 duplicados: la desviación depende del orden; el aviso aparece si y solo si supera max(1, ceil(0.1·N)).
    records = [record(f"{i:03d}", shared="mismo") for i in range(1, 16)] + [record(f"{i:03d}") for i in range(16, 21)]
    for seed in range(20):
        payload = build_splits(records, SplitConfig(seed=seed))
        where = partition_of(payload)
        assert len({where[f"{i:03d}"] for i in range(1, 16)}) == 1
        assert all(payload["partitions"][n]["patients"] for n in PARTITIONS)
        worst = max(abs(payload["report"][n]["patients"] - payload["target_patients"][n]) for n in PARTITIONS)
        assert bool(payload["warnings"]) == (worst > 2)


def test_concurrent_publication_is_compared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Si otro proceso publica antes (`FileExistsError`), se recarga y compara en vez de sobrescribir."""
    out = tmp_path / "splits.json"
    winner = build_splits(cohort(10), SplitConfig())
    real = splits_mod.publish_exclusive

    def racing(path: Path, text: str, mode: int = 0o444) -> None:
        real(path, json.dumps(winner), mode)  # el otro proceso gana la carrera…
        raise FileExistsError(path)  # …y nuestra publicación exclusiva falla

    monkeypatch.setattr(splits_mod, "publish_exclusive", racing)
    assert write_or_reuse_splits(winner, out) is True
    out.chmod(0o644)
    out.unlink()
    with pytest.raises(SplitError, match="seed"):
        write_or_reuse_splits(build_splits(cohort(10), SplitConfig(seed=3)), out)
