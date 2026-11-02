from trust_engine.contract_intelligence.ingestion import chunk_pages,normalize_text

def test_normalize_text_removes_extraction_noise():
    assert normalize_text("  hello\x00  world \n\n\n next ") == "hello world \n\n next"

def test_chunk_pages_preserves_page_metadata_and_overlap():
    pages=[{"page_number":4,"text":" ".join(f"word{i}" for i in range(25))}]
    chunks=chunk_pages(pages,"C-1","agreement.pdf",chunk_size=10,overlap=2)
    assert len(chunks)==3
    assert all(c.page_number==4 for c in chunks)
    assert chunks[0].chunk_text.split()[-2:]==chunks[1].chunk_text.split()[:2]

def test_chunking_rejects_invalid_overlap():
    try: chunk_pages([],"C-1","x.pdf",chunk_size=10,overlap=10)
    except ValueError: return
    raise AssertionError("invalid overlap should fail")
