import pytest

from app.config import ConfigError, load_config, read_secret

VALID = """
documents:
  - grist_doc_id: AbCdEfGh1234
    nom: Test
    demarches:
      - numero: 149930
        nom: Western Pony Club
        dn_token: DN_TOKEN_TEST
"""


def write(tmp_path, text):
    p = tmp_path / "demarches.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_config_valide(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    d = cfg.document("AbCdEfGh1234").demarche(149930)
    assert d.table == "Demarche_149930_dossiers"
    assert cfg.document("inconnu12345") is None


def test_secret_manquant(tmp_path, monkeypatch):
    monkeypatch.delenv("DN_TOKEN_TEST")
    with pytest.raises(ConfigError, match="DN_TOKEN_TEST"):
        load_config(write(tmp_path, VALID))


def test_secret_par_fichier(tmp_path, monkeypatch):
    monkeypatch.delenv("DN_TOKEN_TEST")
    f = tmp_path / "tok"
    f.write_text("secret-fichier\n")
    monkeypatch.setenv("DN_TOKEN_TEST_FILE", str(f))
    assert read_secret("DN_TOKEN_TEST") == "secret-fichier"


@pytest.mark.parametrize("bad", [
    VALID + "inattendu: 1\n",                                   # clé inconnue
    VALID.replace("DN_TOKEN_TEST", "dn-token-test"),            # nom de secret invalide
    VALID.replace("AbCdEfGh1234", "../../etc"),                 # docId invalide
    VALID + "        table_dossiers: 'x\"; DROP'\n",            # table invalide
    VALID + "      - numero: 149930\n        nom: doublon\n        dn_token: DN_TOKEN_TEST\n",
    VALID + "dn_api_url: http://demarche.numerique.gouv.fr/api/v2/graphql\n",  # pas https
])
def test_config_invalide(tmp_path, bad):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, bad))
