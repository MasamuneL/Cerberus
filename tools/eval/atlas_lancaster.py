"""Mide el efecto de Lancaster con el mismo registro REG1 en cada estudio.

Lee los mapas y reportes ATLAS1 de --results-dir. Reproyecta el atlas sin
Lancaster usando los mni/ de esos resultados. Si se indica --before-results-dir,
compara además con los reportes históricos previos a REG1 y ATLAS1.

La comparación usa recuentos, categorías y solapes definidos por el GTV.
El cálculo sin Lancaster omite WT y la salida excluye las métricas WT del
reporte con Lancaster, donde pueden existir si hay segmentación MONAI.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

import ants
import nibabel as nib
import numpy as np

from cerberus_api import areas, atlas, catalog
from cerberus_api.config import Settings
from cerberus_api.nifti import load_nifti
from cerberus_api.schemas import AffectedArea, AreasResult, Hemisphere


def warp_without_lancaster(
    split_path: Path, study_files: dict[str, Path], ref_path: Path, inverse: list[str], out_path: Path
) -> None:
    """Muestrea el atlas directamente desde MNI, como hacía el backend antes de ATLAS1."""
    ref_img = load_nifti(ref_path)
    warped = ants.apply_transforms(
        fixed=ants.image_read(str(ref_path)),
        moving=ants.image_read(str(split_path)),
        transformlist=inverse,
        whichtoinvert=atlas.which_to_invert(inverse),
        interpolator="genericLabel",
    )
    labels = np.rint(warped.numpy()).astype(np.uint8)
    if "brain_mask" in study_files:
        labels[~atlas._mask_on(load_nifti(study_files["brain_mask"]), ref_img)] = 0
    header = ref_img.header.copy()
    header.set_data_dtype(np.uint8)
    header.set_slope_inter(1, 0)
    nib.save(nib.Nifti1Image(labels, ref_img.affine, header), out_path)


def centroids(labels: np.ndarray) -> dict[int, np.ndarray]:
    # Acumula las sumas de coordenadas por etiqueta en una pasada por el mapa.
    indices = np.nonzero(labels)
    values = labels[indices]
    counts = np.bincount(values)
    sums = np.array([np.bincount(values, weights=axis) for axis in indices])
    return {int(val): sums[:, val] / counts[val] for val in np.flatnonzero(counts)}


def centroid_shifts(raw_path: Path, corrected_path: Path, entries: list[tuple[int, str, Hemisphere]]) -> dict[str, Any]:
    """Mide distancias entre centroides presentes en ambos mapas, en mm del paciente."""
    raw_img = load_nifti(raw_path)
    corrected_img = load_nifti(corrected_path)
    aff = atlas.affine_of(raw_img)
    if raw_img.shape != corrected_img.shape or not np.allclose(aff, atlas.affine_of(corrected_img), atol=1e-5):
        raise ValueError("Los mapas comparados deben compartir la geometría de referencia")
    raw = centroids(np.asarray(raw_img.dataobj))
    corrected = centroids(np.asarray(corrected_img.dataobj))
    shifts = [
        {
            "label": val,
            "name": name,
            "hemisphere": hemi,
            "shift_mm": float(np.linalg.norm(aff[:3, :3] @ (corrected[val] - raw[val]))),
        }
        for val, name, hemi in entries
        if val in raw and val in corrected
    ]

    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        values = [item["shift_mm"] for item in items]
        return {
            "n": len(values),
            "mean_mm": float(np.mean(values)) if values else None,
            "std_mm": float(np.std(values, ddof=1)) if len(values) > 1 else None,
            "median_mm": float(np.median(values)) if values else None,
            "min_mm": min(values, default=None),
            "max_mm": max(values, default=None),
            "top5": sorted(items, key=lambda item: item["shift_mm"], reverse=True)[:5],
        }

    return {
        "ba": summarize([item for item in shifts if item["name"].startswith("Brodmann area")]),
        "all": summarize(shifts),
    }


def area_summary(report: list[AffectedArea]) -> dict[str, Any]:
    affected = sum(area.overlap_gtv_cm3 > 0 for area in report)
    return {
        "affected": affected,
        "nearby": len(report) - affected,
        "total": len(report),
        "areas": [
            {
                "label": area.label,
                "name": area.name,
                "name_es": area.name_es,
                "hemisphere": area.hemisphere,
                "eloquent": area.eloquent,
                "overlap_gtv_cm3": area.overlap_gtv_cm3,
                "overlap_gtv_pct": area.overlap_gtv_pct,
                "distance_mm": area.distance_mm,
                "status": "afectada" if area.overlap_gtv_cm3 > 0 else "cercana",
            }
            for area in report
        ],
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    old = {area["label"]: area for area in before["areas"]}
    new = {area["label"]: area for area in after["areas"]}
    return {
        "appeared": [new[key] for key in sorted(new.keys() - old.keys())],
        "disappeared": [old[key] for key in sorted(old.keys() - new.keys())],
        "status_changed": [
            {"before": old[key], "after": new[key]}
            for key in sorted(old.keys() & new.keys())
            if old[key]["status"] != new[key]["status"]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True, help="Directorio de estudios NIfTI")
    parser.add_argument("--models-dir", type=Path, help="Directorio de modelos (por defecto, el de Cerberus)")
    parser.add_argument("--results-dir", type=Path, required=True, help="Resultados ATLAS1 en modo full")
    parser.add_argument("--before-results-dir", type=Path, help="Resultados históricos previos a REG1")
    parser.add_argument("--out", type=Path, required=True, help="Archivo JSON de salida")
    args = parser.parse_args()

    studies = catalog._scan(args.data_dir, "*/t*/*.nii.gz")
    if not studies:
        parser.error(f"No hay estudios en {args.data_dir}")

    models_dir = args.models_dir if args.models_dir is not None else Settings().models_dir
    atlas_img, labels = atlas.fetch_atlas(models_dir)
    split_img, entries = atlas.split_hemispheres(atlas_img, labels)
    results = []
    with tempfile.TemporaryDirectory(prefix="cerberus_atlas_eval_") as tmp:
        split_path = Path(tmp) / "atlas_split.nii.gz"
        raw_path = Path(tmp) / "brodmann_raw.nii.gz"
        nib.save(split_img, split_path)

        for (patient, timepoint), files in sorted(studies.items()):
            if "gtv" not in files or not set(atlas.MOVING_PRIORITY).intersection(files):
                continue
            study = f"{patient}/{timepoint}"
            study_dir = args.results_dir / patient / timepoint
            reference, moving = atlas.select_sequences(files)
            inverse = atlas._load_cached(study_dir / "mni", atlas._cache_key(files, moving))
            if inverse is None:
                raise ValueError(f"{study}: falta el registro full de REG1 para estas entradas")
            corrected_path = study_dir / "brodmann.nii.gz"
            report = AreasResult.model_validate_json((study_dir / areas.AREAS_JSON).read_bytes())
            map_name = load_nifti(corrected_path).header["descrip"].item()
            if report.atlas != atlas.ATLAS_NAME or map_name != atlas.ATLAS_NAME.encode("ascii"):
                raise ValueError(f"{study}: el mapa y el reporte deben haberse generado con ATLAS1")
            if report.reference_sequence != reference or report.margin_mm != areas.MARGIN_MM:
                raise ValueError(f"{study}: la referencia y el margen del reporte deben coincidir con el control")

            warp_without_lancaster(split_path, files, files[reference], inverse, raw_path)
            raw_areas, _ = areas.compute_area_report(raw_path, entries, files["gtv"], None)
            raw = area_summary(raw_areas)
            corrected = area_summary(report.areas)

            historical = None
            if args.before_results_dir is not None:
                historical_path = args.before_results_dir / patient / timepoint / areas.AREAS_JSON
                if historical_path.is_file():
                    historical_report = AreasResult.model_validate_json(historical_path.read_bytes())
                    historical = area_summary(historical_report.areas)

            results.append(
                {
                    "study": study,
                    "reference_sequence": reference,
                    "moving_sequence": moving,
                    "before": historical,
                    "reg1_without_lancaster": raw,
                    "reg1_with_lancaster": corrected,
                    "reg1_changes": compare(historical, raw) if historical is not None else None,
                    "lancaster_changes": compare(raw, corrected),
                    "total_changes": compare(historical, corrected) if historical is not None else None,
                    "centroid_shifts": centroid_shifts(raw_path, corrected_path, entries),
                }
            )
            print(f"{study}: {raw['total']} áreas sin Lancaster, {corrected['total']} con Lancaster", flush=True)

    if not results:
        parser.error("No hay estudios con GTV y una secuencia T1")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"margin_mm": areas.MARGIN_MM, "studies": results}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
