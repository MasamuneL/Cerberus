"""Etapa afín del registro paciente → MNI en un proceso con 1 hilo, docs/PLAN_MVP.md §25 ticket REG1.

ITK lee `ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS` una sola vez por proceso (cambiar la variable después de importar ANTs
no tiene efecto, medido en REG1), y con varios hilos la reducción del histograma conjunto de Mattes suma en un orden
que cambia entre corridas: en estudios mal condicionados (004/t0) el optimizador afín cae en mínimos distintos.
Con 1 hilo la etapa afín es bit a bit reproducible y cuesta ~5 s; el SyN, que sí es caro, sigue multihilo en el
proceso del worker (ver `atlas._register`).

Este módulo solo importa ANTs (arranque ~1 s). Uso: `python -m cerberus_api.linear_reg ['<json>']`. El JSON lleva
`fixed`, `moving`, `mask`, `moving_mask` (rutas NIfTI), `outprefix` y `random_seed`; sin argumento se lee de stdin
**después** de importar ANTs, así el worker lanza el proceso antes de preparar las imágenes y el arranque no suma
tiempo. Imprime en la última línea la ruta de la afín (`<outprefix>0GenericAffine.mat`).
"""

import json
import sys
from typing import Any

# La etapa afín que el "SyN" de ANTsPy 0.5.3 fija por dentro (`registration.py`, rama "SyN"): Affine[0.25] con
# Mattes 32 bins, muestreo regular 0.2, 2100x1200x1200x0 iteraciones, suavizado 3x2x1x0 y reducción 4x2x2x1.
# Reproducirla aquí mantiene el mismo problema de optimización que el `full` de antes; solo cambia el número de hilos.
AFFINE_STAGE: dict[str, Any] = {
    "aff_metric": "mattes",
    "aff_sampling": 32,
    "aff_random_sampling_rate": 0.2,
    "aff_iterations": (2100, 1200, 1200, 0),
    "aff_shrink_factors": (4, 2, 2, 1),
    "aff_smoothing_sigmas": (3, 2, 1, 0),
}


def run_affine(args: dict[str, Any]) -> str:
    """Registra `moving` → `fixed` solo con la etapa afín y devuelve la ruta del `.mat`."""
    import ants

    reg = ants.registration(
        fixed=ants.image_read(args["fixed"]),
        moving=ants.image_read(args["moving"]),
        type_of_transform="Affine",
        outprefix=args["outprefix"],
        mask=ants.image_read(args["mask"]),
        moving_mask=ants.image_read(args["moving_mask"]),
        random_seed=args["random_seed"],
        **AFFINE_STAGE,
    )
    mats = [str(p) for p in reg["fwdtransforms"] if str(p).endswith(".mat")]
    if len(mats) != 1:
        raise RuntimeError(f"La etapa afín devolvió {len(mats)} transformaciones .mat")
    return mats[0]


def main(argv: list[str] | None = None) -> None:
    """Punto de entrada del subproceso: lee el JSON de `argv[0]` (o de stdin) e imprime la ruta de la afín."""
    argv = sys.argv[1:] if argv is None else argv
    import ants  # noqa: F401  (se importa antes de esperar stdin: el arranque se solapa con el padre)

    payload = argv[0] if argv else sys.stdin.read()
    print(run_affine(json.loads(payload)), flush=True)


if __name__ == "__main__":
    main()
