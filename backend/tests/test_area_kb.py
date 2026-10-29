"""Tests de la base curada de funciones por área (§13, ticket B10)."""

import pytest

from cerberus_api import area_kb
from cerberus_api.area_kb import AreaInfo, area_info, functions_for, load_area_kb

BA_NUMBERS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, *range(17, 26), *range(27, 48)]
SUBCORTICAL = [
    "Dentate",
    "Putamen",
    "Amygdala",
    "Pulvinar",
    "Hippocampus",
    "Optic Tract",
    "Red Nucleus",
    "Caudate Body",
    "Caudate Head",
    "Caudate Tail",
    "Hypothalamus",
    "Corpus Callosum",
    "Mammillary Body",
    "Midline Nucleus",
    "Substania Nigra",
    "Anterior Nucleus",
    "Anterior Commissure",
    "Subthalamic Nucleus",
    "Medial Dorsal Nucleus",
    "Medial Geniculum Body",
    "Lateral Dorsal Nucleus",
    "Lateral Geniculum Body",
    "Medial Globus Pallidus",
    "Lateral Globus Pallidus",
    "Ventral Lateral Nucleus",
    "Ventral Anterior Nucleus",
    "Lateral Posterior Nucleus",
    "Ventral Posterior Medial Nucleus",
    "Ventral Posterior Lateral Nucleus",
]
ATLAS_NAMES = [f"Brodmann area {n}" for n in BA_NUMBERS] + SUBCORTICAL


def test_atlas_name_list_has_71_regions():
    assert len(BA_NUMBERS) == 42
    assert len(SUBCORTICAL) == 29
    assert len(ATLAS_NAMES) == 71
    assert len(set(ATLAS_NAMES)) == 71


def test_kb_covers_exactly_the_atlas_names():
    assert set(load_area_kb()) == set(ATLAS_NAMES)


@pytest.mark.parametrize("name", ATLAS_NAMES)
def test_entry_fields_are_valid(name: str):
    info = load_area_kb()[name]
    assert info.name_es.strip()
    assert info.kind in ("cortical", "subcortical")
    assert info.kind == ("cortical" if name.startswith("Brodmann area") else "subcortical")
    assert 1 <= len(info.functions) <= 5
    assert all(f.strip() for f in info.functions + info.functions_left + info.functions_right)
    assert info.sources and all(s.strip() for s in info.sources)


def test_broca_is_left_lateralized():
    for name in ("Brodmann area 44", "Brodmann area 45"):
        left = " ".join(functions_for(name, "izquierdo")).lower()
        right = " ".join(functions_for(name, "derecho")).lower()
        assert "lenguaje" in left and "broca" in left
        assert "broca" not in right


def test_eloquent_flags():
    assert load_area_kb()["Brodmann area 4"].eloquent
    assert load_area_kb()["Brodmann area 44"].eloquent
    assert not load_area_kb()["Brodmann area 10"].eloquent


def test_unknown_name():
    assert functions_for("Background", "izquierdo") == []
    assert functions_for("No existe", "derecho") == []
    assert area_info("No existe") is None


def test_functions_for_side_first_and_dedup(monkeypatch: pytest.MonkeyPatch):
    fake = {
        "X": AreaInfo(
            name_es="X",
            kind="cortical",
            functions=["común", "lenguaje"],
            functions_left=["lenguaje", "lectura"],
            sources=["s"],
        )
    }
    monkeypatch.setattr(area_kb, "load_area_kb", lambda: fake)
    assert functions_for("X", "izquierdo") == ["lenguaje", "lectura", "común"]
    assert functions_for("X", "derecho") == ["común", "lenguaje"]


def test_load_is_cached():
    assert load_area_kb() is load_area_kb()
