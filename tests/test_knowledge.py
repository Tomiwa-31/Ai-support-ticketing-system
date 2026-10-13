"""Knowledge store: chunking, masking before embedding, filtered search, the vector column type, the Voyage client."""
import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.knowledge import embeddings, load_samples, store
from app.knowledge.chunking import MAX_CHARS, chunk_article
from app.knowledge.samples import SAMPLES
from app.knowledge.vector import EMBEDDING_DIM, Embedding
from app.models import KnowledgeChunk
from tests.fakes import FakeEmbedder

ORG = 1


async def _add(session, emb, title, body, product="credipay", status="published", org_id=ORG):
    return await store.add_article(
        session, org_id=org_id, product=product, title=title, body=body, status=status, embedder=emb
    )


async def _search(session, emb, text, product="credipay", org_id=ORG, model=None, k=4):
    return await store.search(
        session, org_id=org_id, product=product, query_vector=FakeEmbedder.vector(text),
        embedding_model=model or emb.model, k=k,
    )


# ---- chunking -------------------------------------------------------------------------------------------------

def test_short_article_is_one_chunk_that_starts_with_the_title():
    assert chunk_article("Title", "One paragraph.") == ["Title\n\nOne paragraph."]


def test_long_article_is_split_and_no_chunk_is_over_the_limit():
    body = "\n\n".join(f"Paragraph {i}. " + "word " * 80 for i in range(6))
    chunks = chunk_article("T", body)
    assert len(chunks) > 1
    assert all(len(c) <= MAX_CHARS + len("T\n\n") for c in chunks)
    assert "Paragraph 5" in chunks[-1]


def test_a_single_huge_paragraph_is_still_cut():
    chunks = chunk_article("T", "x" * 5000)
    assert len(chunks) >= 5 and all(len(c) <= MAX_CHARS + 3 for c in chunks)


def test_empty_body_still_gives_one_chunk():
    assert chunk_article("Only a title", "   ") == ["Only a title"]


# ---- the column type ------------------------------------------------------------------------------------------

def test_embedding_type_round_trips_and_pg_sql_uses_vector_casts():
    t = Embedding(3)
    assert t.process_bind_param([1, 2.5, 3], None) == "[1.0, 2.5, 3.0]"
    assert t.process_result_value("[0.1,0.2,0.3]", None) == [0.1, 0.2, 0.3]
    assert t.process_bind_param(None, None) is None and t.process_result_value(None, None) is None


def test_postgres_search_query_uses_pgvector_cosine_distance():
    sql = str(store.build_pg_search(1, "credipay", [0.1] * 4, "voyage-4", 4).compile(dialect=postgresql.dialect()))
    assert "<=>" in sql and "vector(1024)" in sql and "ORDER BY" in sql
    assert "knowledge_articles.status" in sql and "knowledge_chunks.org_id" in sql
    assert "knowledge_chunks.embedding_model" in sql and "knowledge_chunks.product IN" in sql


# ---- adding articles ------------------------------------------------------------------------------------------

async def test_vectors_are_stored_with_their_model_and_come_back_as_lists(session):
    emb = FakeEmbedder()
    article = await _add(session, emb, "Refunds", "Refunds take five days.")
    chunk = (await session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.article_id == article.id))).one()
    assert chunk.embedding_model == "fake-embed" and len(chunk.embedding) == EMBEDDING_DIM
    assert article.published_at is not None


async def test_drafts_have_no_published_date_and_bad_status_is_refused(session):
    emb = FakeEmbedder()
    draft = await _add(session, emb, "Draft", "text", status="draft")
    assert draft.published_at is None
    with pytest.raises(ValueError):
        await _add(session, emb, "Bad", "text", status="live")


async def test_text_is_masked_before_it_is_embedded_but_stored_as_written(session):
    emb = FakeEmbedder()
    body = "Email billing@example.com or call +234 801 234 5678. Test card 4111 1111 1111 1111."
    article = await _add(session, emb, "Contacts", body)
    embedded = " ".join(emb.calls[0]["texts"])
    for raw in ("billing@example.com", "234 801", "4111"):
        assert raw not in embedded
    assert "[EMAIL_1]" in embedded and "[CARD_1]" in embedded
    assert emb.calls[0]["input_type"] == "document"
    assert article.body == body  # the article itself is untouched


# ---- searching ------------------------------------------------------------------------------------------------

async def test_best_matching_article_ranks_first(session):
    emb = FakeEmbedder()
    await _add(session, emb, "Duplicate charge", "A card charged twice is refunded within five days.")
    await _add(session, emb, "Password reset", "Use the forgot password link to reset your password.")
    hits = await _search(session, emb, "I was charged twice, refund the duplicate card charge")
    assert hits[0].title == "Duplicate charge" and hits[0].score > hits[1].score


async def test_only_published_articles_are_found(session):
    emb = FakeEmbedder()
    await _add(session, emb, "Draft policy", "charged twice refund duplicate", status="draft")
    await _add(session, emb, "Review policy", "charged twice refund duplicate", status="in_review")
    await _add(session, emb, "Live policy", "charged twice refund duplicate", status="published")
    titles = [h.title for h in await _search(session, emb, "charged twice refund duplicate")]
    assert titles == ["Live policy"]


async def test_search_is_filtered_by_product_and_includes_all_products_articles(session):
    emb = FakeEmbedder()
    await _add(session, emb, "Credipay refunds", "refund policy", product="credipay")
    await _add(session, emb, "FinSaaS refunds", "refund policy", product="finsaas")
    await _add(session, emb, "Everyone refunds", "refund policy", product="all")
    assert {h.title for h in await _search(session, emb, "refund policy", product="credipay")} == {
        "Credipay refunds", "Everyone refunds",
    }
    assert {h.title for h in await _search(session, emb, "refund policy", product="finsaas")} == {
        "FinSaaS refunds", "Everyone refunds",
    }
    # No product known: only articles that apply to every product.
    assert {h.title for h in await _search(session, emb, "refund policy", product=None)} == {"Everyone refunds"}


async def test_search_never_crosses_organisations(session):
    from app.models import Organization

    other = Organization(name="Other Co")
    session.add(other)
    await session.commit()
    emb = FakeEmbedder()
    await _add(session, emb, "Other org secret", "refund policy", org_id=other.id)
    assert await _search(session, emb, "refund policy") == []
    assert [h.title for h in await _search(session, emb, "refund policy", org_id=other.id)] == ["Other org secret"]


async def test_vectors_from_another_embedding_model_are_ignored(session):
    old, new = FakeEmbedder(model="old-model"), FakeEmbedder(model="new-model")
    await _add(session, old, "Old vectors", "refund policy")
    assert await _search(session, new, "refund policy") == []
    assert [h.title for h in await _search(session, old, "refund policy")] == ["Old vectors"]


async def test_k_limits_the_number_of_hits(session):
    emb = FakeEmbedder()
    for i in range(5):
        await _add(session, emb, f"Article {i}", f"refund policy number {i}")
    assert len(await _search(session, emb, "refund policy", k=2)) == 2


# ---- the Voyage client (against a mocked server: no key, no network) ------------------------------------------

_REAL_CLIENT = httpx2.AsyncClient


def _voyage(monkeypatch, handler):
    monkeypatch.setattr(
        embeddings.httpx2, "AsyncClient", lambda **kw: _REAL_CLIENT(transport=httpx2.MockTransport(handler), **kw)
    )
    return embeddings.VoyageEmbedder("test-key", "voyage-4")


def _ok_response(request, dim=EMBEDDING_DIM):
    import json

    body = json.loads(request.content)
    # Return vectors out of order on purpose: the client must sort by index.
    data = [{"index": i, "embedding": [float(i)] * dim} for i in range(len(body["input"]))][::-1]
    return httpx2.Response(200, json={"data": data, "model": body["model"], "usage": {"total_tokens": len(body["input"]) * 3}})


async def test_voyage_request_shape_ordering_and_tokens(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return _ok_response(request)

    emb = _voyage(monkeypatch, handler)
    result = await emb.embed(["a", "b", "c"], input_type="query")
    import json

    assert len(seen) == 1 and seen[0].headers["authorization"] == "Bearer test-key"
    assert json.loads(seen[0].content) == {"input": ["a", "b", "c"], "model": "voyage-4", "input_type": "query"}
    assert [v[0] for v in result.vectors] == [0.0, 1.0, 2.0] and result.total_tokens == 9 and result.model == "voyage-4"


async def test_voyage_batches_large_inputs(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return _ok_response(request)

    emb = _voyage(monkeypatch, handler)
    result = await emb.embed([f"t{i}" for i in range(embeddings.BATCH_SIZE + 6)], input_type="document")
    assert len(calls) == 2 and len(result.vectors) == embeddings.BATCH_SIZE + 6


async def test_voyage_errors_become_embedding_errors(monkeypatch):
    emb = _voyage(monkeypatch, lambda request: httpx2.Response(401, text="invalid api key"))
    with pytest.raises(embeddings.EmbeddingError, match="401"):
        await emb.embed(["a"], input_type="query")

    emb = _voyage(monkeypatch, lambda request: _ok_response(request, dim=256))
    with pytest.raises(embeddings.EmbeddingError, match="1024"):
        await emb.embed(["a"], input_type="query")


async def test_rate_limit_is_retried_only_when_asked_to(monkeypatch):
    waits, calls = [], []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(embeddings.asyncio, "sleep", fake_sleep)

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx2.Response(429, text="reduced rate limits", headers={"retry-after": "7"})
        return _ok_response(request)

    patient = _voyage(monkeypatch, handler)
    patient._rate_limit_retries = 4
    result = await patient.embed(["a"], input_type="document")
    assert len(calls) == 3 and waits == [7.0, 7.0] and len(result.vectors) == 1

    # Live traffic does not wait: the first 429 is reported at once (the AI worker then degrades).
    calls.clear()
    waits.clear()
    impatient = _voyage(monkeypatch, lambda request: httpx2.Response(429, text="reduced rate limits"))
    with pytest.raises(embeddings.EmbeddingError, match="429"):
        await impatient.embed(["a"], input_type="query")
    assert waits == []


async def test_rate_limit_gives_up_after_the_retries(monkeypatch):
    async def fake_sleep(seconds):
        pass

    monkeypatch.setattr(embeddings.asyncio, "sleep", fake_sleep)
    seen = []
    emb = _voyage(monkeypatch, lambda request: (seen.append(1), httpx2.Response(429, text="slow down"))[1])
    emb._rate_limit_retries = 2
    with pytest.raises(embeddings.EmbeddingError, match="429"):
        await emb.embed(["a"], input_type="document")
    assert len(seen) == 3


def test_no_voyage_key_means_no_embedder():
    with pytest.raises(embeddings.EmbeddingError, match="VOYAGE_API_KEY"):
        embeddings.get_embedder()


# ---- demo articles and loader ---------------------------------------------------------------------------------

def test_sample_articles_are_well_formed():
    assert {s["product"] for s in SAMPLES} == {"credipay", "finsaas", "finsaas-lending", "all"}
    titles = [(s["product"], s["title"]) for s in SAMPLES]
    assert len(titles) == len(set(titles))
    assert all(len(s["body"]) > 100 for s in SAMPLES)


async def test_add_articles_uses_one_embedding_request(session):
    emb = FakeEmbedder()
    items = [{"product": "credipay", "title": f"T{i}", "body": f"body number {i}"} for i in range(5)]
    articles = await store.add_articles(session, items, org_id=ORG, status="published", embedder=emb)
    assert len(articles) == 5 and len(emb.calls) == 1 and len(emb.calls[0]["texts"]) == 5


async def test_loader_adds_the_samples_once_in_one_request_and_finishes_a_partial_load(session):
    emb = FakeEmbedder()
    # A previous run that was cut off by rate limiting left some articles behind.
    await store.add_articles(session, [dict(s) for s in SAMPLES[:3]], org_id=ORG, status="published", embedder=emb)
    emb.calls.clear()
    assert await load_samples.load(emb) == (len(SAMPLES) - 3, 3)
    assert len(emb.calls) == 1  # all remaining articles in a single request
    emb.calls.clear()
    assert await load_samples.load(emb) == (0, len(SAMPLES))
    assert emb.calls == []  # nothing to do, nothing sent
    assert [h.title for h in await _search(session, emb, "loan disbursement delayed not received", product="finsaas-lending", k=1)] == [
        "Loan disbursement delays"
    ]


# ---- HTTP -----------------------------------------------------------------------------------------------------

async def test_knowledge_api_lists_and_searches(session):
    import httpx

    from app.main import app

    emb = FakeEmbedder()
    embeddings.set_embedder(emb)
    await load_samples.load(emb)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        articles = (await client.get("/knowledge/articles", params={"product": "finsaas-lending"})).json()
        assert len(articles) == 3 and all(a["status"] == "published" and a["chunks"] >= 1 for a in articles)

        r = await client.get("/knowledge/search", params={"q": "my loan disbursement has not arrived, call 555-123-4567", "product": "finsaas-lending"})
        assert r.status_code == 200 and r.json()[0]["title"] == "Loan disbursement delays"
        assert "555-123-4567" not in " ".join(emb.calls[-1]["texts"])  # the query was masked first
        assert emb.calls[-1]["input_type"] == "query"


async def test_knowledge_search_reports_a_missing_key(session):
    import httpx

    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/knowledge/search", params={"q": "anything"})
        assert r.status_code == 503 and "VOYAGE_API_KEY" in r.json()["detail"]
