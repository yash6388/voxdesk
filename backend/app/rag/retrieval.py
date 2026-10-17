import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.rag.embeddings import Embedder

# RRF constant from the original paper (Cormack et al., 2009). Larger k flattens
# the advantage of top ranks; 60 is the widely used default.
RRF_K = 60

# Hybrid search in a single query:
#   semantic: nearest neighbours by cosine distance (pgvector HNSW index)
#   keyword:  Postgres full-text match ranked by ts_rank_cd (GIN index)
#   fused:    Reciprocal Rank Fusion — score = Σ 1 / (k + rank) over both lists,
#             so a chunk ranked well by either method rises, and by both rises most.
# plainto_tsquery ANDs every word; swapping '&' for '|' makes it an OR query,
# which suits natural-language questions where not every word appears in a chunk.
HYBRID_SEARCH_SQL = text("""
WITH semantic AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> CAST(:query_vec AS vector)) AS rank
    FROM chunks
    WHERE business_id = :business_id
    ORDER BY embedding <=> CAST(:query_vec AS vector)
    LIMIT :candidates
),
keyword AS (
    SELECT c.id, ROW_NUMBER() OVER (ORDER BY ts_rank_cd(c.tsv, q.query) DESC) AS rank
    FROM chunks c,
         to_tsquery('english', replace(plainto_tsquery('english', :query)::text, '&', '|'))
             AS q(query)
    WHERE c.business_id = :business_id AND c.tsv @@ q.query
    ORDER BY ts_rank_cd(c.tsv, q.query) DESC
    LIMIT :candidates
)
SELECT c.id, c.content, c.document_id, d.filename, c.chunk_index,
       COALESCE(1.0 / (:rrf_k + s.rank), 0) + COALESCE(1.0 / (:rrf_k + k.rank), 0) AS score,
       s.rank AS semantic_rank, k.rank AS keyword_rank
FROM semantic s
FULL OUTER JOIN keyword k ON s.id = k.id
JOIN chunks c ON c.id = COALESCE(s.id, k.id)
JOIN documents d ON d.id = c.document_id
ORDER BY score DESC
LIMIT :top_k
""")


@dataclass
class RetrievedChunk:
    id: str
    content: str
    document_id: str
    filename: str
    chunk_index: int
    score: float
    semantic_rank: int | None
    keyword_rank: int | None


async def hybrid_search(
    session: AsyncSession,
    embedder: Embedder,
    business_id: uuid.UUID,
    query: str,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    s = get_settings()
    query_vec = await embedder.embed_query(query)
    result = await session.execute(
        HYBRID_SEARCH_SQL,
        {
            # pgvector's text format: "[0.1,0.2,...]"
            "query_vec": "[" + ",".join(map(str, query_vec)) + "]",
            "business_id": business_id,
            "query": query,
            "candidates": s.retrieval_candidates,
            "top_k": top_k or s.retrieval_top_k,
            "rrf_k": RRF_K,
        },
    )
    return [
        RetrievedChunk(
            id=str(row.id),
            content=row.content,
            document_id=str(row.document_id),
            filename=row.filename,
            chunk_index=row.chunk_index,
            score=float(row.score),
            semantic_rank=row.semantic_rank,
            keyword_rank=row.keyword_rank,
        )
        for row in result
    ]
