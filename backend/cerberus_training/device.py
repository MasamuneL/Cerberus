"""Comprobación del dispositivo de cómputo (docs/TRAINING.md).

torch se importa dentro de `probe_device`, nunca al importar el módulo, y su ausencia o una instalación rota
(`ImportError`, `OSError` por bibliotecas CUDA que no cargan) no es un error: el informe lo indica y sigue.
"""

import json
import platform
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class DeviceReport:
    """Resumen serializable del entorno de ejecución."""

    python: str
    platform: str
    torch_version: str | None
    torch_cuda_build: str | None
    cuda_available: bool
    cudnn_version: int | None = None
    gpus: list[str] = field(default_factory=list)
    # Capability de cada GPU en formato "sm_89", y arquitecturas para las que se compiló esta rueda de torch.
    gpu_archs: list[str] = field(default_factory=list)
    compiled_archs: list[str] = field(default_factory=list)
    bf16_supported: bool = False
    note: str = ""
    # Avisos no fatales (p. ej. la GPU tiene una capability que la rueda no incluye).
    warnings: list[str] = field(default_factory=list)


def _arch_warnings(gpu_archs: list[str], compiled: list[str]) -> list[str]:
    """Avisa de las GPU cuya capability exacta (`sm_XY`) no está entre las arquitecturas compiladas."""
    warnings: list[str] = []
    has_ptx = any(a.startswith("compute_") for a in compiled)
    for index, arch in enumerate(gpu_archs):
        if arch in compiled:
            continue
        extra = " Solo habría compilación JIT desde PTX (lenta y no garantizada)." if has_ptx else ""
        warnings.append(
            f"La GPU {index} es {arch}, que no está entre las arquitecturas de esta rueda de torch "
            f"({', '.join(compiled) or 'ninguna'}).{extra} Use un build CUDA más reciente (ver docs/TRAINING.md)."
        )
    return warnings


def probe_device() -> DeviceReport:
    """Informa versión de torch, build CUDA, GPUs y arquitecturas compiladas. No lanza si falta torch o CUDA."""
    py, plat = platform.python_version(), platform.platform()
    try:
        import torch
    except (ImportError, OSError) as exc:
        detail = "torch no está instalado en este entorno" if isinstance(exc, ImportError) else f"torch no cargó: {exc}"
        return DeviceReport(
            python=py, platform=plat, torch_version=None, torch_cuda_build=None, cuda_available=False, note=detail
        )
    cuda_build = torch.version.cuda
    available = bool(torch.cuda.is_available())
    gpus: list[str] = []
    gpu_archs: list[str] = []
    compiled: list[str] = []
    if available:
        count = torch.cuda.device_count()
        gpus = [torch.cuda.get_device_name(i) for i in range(count)]
        gpu_archs = [
            f"sm_{major}{minor}" for major, minor in (torch.cuda.get_device_capability(i) for i in range(count))
        ]
        compiled = list(torch.cuda.get_arch_list())
    if available:
        note = "CUDA disponible"
    elif cuda_build is None:
        note = "torch con ruedas CPU: use el entorno CUDA de training-env/ para entrenar en GPU"
    else:
        note = "torch con build CUDA, pero no hay GPU o controlador utilizable"
    return DeviceReport(
        python=py,
        platform=plat,
        torch_version=torch.__version__,
        torch_cuda_build=cuda_build,
        cuda_available=available,
        cudnn_version=torch.backends.cudnn.version() if available else None,
        gpus=gpus,
        gpu_archs=gpu_archs,
        compiled_archs=compiled,
        bf16_supported=bool(available and torch.cuda.is_bf16_supported()),
        note=note,
        warnings=_arch_warnings(gpu_archs, compiled),
    )


def format_report(report: DeviceReport, as_json: bool = False) -> str:
    """Texto legible (o JSON) del informe de dispositivo."""
    if as_json:
        return json.dumps(asdict(report), indent=2, ensure_ascii=False)
    lines = [
        f"Python:          {report.python}",
        f"Plataforma:      {report.platform}",
        f"torch:           {report.torch_version or 'no instalado'}",
        f"Build CUDA:      {report.torch_cuda_build or 'ninguno (ruedas CPU)'}",
        f"CUDA disponible: {'sí' if report.cuda_available else 'no'}",
    ]
    if report.cuda_available:
        lines.append(f"cuDNN:           {report.cudnn_version}")
        lines.append(f"bf16:            {'sí' if report.bf16_supported else 'no'}")
        lines.extend(
            f"GPU {i}:           {name} ({arch})"
            for i, (name, arch) in enumerate(zip(report.gpus, report.gpu_archs, strict=True))
        )
        lines.append(f"Arquitecturas:   {', '.join(report.compiled_archs) or 'ninguna'}")
    lines.append(f"Estado:          {report.note}")
    lines.extend(f"AVISO:           {w}" for w in report.warnings)
    return "\n".join(lines)
