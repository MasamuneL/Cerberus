"""Carga tipada de NIfTI.

`nib.load` está anotado como `FileBasedImage`, que no expone `get_fdata`, `affine` ni `header.get_zooms`
para pyright. Usa siempre `load_nifti` en el backend en lugar de `nib.load`.
"""

from pathlib import Path

import nibabel as nib


def load_nifti(path: str | Path) -> nib.Nifti1Image:
    """Carga un `.nii`/`.nii.gz` y garantiza que sea NIfTI-1 (lanza `ValueError` si no)."""
    img = nib.load(str(path))
    if not isinstance(img, nib.Nifti1Image):
        raise ValueError(f"No es un NIfTI-1: {Path(path).name}")
    return img
