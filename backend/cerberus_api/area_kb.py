"""Base curada de funciones por área de Brodmann / estructura subcortical (§13, ticket B10).

Contenido **educativo**: funciones clásicas de libros de texto, en español y con fuentes. Es una
estimación basada en atlas; no sustituye fMRI, tractografía ni mapeo cortical intraoperatorio.

Las claves son los nombres exactos del atlas Talairach nivel `ba` de nilearn (71 regiones), incluida su
ortografía original (ej. "Substania Nigra").
"""

import json
from functools import lru_cache
from importlib.resources import files

from pydantic import BaseModel

from cerberus_api.schemas import AreaKind, Domain, Hemisphere


class AreaInfo(BaseModel):
    """Entrada de `data/area_functions.json`."""

    name_es: str
    kind: AreaKind
    functions: list[str]  # funciones comunes a ambos hemisferios
    functions_left: list[str] = []  # solo cuando la lateralización está bien establecida
    functions_right: list[str] = []
    # Dominios funcionales (§14). Atención espacial / integración multimodal / alerta / olfato → "otro".
    domains: list[Domain] = []
    domains_left: list[Domain] = []
    domains_right: list[Domain] = []
    eloquent: bool = False  # lesión → déficit neurológico evidente
    sources: list[str]


@lru_cache(maxsize=1)
def load_area_kb() -> dict[str, AreaInfo]:
    """Carga (una sola vez) la base de funciones empaquetada con `cerberus_api`."""
    resource = files("cerberus_api") / "data" / "area_functions.json"
    raw: dict[str, dict[str, object]] = json.loads(resource.read_text(encoding="utf-8"))
    return {name: AreaInfo.model_validate(entry) for name, entry in raw.items()}


def area_info(name: str) -> AreaInfo | None:
    """Devuelve la entrada de un área por su nombre del atlas, o `None` si no existe."""
    return load_area_kb().get(name)


def functions_for(name: str, hemisphere: Hemisphere) -> list[str]:
    """Funciones del área en un hemisferio: primero las específicas del lado y luego las comunes.

    Sin duplicados y conservando el orden. Un nombre desconocido devuelve `[]`.
    """
    info = area_info(name)
    if info is None:
        return []
    side = info.functions_left if hemisphere == "izquierdo" else info.functions_right
    return list(dict.fromkeys([*side, *info.functions]))


def domains_for(name: str, hemisphere: Hemisphere) -> list[Domain]:
    """Dominios funcionales del área en un hemisferio: primero los del lado y luego los generales.

    Sin duplicados y conservando el orden. Un nombre desconocido devuelve `[]`.
    """
    info = area_info(name)
    if info is None:
        return []
    side = info.domains_left if hemisphere == "izquierdo" else info.domains_right
    return list(dict.fromkeys([*side, *info.domains]))
