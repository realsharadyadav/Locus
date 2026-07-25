from dataclasses import dataclass


@dataclass(frozen=True)
class ModeConfig:
    use_initial_retrieval_only: bool
    select_strongest_excerpts_only: bool
    inspect_all_chunks: bool
    extract_evidence_from_every_chunk: bool
    consolidate_evidence: bool
    use_quality_layer: bool


MODE_CONFIG = {
    "light": ModeConfig(
        use_initial_retrieval_only=True,
        select_strongest_excerpts_only=True,
        inspect_all_chunks=False,
        extract_evidence_from_every_chunk=False,
        consolidate_evidence=False,
        use_quality_layer=False,
    ),
    "thinking": ModeConfig(
        use_initial_retrieval_only=False,
        select_strongest_excerpts_only=False,
        inspect_all_chunks=True,
        extract_evidence_from_every_chunk=True,
        consolidate_evidence=True,
        use_quality_layer=True,
    ),
    "deep_summary": ModeConfig(
        use_initial_retrieval_only=False,
        select_strongest_excerpts_only=False,
        inspect_all_chunks=True,
        extract_evidence_from_every_chunk=True,
        consolidate_evidence=True,
        use_quality_layer=True,
    ),
    "ticket_analysis": ModeConfig(
        use_initial_retrieval_only=False,
        select_strongest_excerpts_only=False,
        inspect_all_chunks=True,
        extract_evidence_from_every_chunk=False,
        consolidate_evidence=False,
        use_quality_layer=False,
    ),
    "web_research": ModeConfig(
        use_initial_retrieval_only=True,
        select_strongest_excerpts_only=False,
        inspect_all_chunks=False,
        extract_evidence_from_every_chunk=False,
        consolidate_evidence=False,
        use_quality_layer=False,
    ),
    "unrestricted": ModeConfig(
        use_initial_retrieval_only=True,
        select_strongest_excerpts_only=False,
        inspect_all_chunks=False,
        extract_evidence_from_every_chunk=False,
        consolidate_evidence=False,
        use_quality_layer=False,
    ),
}
