"""Partición determinista e inmutable por paciente (docs/PLAN_PIPELINE_FINETUNING.md §4 puntos 4-6, ticket FT1).

Algoritmo (versión `largest_remainder_v1`, registrada en `splits.json`):

1. Se toman solo los estudios elegibles del inventario y se agrupan por paciente (todos sus tiempos juntos).
2. Duplicados exactos: los pacientes que comparten el SHA-256 de algún canal de imagen se fusionan en un mismo
   grupo (union-find), de modo que un duplicado nunca cruza particiones.
3. Cuotas en pacientes por **resto mayor** (Hamilton): la cuota exacta `p·N` se redondea antes a 9 decimales
   (`round(p·N, 9)`, para que el error de coma flotante no convierta 0.15·20 = 3 en 2.9999999999999996); luego
   `floor` por partición y las unidades sobrantes a los mayores restos; empate → orden fijo train, val, test.
   Si alguna partición queda en 0, recibe 1 paciente de la mayor (empate → la primera).
   Hacen falta al menos 3 pacientes y 3 grupos.
4. Orden de los grupos: SHA-256 de `"<semilla>:<grupo>"` (independiente de la implementación de `random`).
   Cada grupo va a la partición con mayor déficit respecto a su cuota (empate → train, val, test); si quedan
   tantos grupos como particiones vacías, se reservan para ellas. Con grupos de tamaño 1 las cuotas son exactas;
   con grupos fusionados los tamaños reales pueden desviarse: si alguna partición se aleja de su cuota más de
   `max(1, ceil(0.10·N))` pacientes, el split se escribe igualmente pero con un aviso explícito en `warnings`
   (la CLI lo imprime). Nunca se reequilibra rompiendo un grupo de duplicados.

`splits.json` es inmutable: si ya existe y coincide con lo que se calcularía, se reutiliza; si difiere (otro
inventario, semilla o proporciones), es un error. Nunca se redistribuye. El informe de estratos t0/seguimiento y
de canales es solo descriptivo: no se usa para elegir la partición ni datos clínicos.
"""

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from cerberus_training.config import CHANNEL_ORDER, SplitConfig
from cerberus_training.manifest import duplicate_groups, publish_exclusive

SPLITS_SCHEMA_VERSION = 1
ROUNDING = "largest_remainder_v1"
PARTITIONS: tuple[str, str, str] = ("train", "val", "test")
MIN_PATIENTS = 3
# Desviación máxima tolerada sin aviso entre pacientes asignados y cuota: max(1, ceil(fracción·N)).
DEVIATION_WARN_FRACTION = 0.10


class SplitError(ValueError):
    """Partición imposible o incompatible con una existente; mensaje en español."""


def canonical_hash(payload: Any) -> str:
    """SHA-256 del JSON canónico (claves ordenadas, sin espacios, UTF-8)."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def eligible_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Estudios elegibles ordenados por `study_id`."""
    return sorted((r for r in records if r.get("eligible") is True), key=lambda r: r["study_id"])


def largest_remainder(n: int, ratios: tuple[float, float, float]) -> list[int]:
    """Cuotas enteras que suman `n` por resto mayor, con mínimo 1 por partición (requiere `n >= 3`)."""
    if n < len(ratios):
        raise SplitError(f"Se necesitan al menos {len(ratios)} pacientes para {len(ratios)} particiones; hay {n}")
    # Cuota redondeada a 9 decimales: absorbe el error de coma flotante (0.15·20 → 2.9999999999999996 → 3.0).
    quotas = [round(r * n, 9) for r in ratios]
    counts = [math.floor(q) for q in quotas]
    order = sorted(range(len(ratios)), key=lambda i: (-(quotas[i] - counts[i]), i))
    for i in order[: n - sum(counts)]:
        counts[i] += 1
    for i in range(len(counts)):
        while counts[i] == 0:
            donor = max(range(len(counts)), key=lambda j: (counts[j], -j))
            counts[donor] -= 1
            counts[i] += 1
    return counts


class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # la raíz es el menor ID: grupos estables sin importar el orden de las uniones
            lo, hi = sorted((ra, rb))
            self.parent[hi] = lo


def _study_owner(records: list[dict[str, Any]]) -> dict[str, str]:
    return {r["study_id"]: r["patient"] for r in records}


def patient_groups(eligible: list[dict[str, Any]]) -> list[list[str]]:
    """Grupos de pacientes inseparables: cada paciente, fusionado con los que comparten hash de un canal."""
    patients = sorted({r["patient"] for r in eligible})
    owner = _study_owner(eligible)
    uf = _UnionFind(patients)
    for dup in duplicate_groups(eligible):
        owners = sorted({owner[sid] for sid in dup["studies"]})
        for other in owners[1:]:
            uf.union(owners[0], other)
    groups: dict[str, list[str]] = {}
    for p in patients:
        groups.setdefault(uf.find(p), []).append(p)
    return sorted(groups.values())


def _order_key(seed: int, group: list[str]) -> str:
    return hashlib.sha256(f"{seed}:{','.join(group)}".encode()).hexdigest()


def assign_groups(groups: list[list[str]], targets: list[int], seed: int) -> list[list[str]]:
    """Reparte los grupos (orden pseudoaleatorio con semilla) por déficit de cuota, sin dejar particiones vacías."""
    if len(groups) < len(targets):
        raise SplitError(
            f"Solo hay {len(groups)} grupo(s) de pacientes independientes tras fusionar duplicados; "
            f"se necesitan al menos {len(targets)}"
        )
    ordered = sorted(groups, key=lambda g: (_order_key(seed, g), g))
    assigned: list[list[str]] = [[] for _ in targets]
    for index, group in enumerate(ordered):
        empty = [i for i, part in enumerate(assigned) if not part]
        if empty and len(ordered) - index <= len(empty):
            choice = empty[0]
        else:
            choice = max(range(len(targets)), key=lambda i: (targets[i] - len(assigned[i]), -i))
        assigned[choice].extend(group)
    return [sorted(part) for part in assigned]


def _partition_report(studies: list[dict[str, Any]]) -> dict[str, Any]:
    """Descriptivo: estratos t0/seguimiento, secuencia elegida por canal, máscara cerebral y GTV vacías."""
    channels: dict[str, Counter[str]] = {c: Counter() for c in CHANNEL_ORDER}
    for r in studies:
        for channel, seq in r["selected_sequences"].items():
            channels[channel][str(seq)] += 1
    return {
        "patients": len({r["patient"] for r in studies}),
        "studies": len(studies),
        "strata": dict(sorted(Counter(r["stratum"] for r in studies).items())),
        "channels": {c: dict(sorted(v.items())) for c, v in channels.items()},
        "with_brain_mask": sum(1 for r in studies if r.get("brain_mask")),
        "empty_labels": sum(1 for r in studies if (r.get("label") or {}).get("empty")),
    }


def build_splits(records: list[dict[str, Any]], config: SplitConfig) -> dict[str, Any]:
    """Calcula el contenido de `splits.json` (incluye `split_sha256`) a partir del inventario."""
    eligible = eligible_records(records)
    patients = sorted({r["patient"] for r in eligible})
    if len(patients) < MIN_PATIENTS:
        raise SplitError(
            f"Hay {len(patients)} paciente(s) con estudios elegibles; se necesitan al menos {MIN_PATIENTS}"
        )
    ratios = (config.train, config.val, config.test)
    targets = largest_remainder(len(patients), ratios)
    groups = patient_groups(eligible)
    parts = assign_groups(groups, targets, config.seed)

    partition_of = {p: name for name, members in zip(PARTITIONS, parts, strict=True) for p in members}
    partitions: dict[str, Any] = {}
    report: dict[str, Any] = {}
    for name, members in zip(PARTITIONS, parts, strict=True):
        studies = [r for r in eligible if partition_of[r["patient"]] == name]
        partitions[name] = {"patients": members, "studies": [r["study_id"] for r in studies]}
        report[name] = _partition_report(studies)

    owner = _study_owner(eligible)
    duplicates: list[dict[str, Any]] = []
    for dup in duplicate_groups(eligible):
        names = sorted({partition_of[owner[sid]] for sid in dup["studies"]})
        if len(names) != 1:  # invariante del union-find; nunca debería ocurrir
            raise SplitError(f"Un duplicado cruzó particiones: {dup['studies']}")
        duplicates.append({**dup, "partition": names[0]})

    tolerance = max(1, math.ceil(DEVIATION_WARN_FRACTION * len(patients)))
    warnings = [
        f"{name}: {len(members)} pacientes frente a una cuota de {target} (desviación mayor que {tolerance}) "
        "por grupos de duplicados fusionados"
        for name, members, target in zip(PARTITIONS, parts, targets, strict=True)
        if abs(len(members) - target) > tolerance
    ]

    payload: dict[str, Any] = {
        "schema_version": SPLITS_SCHEMA_VERSION,
        "group_by": config.group_by,
        "seed": config.seed,
        "ratios": dict(zip(PARTITIONS, ratios, strict=True)),
        "rounding": ROUNDING,
        "target_patients": dict(zip(PARTITIONS, targets, strict=True)),
        "eligible_records_sha256": canonical_hash(eligible),
        "eligible_studies": len(eligible),
        "pretraining_overlap": config.pretraining_overlap,
        "merged_groups": [g for g in groups if len(g) > 1],
        "duplicates": duplicates,
        "partitions": partitions,
        "report": report,
        "warnings": warnings,
    }
    payload["split_sha256"] = canonical_hash(payload)
    return payload


def load_splits(path: Path) -> dict[str, Any]:
    """Lee `splits.json` y verifica su propio hash (detecta ediciones manuales)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SplitError(f"No se pudo leer {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != SPLITS_SCHEMA_VERSION:
        raise SplitError(f"{path}: esquema no soportado (se espera {SPLITS_SCHEMA_VERSION})")
    body = {k: v for k, v in data.items() if k != "split_sha256"}
    if data.get("split_sha256") != canonical_hash(body):
        raise SplitError(f"{path}: el hash del split no coincide con su contenido (¿editado a mano?)")
    return data


def _compare_existing(payload: dict[str, Any], output: Path) -> bool:
    existing = load_splits(output)
    if existing["split_sha256"] == payload["split_sha256"]:
        return True
    reasons = [
        key
        for key in ("eligible_records_sha256", "seed", "ratios", "rounding", "pretraining_overlap")
        if existing.get(key) != payload.get(key)
    ]
    raise SplitError(
        f"Ya existe {output} con otra partición (difiere en: {', '.join(reasons) or 'contenido'}). "
        "Un split no se redistribuye: use otro work_dir o borre el archivo a conciencia."
    )


def write_or_reuse_splits(payload: dict[str, Any], output: Path) -> bool:
    """Publica `splits.json` (solo lectura, 0444) si no existe; devuelve `True` si se reutilizó uno idéntico.

    La publicación es exclusiva (temporal + `os.link`): si otro proceso la gana (`FileExistsError`), se recarga y
    se compara. Si el existente difiere, lanza `SplitError`: un split no se redistribuye nunca.
    """
    if output.exists():
        return _compare_existing(payload, output)
    try:
        publish_exclusive(output, json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    except FileExistsError:
        return _compare_existing(payload, output)
    return False


def format_splits(payload: dict[str, Any]) -> str:
    """Resumen legible del split para la CLI."""
    lines = [
        f"Split {payload['split_sha256'][:12]} (semilla {payload['seed']}, {payload['rounding']}); "
        f"registros elegibles {payload['eligible_records_sha256'][:12]}; "
        f"solapamiento con preentrenamiento: {payload['pretraining_overlap']}",
    ]
    for name in PARTITIONS:
        rep = payload["report"][name]
        lines.append(
            f"  {name}: {rep['patients']} pacientes (objetivo {payload['target_patients'][name]}), "
            f"{rep['studies']} estudios, estratos {rep['strata']}, canales {rep['channels']}"
        )
    if payload["merged_groups"]:
        lines.append(f"  grupos fusionados por duplicados: {payload['merged_groups']}")
    lines.extend(f"  AVISO: {w}" for w in payload["warnings"])
    return "\n".join(lines)
