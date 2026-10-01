"""Pasta por gênero + slug datado AAAAMMDD_titulo."""

import json
import os
import re

from curio.pipeline import _paths_for_slug, iter_projects, video_paths
from curio.slug import (find_project_root, project_dir, slugify,
                        slugify_with_timestamp, unique_slug)


def test_slug_dated_e_data_hoje_titulo():
    from datetime import datetime
    hoje = datetime.now().strftime("%Y%m%d")
    slug = slugify_with_timestamp("Fale sobre São Tomás de Aquino!")
    assert re.fullmatch(r"\d{8}_[a-z0-9-]+", slug), slug
    assert slug.startswith(hoje + "_")
    assert "sao-tomas" in slug


def test_project_dir_por_genero_e_plano_sem_genero():
    assert project_dir("output", "people", "s") == os.path.join(
        "output", "people", "s")
    assert project_dir("output", "", "s") == os.path.join("output", "s")


def test_video_paths_aninha_com_genero_e_mantem_legado():
    assert video_paths("out", "s", "people").root == os.path.join(
        "out", "people", "s")
    assert video_paths("out", "s").root == os.path.join("out", "s")
    assert video_paths("out", "s", "people").metadata_json.endswith(
        os.path.join("people", "s", "metadata.json"))


def test_find_project_root_acha_novo_e_legado(tmp_path):
    out = str(tmp_path)
    novo = os.path.join(out, "people", "20261001_teste")
    legado = os.path.join(out, "antigo")
    os.makedirs(novo)
    os.makedirs(legado)
    assert find_project_root(out, "20261001_teste") == novo
    assert find_project_root(out, "antigo") == legado
    assert find_project_root(out, "inexistente") is None


def test_unique_slug_reutiliza_rerun_e_sufixa_colisao(tmp_path):
    out = str(tmp_path)
    root = os.path.join(out, "people", "20261001_titulo")
    os.makedirs(root)
    with open(os.path.join(root, "metadata.json"), "w",
               encoding="utf-8") as fh:
        json.dump({"input": "mesma ideia"}, fh)
    assert unique_slug(out, "people", "20261001_titulo",
                       "mesma ideia") == "20261001_titulo"
    assert unique_slug(out, "people", "20261001_titulo",
                       "outra ideia") == "20261001_titulo-2"
    assert unique_slug(out, "people", "livre", "x") == "livre"


def test_paths_for_slug_e_iter_projects(tmp_path):
    out = str(tmp_path)
    novo = os.path.join(out, "science", "20261001_balde")
    legado = os.path.join(out, "antigo")
    os.makedirs(os.path.join(novo, "script"))
    os.makedirs(legado)
    for root in (novo, legado):
        with open(os.path.join(root, "metadata.json"), "w",
                   encoding="utf-8") as fh:
            json.dump({"input": "i"}, fh)
    slug, paths = _paths_for_slug(out, "20261001_balde")
    assert paths.root == novo
    slug, paths = _paths_for_slug(out, "science/20261001_balde")
    assert paths.root == novo
    _, paths = _paths_for_slug(out, "antigo")
    assert paths.root == legado
    refs = [ref for ref, _root in iter_projects(out)]
    assert refs == ["antigo", "science/20261001_balde"]
    try:
        _paths_for_slug(out, "fantasma")
    except FileNotFoundError as exc:
        assert "fantasma" in str(exc)
    else:
        raise AssertionError("devia levantar FileNotFoundError")


def test_slugify_base_intacto():
    assert slugify("De onde veio a palavra salário?") == "de-onde-veio-a-palavra-salario"
