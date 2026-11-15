import httpx
import pytest

from app.security import AuthError, LimiteurDebit, VerificateurJetons, verifier_base_url

from .conftest import BASE, DOC, TOKEN, Recorder

HOST = "grist.numerique.gouv.fr"


@pytest.mark.parametrize("url", [BASE, f"https://{HOST}/api/docs/{DOC}"])
def test_base_url_valide(url):
    assert verifier_base_url(url, HOST) == DOC


@pytest.mark.parametrize("url", [
    BASE.replace("https", "http"),
    BASE.replace(HOST, "evil.example"),
    BASE.replace(HOST, HOST + ".evil.example"),
    BASE.replace(HOST, HOST + ":8443"),
    BASE.replace("https://", "https://user:pw@"),
    BASE + "?x=1",
    BASE + "#frag",
    BASE + "/../../other",
    f"https://{HOST}/o/x/api/docs/abc",
    f"https://{HOST}/api/docs/{DOC}/tables",
])
def test_base_url_refusee(url):
    with pytest.raises(AuthError):
        verifier_base_url(url, HOST)


def grist_ok(request: httpx.Request) -> httpx.Response:
    assert request.url.params["auth"] == TOKEN
    return httpx.Response(200, json={"tables": [{"id": "T"}]})


@pytest.mark.anyio
async def test_jeton_valide_puis_cache(config):
    rec = Recorder(grist_ok)
    v = VerificateurJetons(config, transport=rec.transport())
    qui = await v.verifier(TOKEN, BASE)
    assert qui.document.grist_doc_id == DOC
    await v.verifier(TOKEN, BASE)
    assert len(rec.requests) == 1  # deuxième appel servi par le cache


@pytest.mark.anyio
async def test_document_non_configure_sans_appel_reseau(config):
    rec = Recorder(grist_ok)
    v = VerificateurJetons(config, transport=rec.transport())
    with pytest.raises(AuthError) as e:
        await v.verifier(TOKEN, BASE.replace(DOC, "AutreDoc1234"))
    assert e.value.status == 403
    assert rec.requests == []


@pytest.mark.anyio
@pytest.mark.parametrize("token", [None, "", "court", "a b" * 10, "x" * 2000])
async def test_jeton_mal_forme(config, token):
    v = VerificateurJetons(config, transport=Recorder(grist_ok).transport())
    with pytest.raises(AuthError):
        await v.verifier(token, BASE)


@pytest.mark.anyio
async def test_jeton_refuse_par_grist(config):
    v = VerificateurJetons(config, transport=Recorder(lambda r: httpx.Response(401, json={"error": "no"})).transport())
    with pytest.raises(AuthError) as e:
        await v.verifier(TOKEN, BASE)
    assert e.value.status == 401


def test_limiteur():
    lim = LimiteurDebit(par_minute=3)
    for _ in range(3):
        lim.verifier("doc")
    with pytest.raises(AuthError) as e:
        lim.verifier("doc")
    assert e.value.status == 429
    lim.verifier("autre")  # compteur par document
