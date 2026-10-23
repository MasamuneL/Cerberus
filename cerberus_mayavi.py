"""Escena Mayavi de Cerberus: cerebro, edema FLAIR, MONAI WT y GTV con panel de volúmenes.

Se usa de dos formas:
- Desde el notebook (offscreen, ETS_TOOLKIT=null) para capturar una imagen.
- Como script, en ventana Qt interactiva:  python cerberus_mayavi.py escena.npz
  (el .npz lo genera el notebook con `save_scene`).
"""

import sys

import numpy as np


def save_scene(path, brain, gtv, flair_total=None, wt=None, title=""):
    """Guarda las máscaras (grid de 1 mm) para abrirlas en la ventana nativa."""
    _opt = {k: v for k, v in {"flair_total": flair_total, "wt": wt}.items() if v is not None}
    np.savez_compressed(path, brain=brain, gtv=gtv, title=np.array(title), **_opt)


def build_scene(mlab, brain, gtv, flair_total=None, wt=None, step=2, title="", size=(1000, 750)):
    """Dibuja la escena y devuelve la figura. Máscaras booleanas en grid de 1 mm³."""
    _layers = [(brain, (0.75, 0.75, 0.8), 0.12)]
    if wt is not None:
        _layers.append((wt, (0.1, 0.6, 0.2), 0.25))
    if flair_total is not None:
        _layers.append((flair_total, (1.0, 0.8, 0.0), 0.35))
    _layers.append((gtv, (0.85, 0.1, 0.1), 0.95))

    fig = mlab.figure(size=size, bgcolor=(1, 1, 1))
    for _m, _c, _o in _layers:
        # scalar_field + spacing en mm (no `extent`, que reescala cada superficie a su propio bounding box)
        _src = mlab.pipeline.scalar_field(_m[::step, ::step, ::step].astype(np.float32), figure=fig)
        _src.spacing = (step, step, step)
        mlab.pipeline.iso_surface(_src, contours=[0.5], color=_c, opacity=_o, figure=fig)

    # n vóxeles / 1000 = cm³ en el grid de 1 mm, así GTV + edema = total exacto
    def _pct(m):
        return 100 * m.sum() / brain.sum()

    _panel = [
        (title, (0.1, 0.1, 0.1), 22, True),
        (f"Cerebro: {brain.sum() / 1000:.0f} cm3", (0.35, 0.35, 0.45), 18, False),
        (f"GTV (solido): {gtv.sum() / 1000:.1f} cm3 = {_pct(gtv):.2f} %", (0.75, 0.05, 0.05), 18, False),
    ]
    if flair_total is not None:
        _edema = flair_total & ~gtv
        _panel += [
            (f"Edema FLAIR: {_edema.sum() / 1000:.1f} cm3 = {_pct(_edema):.2f} %", (0.7, 0.5, 0.0), 18, False),
            (f"TOTAL (GTV+edema): {flair_total.sum() / 1000:.1f} cm3 = {_pct(flair_total):.2f} %", (0.1, 0.1, 0.1), 22, True),
        ]
    if wt is not None:
        _panel.append((f"MONAI WT: {wt.sum() / 1000:.1f} cm3 = {_pct(wt):.2f} %", (0.1, 0.5, 0.2), 18, False))
    for _i, (_txt, _col, _size, _bold) in enumerate(_panel):
        _t = mlab.text(0.02, 0.93 - 0.055 * _i, _txt, color=_col, figure=fig)
        _t.actor.text_scale_mode = "none"  # tamaño fijo en px, no escalado al ancho
        _t.property.font_size = _size
        _t.property.bold = _bold

    # Etiqueta 3D anclada sobre el tumor (coordenadas en mm del grid de 1 mm)
    _cx, _cy, _cz = np.argwhere(gtv).mean(0)
    _label = f"{_pct(flair_total):.1f} % total" if flair_total is not None else f"{_pct(gtv):.1f} %"
    mlab.text3d(_cx, _cy, _cz + 45, _label, color=(0.5, 0, 0), scale=7, figure=fig)
    return fig


if __name__ == "__main__":
    import os

    os.environ.setdefault("ETS_TOOLKIT", "qt")
    os.environ.setdefault("QT_API", "pyqt5")
    from mayavi import mlab

    _d = np.load(sys.argv[1])
    build_scene(
        mlab,
        _d["brain"],
        _d["gtv"],
        flair_total=_d["flair_total"] if "flair_total" in _d else None,
        wt=_d["wt"] if "wt" in _d else None,
        title=str(_d["title"]),
    )
    mlab.view(azimuth=45, elevation=70, distance="auto")
    mlab.show()
