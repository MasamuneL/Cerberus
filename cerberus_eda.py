import marimo

__generated_with = "0.25.2"
app = marimo.App(
    width="full",
    app_title="Cerberus · EDA y segmentación CFB-GBM",
)


@app.cell
def _():
    import os

    # Mayavi sin ventana: debe definirse ANTES de importar mayavi
    os.environ.setdefault("ETS_TOOLKIT", "null")
    os.environ.setdefault("QT_API", "pyqt5")

    import functools
    import re
    from pathlib import Path

    import marimo as mo
    import matplotlib.pyplot as plt
    import nibabel as nib
    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go
    from scipy import ndimage as ndi
    from skimage import filters, measure
    from sklearn.cluster import KMeans

    return (
        KMeans,
        Path,
        filters,
        functools,
        go,
        measure,
        mo,
        ndi,
        nib,
        np,
        pd,
        plt,
        re,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Proyecto Cerberus — Análisis, visualización y segmentación (CFB-GBM)

    Notebook de exploración sobre la muestra local del dataset **CFB-GBM** (TCIA, glioblastoma).
    Sigue lo propuesto en las notas del proyecto:

    | Nota | Qué aplicamos aquí |
    |---|---|
    | *Planos anatómicos y tipos de visualización* | Cortes **axial / coronal / sagital** sincronizados, máscara superpuesta y control de opacidad |
    | *Herramientas de visualización – Mayavi* | **Mayavi (`mlab.contour3d`)** para iso-superficies 3D (render offscreen) + Plotly como visor interactivo |
    | *Volumetría tumoral cerebral* | $V = N_{vóxeles}\cdot s_x s_y s_z$, fracción tumor/cerebro, **ABC/2** vs planimetría, umbrales **RANO 2.0** |
    | *Modelos open source para segmentación* | Líneas base clásicas (Otsu, K-Means) y **MONAI Model Zoo `brats_mri_segmentation`** (SegResNet BraTS) |

    > ⚠️ La máscara de referencia del dataset es **GTV de radioterapia** (puede incluir cavidad de resección y excluye edema).
    > Todo volumen reportado aquí es “GTV”, no “volumen tumoral” genérico.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. Inventario de la data
    """)
    return


@app.cell
def _(Path):
    DATA_DIR = Path(__file__).parent / "Data"
    BUNDLE_DIR = Path(__file__).parent / "models"

    SEQ_INFO = {
        "t1gd": "T1 con gadolinio (realce)",
        "t1eg": "T1 gradiente-eco",
        "t1tse": "T1 turbo spin-eco",
        "t2tse": "T2 turbo spin-eco",
        "t2star": "T2* (sangre / calcio)",
        "flair": "T2-FLAIR (edema)",
        "adc": "Mapa ADC (difusión)",
        "ct": "Tomografía (planeación RT)",
        "rtdose": "Dosis de radioterapia (Gy)",
        "brain_mask": "Máscara cerebral (skull-strip)",
        "gtv": "GTV de radioterapia (etiqueta)",
    }
    MRI_SEQS = ["t1gd", "t1eg", "t1tse", "t2tse", "t2star", "flair", "adc"]
    return BUNDLE_DIR, DATA_DIR, MRI_SEQS, SEQ_INFO


@app.cell
def _(DATA_DIR, nib, pd, re):
    _rows = []
    for _f in sorted(DATA_DIR.glob("*/t*/*.nii.gz")):
        _m = re.match(r"(\d+)_(t\d)_(.+)\.nii\.gz", _f.name)
        if not _m:
            continue
        _hdr = nib.load(_f).header
        _rows.append(
            {
                "paciente": f"{int(_m.group(1)):03d}",
                "tiempo": _m.group(2),
                "secuencia": _m.group(3),
                "shape": tuple(int(s) for s in _hdr.get_data_shape()),
                "spacing_mm": tuple(round(float(z), 3) for z in _hdr.get_zooms()[:3]),
                "dtype": str(_hdr.get_data_dtype()),
                "path": str(_f),
            }
        )
    inventory = pd.DataFrame(_rows)
    return (inventory,)


@app.cell
def _(SEQ_INFO, inventory, mo, plt):
    _avail = (
        inventory.assign(estudio=inventory.paciente + "/" + inventory.tiempo, v=1)
        .pivot_table(index="estudio", columns="secuencia", values="v", fill_value=0)
        .reindex(columns=[s for s in SEQ_INFO if s in inventory.secuencia.unique()])
    )
    _fig, _ax = plt.subplots(figsize=(9, 3.6))
    _ax.imshow(_avail.values, cmap="Greens", vmin=0, vmax=1.4, aspect="auto")
    _ax.set_xticks(range(_avail.shape[1]), _avail.columns, rotation=45, ha="right")
    _ax.set_yticks(range(_avail.shape[0]), _avail.index)
    for _i in range(_avail.shape[0]):
        for _j in range(_avail.shape[1]):
            _ax.text(_j, _i, "✓" if _avail.values[_i, _j] else "–", ha="center", va="center", fontsize=9)
    _ax.set_title("Disponibilidad de secuencias por estudio (paciente/tiempo)")
    _fig.tight_layout()

    mo.vstack(
        [
            mo.md(
                f"**{inventory.paciente.nunique()} pacientes · "
                f"{inventory.groupby(['paciente', 'tiempo']).ngroups} estudios · {len(inventory)} volúmenes NIfTI**. "
                f"Geometrías: `{sorted(inventory['shape'].unique())}` · "
                f"spacing: `{sorted(inventory['spacing_mm'].unique())}` → todo está **co-registrado en el mismo grid**."
            ),
            _fig,
            mo.accordion({"Tabla completa del inventario": mo.ui.table(inventory.drop(columns="path"), page_size=10)}),
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Utilidades de carga

    Los volúmenes son 512×512×208 a 0.5×0.5×1 mm. Para explorar y segmentar se submuestrean en el plano
    (`stride=2`) a **1 mm isotrópico** (256×256×208), que es además la resolución que espera el modelo de MONAI.
    La volumetría de la sección 2 se calcula a **resolución nativa**.
    """)
    return


@app.cell
def _(functools, inventory, nib, np):
    @functools.lru_cache(maxsize=24)
    def load_vol(path: str, stride: int = 2) -> np.ndarray:
        """Carga un NIfTI como float32, submuestreando x/y con `stride` (2 → 1 mm isotrópico)."""
        return np.asanyarray(nib.load(path).dataobj, dtype=np.float32)[::stride, ::stride, :]

    def path_of(pid: str, tp: str, seq: str) -> str | None:
        _r = inventory.query("paciente == @pid and tiempo == @tp and secuencia == @seq")
        return None if _r.empty else _r.path.iloc[0]

    def dice(a: np.ndarray, b: np.ndarray) -> float:
        a, b = a.astype(bool), b.astype(bool)
        _den = a.sum() + b.sum()
        return float(2 * (a & b).sum() / _den) if _den else 1.0

    def zscore_in(vol: np.ndarray, mask: np.ndarray) -> np.ndarray:
        _v = vol[mask]
        return (vol - _v.mean()) / (_v.std() + 1e-6)

    return dice, load_vol, path_of, zscore_in


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2. Volumetría del GTV en todos los estudios

    - **Planimetría (vóxeles):** $V = N \cdot s_x s_y s_z$ — referencia exacta dada la máscara.
    - **ABC/2:** $A\cdot B\cdot C/2$ con los diámetros del *bounding box* (LR, AP, SI). La literatura reporta sobreestimación de 29–45 %.
    - **Fracción cerebral:** tumor/cerebro, adimensional (no depende del spacing).
    - **Control de escala:** un `pixdim = (1,1,1)` exacto sería señal de header perdido.
    - **Medible RANO 2.0:** ≥ 10 mm en las tres direcciones.
    """)
    return


@app.cell
def _(inventory, mo, ndi, nib, np, pd):
    @mo.cache
    def volumetry_table(studies: tuple) -> pd.DataFrame:
        _rows = []
        for _pid, _tp, _gtv_path, _brain_path in studies:
            _img = nib.load(_gtv_path)
            _sx, _sy, _sz = (float(z) for z in _img.header.get_zooms()[:3])
            _gtv = np.asanyarray(_img.dataobj) > 0
            _brain = np.asanyarray(nib.load(_brain_path).dataobj) > 0
            _vox = _sx * _sy * _sz
            _idx = np.argwhere(_gtv)
            _ext = (_idx.max(0) - _idx.min(0) + 1) * np.array([_sx, _sy, _sz])
            _v = _gtv.sum() * _vox / 1000
            _abc2 = np.prod(_ext) / 2 / 1000
            _rows.append(
                {
                    "paciente": _pid,
                    "tiempo": _tp,
                    "GTV_cm3": round(_v, 2),
                    "cerebro_cm3": round(_brain.sum() * _vox / 1000, 1),
                    "fraccion_%": round(100 * _gtv.sum() / _brain.sum(), 2),
                    "LR_mm": round(_ext[0], 1),
                    "AP_mm": round(_ext[1], 1),
                    "SI_mm": round(_ext[2], 1),
                    "ABC/2_cm3": round(_abc2, 2),
                    "error_ABC/2_%": round(100 * (_abc2 - _v) / _v, 1),
                    "componentes": int(ndi.label(_gtv)[1]),
                    "medible_RANO": bool((_ext >= 10).all()),
                    "spacing_ok": (_sx, _sy, _sz) != (1.0, 1.0, 1.0),
                }
            )
        return pd.DataFrame(_rows)

    _studies = []
    for (_pid, _tp), _g in inventory.groupby(["paciente", "tiempo"]):
        _s = dict(zip(_g.secuencia, _g.path))
        if "gtv" in _s and "brain_mask" in _s:
            _studies.append((_pid, _tp, _s["gtv"], _s["brain_mask"]))

    with mo.status.spinner("Calculando volumetría a resolución nativa…"):
        vol_df = volumetry_table(tuple(_studies))
    vol_df
    return (vol_df,)


@app.cell
def _(mo, plt, vol_df):
    _lbl = vol_df.paciente + "/" + vol_df.tiempo
    _fig, (_a1, _a2) = plt.subplots(1, 2, figsize=(12, 3.8))
    _x = range(len(vol_df))
    _a1.bar([i - 0.2 for i in _x], vol_df["GTV_cm3"], 0.4, label="Planimetría (vóxeles)")
    _a1.bar([i + 0.2 for i in _x], vol_df["ABC/2_cm3"], 0.4, label="ABC/2 (bbox)")
    _a1.set_xticks(list(_x), _lbl, rotation=30)
    _a1.set_ylabel("cm³")
    _a1.set_title("GTV: planimetría vs ABC/2")
    _a1.legend()
    _a2.scatter(vol_df["GTV_cm3"], vol_df["error_ABC/2_%"])
    for _t, _xx, _yy in zip(_lbl, vol_df["GTV_cm3"], vol_df["error_ABC/2_%"]):
        _a2.annotate(_t, (_xx, _yy), fontsize=8, xytext=(3, 3), textcoords="offset points")
    _a2.axhline(0, color="k", lw=0.8)
    _a2.set_xlabel("GTV (cm³)")
    _a2.set_ylabel("Error ABC/2 (%)")
    _a2.set_title("Sesgo de la aproximación elipsoidal")
    _fig.tight_layout()
    mo.vstack(
        [
            _fig,
            mo.md(
                f"ABC/2 con bounding box **sobreestima en promedio {vol_df['error_ABC/2_%'].mean():.0f} %** "
                "(el GBM es irregular: peor caso para una elipse)."
            ),
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 2.1 Seguimiento longitudinal — umbrales volumétricos RANO 2.0

    | Categoría | Cambio de volumen vs basal |
    |---|---|
    | Progresión (PD) | ≥ +40 % |
    | Respuesta parcial (PR) | ≤ −65 % |
    | Respuesta menor (MR) | ≤ −40 % y > −65 % |
    | Estable (SD) | resto |

    > Ejercicio sobre el GTV. RANO 2.0 mide volumen **realzante en T1Gd**, que no es exactamente el GTV.
    """)
    return


@app.cell
def _(mo, plt, vol_df):
    def rano_vol(pct: float) -> str:
        if pct >= 40:
            return "PD (progresión)"
        if pct <= -65:
            return "PR (respuesta parcial)"
        if pct <= -40:
            return "MR (respuesta menor)"
        return "SD (estable)"

    _long = vol_df[vol_df.groupby("paciente").tiempo.transform("nunique") > 1].copy()
    _base = _long[_long.tiempo == "t0"].set_index("paciente")["GTV_cm3"]
    _long["cambio_vs_t0_%"] = (100 * (_long.GTV_cm3 / _long.paciente.map(_base) - 1)).round(1)
    _long["RANO_2.0_vol"] = _long["cambio_vs_t0_%"].apply(rano_vol)

    _fig, _ax = plt.subplots(figsize=(6, 3.5))
    for _pid, _g in _long.groupby("paciente"):
        _ax.plot(_g.tiempo, _g["cambio_vs_t0_%"], marker="o", label=f"Paciente {_pid}")
    _ax.axhspan(40, 100, color="red", alpha=0.08, label="PD ≥ +40 %")
    _ax.axhspan(-100, -65, color="green", alpha=0.08, label="PR ≤ −65 %")
    _ax.set_ylim(-80, 60)
    _ax.set_ylabel("Δ GTV vs t0 (%)")
    _ax.legend(fontsize=8)
    _ax.set_title("Evolución del GTV (t0 → t1 → t2)")
    _fig.tight_layout()
    mo.hstack([_long[["paciente", "tiempo", "GTV_cm3", "cambio_vs_t0_%", "RANO_2.0_vol"]], _fig], widths=[1, 1])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. Visor de cortes ortogonales (axial · coronal · sagital)

    Orientación de los volúmenes: **LPS** (x→izquierda, y→posterior, z→superior). Se muestran en **convención radiológica**
    (la izquierda del paciente a la derecha de la imagen). Los sliders inician en el centroide del GTV.
    """)
    return


@app.cell
def _(inventory, mo):
    patient_dd = mo.ui.dropdown(sorted(inventory.paciente.unique()), value="001", label="Paciente")
    patient_dd
    return (patient_dd,)


@app.cell
def _(inventory, mo):
    _tps = sorted(inventory.query("paciente == @patient_dd.value").tiempo.unique())
    timepoint_dd = mo.ui.dropdown(_tps, value=_tps[0], label="Tiempo")
    timepoint_dd
    return (timepoint_dd,)


@app.cell
def _(MRI_SEQS, inventory, load_vol, np, path_of, patient_dd, timepoint_dd):
    pid, tp = patient_dd.value, timepoint_dd.value
    case_seqs = sorted(inventory.query("paciente == @pid and tiempo == @tp").secuencia)
    case_mri = [s for s in MRI_SEQS if s in case_seqs]
    brain = load_vol(path_of(pid, tp, "brain_mask")) > 0
    gtv = load_vol(path_of(pid, tp, "gtv")) > 0
    gtv_center = [int(round(c)) for c in np.argwhere(gtv).mean(0)]
    return brain, case_mri, case_seqs, gtv, gtv_center, pid, tp


@app.cell
def _(brain, case_seqs, gtv_center, mo):
    _viewable = [s for s in case_seqs if s not in ("gtv", "brain_mask")]
    seq_dd = mo.ui.dropdown(_viewable, value="t1gd" if "t1gd" in _viewable else _viewable[0], label="Secuencia")
    sl_x = mo.ui.slider(0, brain.shape[0] - 1, value=gtv_center[0], label="Sagital (x)", show_value=True)
    sl_y = mo.ui.slider(0, brain.shape[1] - 1, value=gtv_center[1], label="Coronal (y)", show_value=True)
    sl_z = mo.ui.slider(0, brain.shape[2] - 1, value=gtv_center[2], label="Axial (z)", show_value=True)
    opacity = mo.ui.slider(0.0, 1.0, step=0.05, value=0.4, label="Opacidad GTV", show_value=True)
    show_brain = mo.ui.checkbox(value=False, label="Contorno máscara cerebral")
    mo.hstack([seq_dd, sl_x, sl_y, sl_z, opacity, show_brain], wrap=True)
    return opacity, seq_dd, show_brain, sl_x, sl_y, sl_z


@app.cell
def _(np, plt):
    def ortho_view(vol, overlays, x, y, z, title="", alpha=0.4, cmap="gray", vlim=None, contours=None):
        """Tres cortes de un volumen LPS en convención radiológica.

        overlays: lista de (máscara, color) rellenos; contours: lista de (máscara, color) solo borde.
        """
        if vlim is None:
            _nz = vol[vol != 0]
            vlim = np.percentile(_nz, [1, 99]) if _nz.size else (0, 1)
        _cuts = [
            (f"Axial z={z}", lambda a: a[:, :, z].T, "upper", (x, y)),
            (f"Coronal y={y}", lambda a: a[:, y, :].T, "lower", (x, z)),
            (f"Sagital x={x}", lambda a: a[x, :, :].T, "lower", (y, z)),
        ]
        _fig, _axes = plt.subplots(1, 3, figsize=(14, 5))
        for _ax, (_name, _cut, _origin, (_cx, _cy)) in zip(_axes, _cuts):
            _ax.imshow(_cut(vol), cmap=cmap, vmin=vlim[0], vmax=vlim[1], origin=_origin)
            for _m, _c in overlays:
                _s = _cut(_m)
                _rgba = np.zeros((*_s.shape, 4))
                _rgba[_s > 0] = (*plt.matplotlib.colors.to_rgb(_c), alpha)
                _ax.imshow(_rgba, origin=_origin)
            for _m, _c in contours or []:
                _s = _cut(_m)
                if _s.any():
                    _ax.contour(_s.astype(float), levels=[0.5], colors=[_c], linewidths=0.8, origin=_origin)
            _ax.axvline(_cx, color="yellow", lw=0.5, alpha=0.6)
            _ax.axhline(_cy, color="yellow", lw=0.5, alpha=0.6)
            _ax.set_title(_name)
            _ax.axis("off")
        _fig.suptitle(title)
        _fig.tight_layout()
        return _fig

    return (ortho_view,)


@app.cell
def _(
    SEQ_INFO,
    brain,
    gtv,
    load_vol,
    opacity,
    ortho_view,
    path_of,
    pid,
    seq_dd,
    show_brain,
    sl_x,
    sl_y,
    sl_z,
    tp,
):
    ortho_view(
        load_vol(path_of(pid, tp, seq_dd.value)),
        [(gtv, "red")],
        sl_x.value,
        sl_y.value,
        sl_z.value,
        title=f"Paciente {pid} · {tp} · {seq_dd.value} — {SEQ_INFO.get(seq_dd.value, '')}  (rojo = GTV)",
        alpha=opacity.value,
        cmap="jet" if seq_dd.value == "rtdose" else "gray",
        contours=[(brain, "cyan")] if show_brain.value else None,
    )
    return


@app.cell
def _(case_mri, load_vol, mo, np, path_of, pid, plt, sl_z, tp):
    # Mosaico: todas las secuencias MRI del estudio en el mismo corte axial
    _fig, _axes = plt.subplots(1, len(case_mri), figsize=(3 * len(case_mri), 3.4))
    for _ax, _s in zip(np.atleast_1d(_axes), case_mri):
        _v = load_vol(path_of(pid, tp, _s))[:, :, sl_z.value].T
        _nz = _v[_v != 0]
        _lo, _hi = np.percentile(_nz, [1, 99]) if _nz.size else (0, 1)
        _ax.imshow(_v, cmap="gray", vmin=_lo, vmax=_hi)
        _ax.set_title(_s)
        _ax.axis("off")
    _fig.suptitle(f"Multisecuencia en el corte axial z={sl_z.value}")
    _fig.tight_layout()
    mo.vstack([mo.md("Cada secuencia resalta tejido distinto: **T1Gd** el realce, **FLAIR** el edema, **ADC** la celularidad."), _fig])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Análisis de intensidades: GTV vs cerebro sano

    Cada secuencia se normaliza con *z-score* dentro de la máscara cerebral (igual que MONAI `NormalizeIntensity(nonzero=True)`).
    El **d de Cohen** mide qué tanto separa cada secuencia el GTV del resto del cerebro → guía qué canales usar para segmentar.
    """)
    return


@app.cell
def _(
    brain,
    case_mri,
    gtv,
    load_vol,
    mo,
    np,
    path_of,
    pd,
    pid,
    plt,
    tp,
    zscore_in,
):
    _rng = np.random.default_rng(0)
    _healthy = brain & ~gtv
    _stats, _samples = [], {}
    for _s in case_mri:
        _z = zscore_in(load_vol(path_of(pid, tp, _s)), brain)
        _t, _h = _z[gtv], _z[_healthy]
        _pooled = np.sqrt((_t.var() + _h.var()) / 2)
        _stats.append(
            {
                "secuencia": _s,
                "media_GTV (z)": round(float(_t.mean()), 2),
                "media_sano (z)": round(float(_h.mean()), 2),
                "d_Cohen": round(float((_t.mean() - _h.mean()) / (_pooled + 1e-6)), 2),
            }
        )
        _samples[_s] = (_rng.choice(_t, min(20000, _t.size)), _rng.choice(_h, 20000))
    intensity_df = pd.DataFrame(_stats).sort_values("d_Cohen", key=abs, ascending=False, ignore_index=True)

    _fig, _axes = plt.subplots(1, len(case_mri), figsize=(3 * len(case_mri), 3), sharey=True)
    _bins = np.linspace(-4, 6, 80)
    for _ax, _s in zip(np.atleast_1d(_axes), case_mri):
        _t, _h = _samples[_s]
        _ax.hist(_h, _bins, density=True, alpha=0.6, label="cerebro sano")
        _ax.hist(_t, _bins, density=True, alpha=0.6, color="red", label="GTV")
        _ax.set_title(_s)
    np.atleast_1d(_axes)[0].legend(fontsize=8)
    _fig.suptitle("Distribución de intensidades normalizadas")
    _fig.tight_layout()
    mo.vstack([_fig, intensity_df])
    return (intensity_df,)


@app.cell
def _(brain, case_seqs, gtv, load_vol, mo, np, path_of, pid, plt, tp):
    # Histograma dosis-volumen (DVH): cuánta dosis recibió el GTV vs el resto del cerebro
    mo.stop("rtdose" not in case_seqs, mo.md("_Este estudio no tiene `rtdose` (solo los estudios t0 lo traen)._"))
    _dose = load_vol(path_of(pid, tp, "rtdose"))
    _g, _h = _dose[gtv], _dose[brain & ~gtv]
    _d = np.linspace(0, _dose.max(), 200)
    _fig, _ax = plt.subplots(figsize=(6, 3.5))
    for _vals, _n, _c in [(_g, "GTV", "red"), (_h, "Cerebro fuera del GTV", "tab:blue")]:
        _ax.plot(_d, [(_vals >= x).mean() * 100 for x in _d], label=_n, color=_c)
    _ax.set_xlabel("Dosis (Gy)")
    _ax.set_ylabel("% de volumen ≥ dosis")
    _ax.set_title("DVH acumulado")
    _ax.legend()
    _ax.grid(alpha=0.3)
    _fig.tight_layout()
    mo.hstack(
        [
            _fig,
            mo.md(
                f"""
    | Métrica | Gy |
    |---|---|
    | Dosis media GTV | {_g.mean():.1f} |
    | D95 GTV (cubre 95 %) | {np.percentile(_g, 5):.1f} |
    | D2 GTV (casi máxima) | {np.percentile(_g, 98):.1f} |
    | Dosis media cerebro sano | {_h.mean():.1f} |
    """
            ),
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5. Segmentación

    Tres enfoques, de menor a mayor complejidad, comparados contra el **GTV** con **Dice** y **error volumétrico**
    (la nota de volumetría insiste: un Dice alto no garantiza un volumen correcto).

    1. **Doble umbral de Otsu** sobre una secuencia + limpieza morfológica + componente conexa más grande.
    2. **K-Means multisecuencia** (no supervisado) sobre los vóxeles del cerebro.
    3. **MONAI `brats_mri_segmentation`** — SegResNet 3D preentrenado en BraTS (canales T1c, T1, T2, FLAIR a 1 mm).

    > Contexto: el Dice inter-observador humano en GBM ronda **0.72–0.88**. No esperar 1.0.
    """)
    return


@app.cell
def _(case_mri, intensity_df, mo):
    otsu_seq = mo.ui.dropdown(case_mri, value=intensity_df.secuencia.iloc[0], label="Secuencia Otsu")
    km_seqs = mo.ui.multiselect(
        case_mri, value=[s for s in ("t1gd", "flair", "t2tse", "t2star") if s in case_mri][:3], label="Canales K-Means"
    )
    km_k = mo.ui.slider(3, 8, value=5, label="k", show_value=True)
    mo.hstack([otsu_seq, km_seqs, km_k], justify="start", gap=2)
    return km_k, km_seqs, otsu_seq


@app.cell
def _(filters, ndi, np):
    def largest_cc(mask: np.ndarray) -> np.ndarray:
        _lab, _n = ndi.label(mask)
        if _n == 0:
            return mask
        return _lab == (np.argmax(ndi.sum(mask, _lab, range(1, _n + 1))) + 1)

    def clean(mask: np.ndarray) -> np.ndarray:
        _m = largest_cc(ndi.binary_opening(mask, iterations=2))
        return ndi.binary_fill_holes(ndi.binary_closing(_m, iterations=2))

    def seg_otsu(vol: np.ndarray, brain: np.ndarray, polarity: int = 1) -> np.ndarray:
        _v = polarity * vol
        # 1er Otsu separa tejidos del cerebro; 2º Otsu sobre la cola brillante aísla la lesión
        _thr = filters.threshold_otsu(_v[brain])
        _thr2 = filters.threshold_otsu(_v[brain & (_v > _thr)])
        return clean(brain & (_v > _thr2))

    return clean, seg_otsu


@app.cell
def _(
    brain,
    dice,
    gtv,
    intensity_df,
    load_vol,
    otsu_seq,
    path_of,
    pid,
    seg_otsu,
    tp,
):
    # Polaridad según el signo del d de Cohen (p.ej. ADC puede ser hipointenso en el tumor)
    _d = intensity_df.set_index("secuencia").loc[otsu_seq.value, "d_Cohen"]
    pred_otsu = seg_otsu(load_vol(path_of(pid, tp, otsu_seq.value)), brain, polarity=1 if _d >= 0 else -1)
    dice_otsu = dice(pred_otsu, gtv)
    return dice_otsu, pred_otsu


@app.cell
def _(
    KMeans,
    brain,
    clean,
    dice,
    gtv,
    km_k,
    km_seqs,
    load_vol,
    mo,
    np,
    path_of,
    pid,
    tp,
    zscore_in,
):
    mo.stop(len(km_seqs.value) == 0, mo.md("_Selecciona al menos un canal para K-Means._"))
    _feats = np.stack([zscore_in(load_vol(path_of(pid, tp, s)), brain)[brain] for s in km_seqs.value], 1)
    _fit_idx = np.random.default_rng(0).choice(len(_feats), min(150_000, len(_feats)), replace=False)
    _km = KMeans(n_clusters=km_k.value, n_init=4, random_state=0).fit(_feats[_fit_idx])
    # Heurística que no mira la etiqueta: el cluster más "anómalo" (centro z-score más lejano del origen)
    _tumor_c = int(np.argmax(np.linalg.norm(_km.cluster_centers_, axis=1)))
    km_labels = np.zeros(brain.shape, np.int16)
    km_labels[brain] = _km.predict(_feats) + 1
    pred_km = clean(km_labels == _tumor_c + 1)
    dice_km = dice(pred_km, gtv)
    return dice_km, km_labels, pred_km


@app.cell
def _(
    brain,
    dice_km,
    dice_otsu,
    gtv,
    km_labels,
    mo,
    ortho_view,
    otsu_seq,
    pred_km,
    pred_otsu,
    sl_x,
    sl_y,
    sl_z,
):
    _f1 = ortho_view(
        brain.astype(float), [(pred_otsu, "orange")], sl_x.value, sl_y.value, sl_z.value,
        title=f"Otsu sobre {otsu_seq.value} (naranja) vs GTV (contorno rojo) — Dice {dice_otsu:.3f}",
        alpha=0.6, vlim=(0, 3), contours=[(gtv, "red")],
    )
    _f2 = ortho_view(
        km_labels.astype(float), [], sl_x.value, sl_y.value, sl_z.value,
        title=f"K-Means: clusters · elegido (magenta) vs GTV (blanco) — Dice {dice_km:.3f}",
        cmap="tab10", vlim=(0, 10), contours=[(gtv, "white"), (pred_km, "magenta")],
    )
    mo.vstack([_f1, _f2])
    return


@app.cell
def _(gtv, mo, pd, pred_km, pred_otsu):
    def seg_metrics(name, pred):
        # Grid de 1 mm³ → n vóxeles / 1000 = cm³
        _vp, _vg = pred.sum() / 1000, gtv.sum() / 1000
        return {
            "método": name,
            "Dice": round(float(2 * (pred & gtv).sum() / (pred.sum() + gtv.sum())), 3),
            "vol_pred_cm3": round(_vp, 2),
            "vol_GTV_cm3": round(_vg, 2),
            "error_vol_%": round(100 * (_vp - _vg) / _vg, 1),
        }

    classic_rows = [seg_metrics("Otsu", pred_otsu), seg_metrics("K-Means", pred_km)]
    mo.vstack([mo.md("### Comparativa de líneas base clásicas"), pd.DataFrame(classic_rows)])
    return classic_rows, seg_metrics


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 5.3 MONAI — SegResNet preentrenado (BraTS)

    El bundle espera 4 canales **[T1c, T1, T2, FLAIR]**. CFB-GBM no siempre los trae todos, así que se mapea:

    - T1c ← `t1gd` · T1 ← `t1eg` o `t1tse` · T2 ← `t2tse` o `t2star` · FLAIR ← `flair`
    - Canal faltante → ceros (= media tras normalizar). Degrada el resultado; queda documentado en la tabla.

    Salidas: **TC** (tumor core), **WT** (whole tumor = core + edema) y **ET** (enhancing). El GTV se parece más a **TC**.
    """)
    return


@app.cell
def _(mo):
    run_monai = mo.ui.run_button(label="▶ Ejecutar MONAI SegResNet", kind="success")
    # Guarda el WT por (paciente, tiempo) para que Mayavi lo use si existe, sin depender de que MONAI se haya corrido
    monai_store = {}
    run_monai
    return monai_store, run_monai


@app.cell
def _(
    BUNDLE_DIR,
    brain,
    case_seqs,
    load_vol,
    mo,
    monai_store,
    np,
    path_of,
    pd,
    pid,
    run_monai,
    tp,
):
    mo.stop(not run_monai.value, mo.md("_Pulsa el botón para correr la inferencia (descarga el bundle si no existe, ~36 MB)._"))

    import torch
    from monai.bundle import download
    from monai.inferers import sliding_window_inference
    from monai.networks.nets import SegResNet
    from monai.transforms import NormalizeIntensity

    _bdir = BUNDLE_DIR / "brats_mri_segmentation"
    if not (_bdir / "models" / "model.pt").exists():
        download(name="brats_mri_segmentation", bundle_dir=str(BUNDLE_DIR))

    _mapping = {"T1c": ["t1gd"], "T1": ["t1eg", "t1tse"], "T2": ["t2tse", "t2star"], "FLAIR": ["flair"]}
    _chans, _used = [], []
    for _ch, _cands in _mapping.items():
        _src = next((c for c in _cands if c in case_seqs), None)
        _used.append({"canal_modelo": _ch, "secuencia_usada": _src or "— (ceros)"})
        _chans.append(load_vol(path_of(pid, tp, _src)) * brain if _src else np.zeros(brain.shape, np.float32))
    _x = NormalizeIntensity(nonzero=True, channel_wise=True)(torch.from_numpy(np.stack(_chans)))

    _dev = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    _net = SegResNet(
        blocks_down=[1, 2, 2, 4], blocks_up=[1, 1, 1], init_filters=16, in_channels=4, out_channels=3, dropout_prob=0.2
    )
    _net.load_state_dict(torch.load(_bdir / "models" / "model.pt", map_location="cpu"))
    _net.eval().to(_dev)
    with mo.status.spinner(f"Inferencia en {_dev}…"), torch.no_grad():
        _y = sliding_window_inference(_x[None].to(_dev), (240, 240, 160), 1, _net, overlap=0.5)
    _prob = torch.sigmoid(_y)[0].cpu().numpy()
    monai_pred = {_n: (_prob[_i] > 0.5) & brain for _i, _n in enumerate(["TC", "WT", "ET"])}
    monai_store[(pid, tp)] = monai_pred["WT"]
    mo.vstack([mo.md(f"Inferencia en **{_dev}** · canales usados:"), pd.DataFrame(_used)])
    return (monai_pred,)


@app.cell
def _(
    gtv,
    load_vol,
    monai_pred,
    ortho_view,
    path_of,
    pid,
    sl_x,
    sl_y,
    sl_z,
    tp,
):
    _t1gd = path_of(pid, tp, "t1gd")
    ortho_view(
        load_vol(_t1gd) if _t1gd else gtv.astype(float),
        [(monai_pred["WT"], "yellow"), (monai_pred["TC"], "orange"), (monai_pred["ET"], "red")],
        sl_x.value, sl_y.value, sl_z.value,
        title="MONAI: WT (amarillo) · TC (naranja) · ET (rojo) — contorno cian = GTV",
        alpha=0.35, contours=[(gtv, "cyan")],
    )
    return


@app.cell
def _(classic_rows, mo, monai_pred, pd, plt, seg_metrics):
    _df = pd.DataFrame(classic_rows + [seg_metrics(f"MONAI {k}", v) for k, v in monai_pred.items()])
    _fig, _ax = plt.subplots(figsize=(6, 3))
    _ax.barh(_df["método"], _df["Dice"], color=["gray", "gray", "tab:orange", "gold", "tab:red"])
    _ax.axvspan(0.72, 0.88, color="green", alpha=0.1, label="Dice inter-observador GBM")
    _ax.set_xlim(0, 1)
    _ax.set_xlabel("Dice vs GTV")
    _ax.legend(fontsize=8, loc="lower right")
    _fig.tight_layout()
    mo.vstack([mo.md("### 5.4 Comparativa final de métodos"), mo.hstack([_df, _fig])])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 5.5 Edema peritumoral por FLAIR (tamaño total del tumor)

    El GTV **excluye el edema** (guía ESTRO-EANO) y el dataset no trae etiqueta de edema. Lo estimamos de forma
    independiente a MONAI:

    1. Se normaliza FLAIR con la media/desviación del **cerebro sano lejano** (fuera del GTV dilatado 20 mm).
    2. Hiperintensidad = $z >$ umbral, solo dentro de una región alrededor del GTV.
    3. Se conserva solo lo **conectado al GTV** (descarta lesiones de sustancia blanca lejanas) y se rellenan huecos.
    4. **Edema = región − GTV**, **Total = GTV + edema**.

    > Es una estimación sensible al umbral (prueba el slider). Compárala con **MONAI WT** (núcleo + edema) si ya lo ejecutaste.
    """)
    return


@app.cell
def _(mo):
    flair_thr = mo.ui.slider(1.0, 3.0, step=0.25, value=1.5, label="Umbral FLAIR (z)", show_value=True)
    flair_roi = mo.ui.slider(10, 50, step=5, value=30, label="Radio búsqueda alrededor del GTV (mm)", show_value=True)
    mo.hstack([flair_thr, flair_roi], justify="start", gap=2)
    return flair_roi, flair_thr


@app.cell
def _(brain, case_seqs, flair_roi, flair_thr, gtv, load_vol, ndi, np, path_of, pid, tp):
    # Sin mo.stop: si no hay FLAIR, edema=None y Mayavi sigue funcionando
    if "flair" in case_seqs:
        _f = load_vol(path_of(pid, tp, "flair"))
        _far = brain & ~ndi.binary_dilation(gtv, iterations=20)  # grid 1 mm → iteraciones = mm
        _z = (_f - _f[_far].mean()) / (_f[_far].std() + 1e-6)
        _roi = brain & ndi.binary_dilation(gtv, iterations=flair_roi.value)
        _hyper = ndi.binary_opening((_z > flair_thr.value) & _roi, iterations=1)
        _lab, _ = ndi.label(_hyper | gtv)
        _ids = np.unique(_lab[gtv])
        flair_total = ndi.binary_fill_holes(np.isin(_lab, _ids[_ids > 0])) & brain | gtv
        edema = flair_total & ~gtv
    else:
        flair_total, edema = None, None
    return edema, flair_total


@app.cell
def _(brain, edema, flair_total, gtv, load_vol, mo, monai_store, ortho_view, path_of, pd, pid, sl_x, sl_y, sl_z, tp):
    mo.stop(edema is None, mo.md("_Este estudio no tiene FLAIR: no se puede estimar edema._"))

    def _row(name, mask):
        return {"región": name, "cm³": round(mask.sum() / 1000, 1), "% cerebro": round(100 * mask.sum() / brain.sum(), 2)}

    _rows = [_row("GTV (tumor sólido)", gtv), _row("Edema FLAIR", edema), _row("Total FLAIR (GTV + edema)", flair_total)]
    _wt = monai_store.get((pid, tp))
    if _wt is not None:
        _rows.append(_row("MONAI WT (núcleo + edema)", _wt))
    _fig = ortho_view(
        load_vol(path_of(pid, tp, "flair")), [(edema, "yellow"), (gtv, "red")], sl_x.value, sl_y.value, sl_z.value,
        title="FLAIR · edema estimado (amarillo) + GTV (rojo)", alpha=0.4,
    )
    mo.vstack([_fig, mo.md("Volúmenes en grid de 1 mm³ (n vóxeles / 1000 = cm³):"), pd.DataFrame(_rows)])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 6. Visualización 3D

    ### 6.1 Mayavi (`mlab.contour3d`)
    Iso-superficies del cerebro (translúcido), edema FLAIR (amarillo), MONAI WT opcional (verde) y GTV (rojo), con panel de
    volúmenes y % del cerebro. Se dibujan vía `mlab.pipeline.iso_surface` (lo mismo que hace `contour3d`).

    - **Renderizar imagen:** Mayavi corre *offscreen* (`ETS_TOOLKIT=null`) y se captura con `mlab.screenshot` (imagen fija).
    - **Ventana interactiva:** abre la misma escena en una ventana Qt nativa en un proceso aparte
      (`cerberus_mayavi.py`), donde sí se rota con el mouse.

    Como dicen las notas, Mayavi sirve para prototipos y figuras del reporte; el visor de la app sería web (Cornerstone3D / OHIF).
    """)
    return


@app.cell
def _(DATA_DIR):
    import subprocess
    import sys
    import tempfile

    # Módulo compartido con la ventana nativa (cerberus_mayavi.py, junto al notebook)
    if str(DATA_DIR.parent) not in sys.path:
        sys.path.insert(0, str(DATA_DIR.parent))
    import cerberus_mayavi

    return cerberus_mayavi, subprocess, sys, tempfile


@app.cell
def _(mo):
    run_mayavi = mo.ui.run_button(label="▶ Renderizar imagen (offscreen)", kind="success")
    open_native = mo.ui.run_button(label="🖱 Abrir ventana interactiva Mayavi", kind="neutral")
    mayavi_az = mo.ui.slider(0, 360, step=15, value=45, label="Azimut", show_value=True)
    mayavi_el = mo.ui.slider(0, 180, step=15, value=70, label="Elevación", show_value=True)
    mayavi_ds = mo.ui.dropdown({"2 mm": 2, "3 mm": 3, "4 mm": 4}, value="2 mm", label="Resolución malla")
    mayavi_edema = mo.ui.checkbox(value=True, label="Edema FLAIR (amarillo)")
    mayavi_wt = mo.ui.checkbox(value=False, label="MONAI WT (verde, si se ejecutó)")
    mo.vstack(
        [
            mo.hstack([run_mayavi, open_native], justify="start", gap=1),
            mo.hstack([mayavi_az, mayavi_el, mayavi_ds, mayavi_edema, mayavi_wt], justify="start", gap=2, wrap=True),
        ]
    )
    return mayavi_az, mayavi_ds, mayavi_edema, mayavi_el, mayavi_wt, open_native, run_mayavi


@app.cell
def _(flair_total, mayavi_edema, mayavi_wt, monai_store, pid, tp):
    # Capas opcionales elegidas en los checkboxes (WT solo si MONAI ya corrió para este estudio)
    mv_flair = flair_total if mayavi_edema.value else None
    mv_wt = monai_store.get((pid, tp)) if mayavi_wt.value else None
    mv_title = f"Paciente {pid} / {tp}"
    return mv_flair, mv_title, mv_wt


@app.cell
def _(
    brain,
    cerberus_mayavi,
    gtv,
    mayavi_az,
    mayavi_ds,
    mayavi_el,
    mo,
    mv_flair,
    mv_title,
    mv_wt,
    run_mayavi,
):
    mo.stop(not run_mayavi.value, mo.md("_Pulsa **Renderizar imagen** para la captura, o abre la ventana interactiva._"))
    from mayavi import mlab

    mlab.options.offscreen = True
    _fig = cerberus_mayavi.build_scene(mlab, brain, gtv, mv_flair, mv_wt, step=mayavi_ds.value, title=mv_title)
    mlab.view(azimuth=mayavi_az.value, elevation=mayavi_el.value, distance="auto", figure=_fig)
    _img = mlab.screenshot(figure=_fig, mode="rgb", antialiased=True)
    mlab.close(_fig)
    mo.image(_img, caption=f"Mayavi · {mv_title} · cerebro, edema FLAIR (amarillo), GTV (rojo)", width=800)
    return


@app.cell
def _(brain, cerberus_mayavi, gtv, mo, mv_flair, mv_title, mv_wt, open_native, subprocess, sys, tempfile):
    mo.stop(not open_native.value)
    # El kernel ya importó Mayavi con ETS_TOOLKIT=null; la ventana Qt necesita su propio proceso
    _npz = tempfile.NamedTemporaryFile(prefix="cerberus_", suffix=".npz", delete=False).name
    cerberus_mayavi.save_scene(_npz, brain, gtv, mv_flair, mv_wt, title=mv_title)
    _env = {k: v for k, v in __import__("os").environ.items() if k != "ETS_TOOLKIT"}
    subprocess.Popen([sys.executable, cerberus_mayavi.__file__, _npz], env=_env)
    mo.callout(
        mo.md(
            f"Ventana Mayavi abierta para **{mv_title}** (puede aparecer detrás del navegador). "
            "Arrastra para rotar, rueda para zoom, *shift*+arrastrar para desplazar. Ciérrala cuando termines."
        ),
        kind="success",
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 6.2 Malla interactiva (marching cubes + Plotly)
    Mismas capas que Mayavi, interactivas en el navegador: rota, haz zoom y oculta capas con clic en la leyenda.
    """)
    return


@app.cell
def _(mo):
    plot_edema = mo.ui.checkbox(value=True, label="Edema FLAIR")
    plot_wt = mo.ui.checkbox(value=False, label="MONAI WT (si se ejecutó)")
    mo.hstack([plot_edema, plot_wt], justify="start", gap=2)
    return plot_edema, plot_wt


@app.cell
def _(brain, flair_total, go, gtv, measure, mo, monai_store, np, pid, plot_edema, plot_wt, tp):
    def mesh(mask, step, color, alpha, name):
        _v, _f, _, _ = measure.marching_cubes(mask[::step, ::step, ::step].astype(np.uint8), 0.5, spacing=(step,) * 3)
        return go.Mesh3d(
            x=_v[:, 0], y=_v[:, 1], z=_v[:, 2], i=_f[:, 0], j=_f[:, 1], k=_f[:, 2],
            color=color, opacity=alpha, name=name, showlegend=True, flatshading=True,
        )

    def _vol(m):
        return f"{m.sum() / 1000:.1f} cm³ · {100 * m.sum() / brain.sum():.2f} %"

    _traces = [mesh(brain, 4, "lightgray", 0.12, f"Cerebro {brain.sum() / 1000:.0f} cm³")]
    _wt = monai_store.get((pid, tp)) if plot_wt.value else None
    if _wt is not None:
        _traces.append(mesh(_wt, 2, "seagreen", 0.25, f"MONAI WT {_vol(_wt)}"))
    _title = f"Paciente {pid}/{tp} · GTV {_vol(gtv)}"
    if plot_edema.value and flair_total is not None:
        _traces.append(mesh(flair_total, 2, "gold", 0.35, f"Total GTV+edema {_vol(flair_total)}"))
        _title += f" · TOTAL {_vol(flair_total)}"
    _traces.append(mesh(gtv, 2, "crimson", 0.9, f"GTV {_vol(gtv)}"))

    _fig = go.Figure(_traces)
    _fig.update_layout(
        title=_title,
        height=650,
        margin=dict(l=0, r=0, t=40, b=0),
        legend=dict(x=0, y=0.95),
        scene=dict(aspectmode="data", xaxis_title="x → L (mm)", yaxis_title="y → P (mm)", zaxis_title="z → S (mm)"),
    )
    mo.ui.plotly(_fig)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 7. Conclusiones y siguientes pasos

    - **Datos:** todos los estudios están co-registrados (512×512×208, 0.5×0.5×1 mm, LPS). Las secuencias varían
      entre pacientes → el modelo final debe tolerar canales faltantes.
    - **Volumetría:** el cálculo por vóxeles es directo; **ABC/2 sobreestima** de forma sistemática en GBM.
    - **Segmentación clásica** (Otsu / K-Means): línea base barata, pero confunde realce vascular, plexos y edema.
    - **MONAI SegResNet (BraTS)** sin reentrenar: comparar TC vs GTV; WT sobresegmenta porque incluye edema,
      que el GTV europeo (ESTRO-EANO) excluye.
    - **Siguientes pasos** (de las notas):
        1. Fine-tuning con **nnU-Net** sobre CFB-GBM completo usando el GTV como etiqueta.
        2. Revisión/corrección de etiquetas con **3D Slicer + MONAI Label**.
        3. Visor de la app en **Cornerstone3D / OHIF** (cortes sincronizados + overlay + panel de mediciones).
        4. Registro a MNI + atlas Julich-Brain para reportar áreas de Brodmann afectadas.
        5. Validar contra **RANO 2.0** volumétrico (brecha abierta en la literatura).
    """)
    return


if __name__ == "__main__":
    app.run()
