from rag_lc.retrieve import _rrf_fuse, _tokenize
from langchain_core.documents import Document


def test_tokenize_mixed():
    toks = _tokenize("NFG 风险管理 SLA")
    assert "nfg" in toks
    assert "风" in toks


def test_rrf_fuse_prefers_overlap():
    dense = [
        Document(page_content="alpha", metadata={"doc_id": "a"}),
        Document(page_content="beta", metadata={"doc_id": "b"}),
    ]
    bm25 = [
        Document(page_content="beta", metadata={"doc_id": "b"}),
        Document(page_content="gamma", metadata={"doc_id": "c"}),
    ]
    fused = _rrf_fuse([dense, bm25], top_k=3)
    texts = [d.page_content for d in fused]
    assert texts[0] == "beta"
    assert set(texts) == {"alpha", "beta", "gamma"}
