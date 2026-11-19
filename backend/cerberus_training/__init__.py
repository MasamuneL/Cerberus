"""Pipeline de fine-tuning de SegResNet sobre CFB-GBM (docs/PLAN_PIPELINE_FINETUNING.md).

Paquete hermano de `cerberus_api`. No lo importa la app web ni los workers arq. Importar este paquete no
carga torch ni MONAI: esas dependencias se importan de forma perezosa dentro de cada subcomando.
"""

__version__ = "0.1.0"
