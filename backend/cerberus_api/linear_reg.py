"""Etapa afín del registro paciente → MNI en un proceso con 1 hilo, docs/PLAN_MVP.md §25 ticket REG1.

ITK lee `ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS` al inicializarse. Con varios hilos la métrica de Mattes puede
llevar al optimizador afín a mínimos distintos entre corridas. El subproceso recibe un hilo desde su arranque
y deja la etapa no lineal en el worker (ver `atlas._register`).

`python -m cerberus_api.linear_reg` lee de stdin las rutas NIfTI, el prefijo de salida y la semilla en JSON.
Escribe en stdout la ruta de la afín como cadena JSON.
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
        mask_all_stages=True,  # El GTV queda excluido del costo también en la etapa afín.
        random_seed=args["random_seed"],
        **AFFINE_STAGE,
    )
    mats = [str(p) for p in reg["fwdtransforms"] if str(p).endswith(".mat")]
    if len(mats) != 1:
        raise RuntimeError(f"La etapa afín devolvió {len(mats)} transformaciones .mat")
    return mats[0]


def main() -> None:
    """Lee los argumentos de stdin y devuelve la ruta de la afín por stdout."""
    print(json.dumps(run_affine(json.load(sys.stdin))))


if __name__ == "__main__":
    main()
