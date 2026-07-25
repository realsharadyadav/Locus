from backend.app.vector_store import chunk_text, embed_text


def test_chunk_text_uses_overlap_and_preserves_content():
    text = " ".join(f"sentence {index}." for index in range(120))
    chunks = chunk_text(text, chunk_chars=160, overlap=30)
    assert len(chunks) > 1
    assert chunks[0].startswith("sentence 0")
    assert "sentence 119" in chunks[-1]


def test_embed_text_is_deterministic_and_normalized():
    first = embed_text("semantic local search")
    second = embed_text("semantic local search")
    magnitude = sum(value * value for value in first) ** 0.5
    assert first == second
    assert 0.99 < magnitude < 1.01
