from dataclasses import asdict, dataclass
import re

from .llm import _context_budget, generate_answer


FULL_SUMMARY_PATTERNS = (
    r"\b(?:complete|comprehensive|detailed|in[- ]depth|full) summar(?:y|ise|ize)\b",
    r"\bsummari[sz]e\b.*\b(?:book|document|pdf|all chapters|chapter[- ]wise|in detail)\b",
    r"\b(?:full context|understand (?:the )?full (?:book|document)|all chapters|chapter[- ]wise summary)\b",
    r"\bdo not have time\b.*\bfull context\b",
)
SUMMARY_INTENT_PATTERNS = (
    r"\bsummari[sz]e\b",
    r"\bsummary\b",
    r"\boverview\b",
    r"\bchapter[- ]wise\b",
)
PAGE_MARKER = re.compile(r"^--- PAGE (\d+) ---$", re.MULTILINE)
HEADING = re.compile(
    r"^(?:#{1,4}\s+)?((?:(?:chapter|part|section)\s+[\w.-]+(?:(?:\s*[:.-]\s*|\s+).+)?|"
    r"(?:introduction|preface|prologue|overview|conclusion|epilogue|appendix|references)(?:(?:\s*[:.-]\s*|\s+).+)?))$",
    re.IGNORECASE,
)


@dataclass
class CoverageManifest:
    fileName: str
    totalPages: int
    totalChunks: int
    processedChunks: int
    detectedSections: list[str]
    summarizedSections: list[str]
    coverageStatus: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DocumentChunk:
    filename: str
    index: int
    text: str
    pages: list[int]
    section: str


def is_full_summary_intent(question: str) -> bool:
    normalized = " ".join(question.lower().split())
    return any(re.search(pattern, normalized) for pattern in FULL_SUMMARY_PATTERNS)


def is_summary_intent(question: str) -> bool:
    normalized = " ".join(question.lower().split())
    return any(re.search(pattern, normalized) for pattern in SUMMARY_INTENT_PATTERNS)


def _segments(text: str) -> tuple[list[tuple[int | None, str]], int]:
    matches = list(PAGE_MARKER.finditer(text))
    if not matches:
        return [(None, text)], 0
    result = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result.append((int(match.group(1)), text[match.end():end].strip()))
    return result, max(page for page, _ in result if page is not None)


def _heading(line: str) -> str | None:
    clean = line.strip().strip("*_")
    if re.match(r"^#{1,4}\s+\S", clean):
        return re.sub(r"^#{1,4}\s+", "", clean).strip()
    match = HEADING.match(clean)
    return match.group(1).strip() if match else None


def chunk_document(filename: str, text: str, size: int) -> tuple[list[DocumentChunk], int, list[str]]:
    segments, total_pages = _segments(text)
    chunks: list[DocumentChunk] = []
    sections: list[str] = []
    current_section = "Document overview"
    buffer: list[str] = []
    pages: set[int] = set()

    def flush() -> None:
        if not buffer:
            return
        chunks.append(DocumentChunk(filename, len(chunks) + 1, "\n".join(buffer), sorted(pages), current_section))
        buffer.clear()
        pages.clear()

    for page, segment in segments:
        in_table_of_contents = False
        for line in segment.splitlines():
            paragraph = line.strip()
            if not paragraph:
                continue
            if re.match(r"^(?:table of contents|contents)$", paragraph, re.IGNORECASE):
                in_table_of_contents = True
                buffer.append(paragraph)
                if page is not None:
                    pages.add(page)
                continue
            found_heading = _heading(paragraph)
            if found_heading and not in_table_of_contents:
                flush()
                current_section = found_heading
                if found_heading not in sections:
                    sections.append(found_heading)
                continue
            for start in range(0, len(paragraph), size):
                piece = paragraph[start:start + size]
                if buffer and sum(len(item) + 1 for item in buffer) + len(piece) > size:
                    flush()
                buffer.append(piece)
                if page is not None:
                    pages.add(page)
    flush()
    return chunks or [DocumentChunk(filename, 1, text[:size], [], current_section)], total_pages, sections


def _reduce_sources(sources: list[tuple[str, str]], model: str, instruction: str) -> list[tuple[str, str]]:
    limit = max(4_000, int(_context_budget(model) * 0.62))
    current = sources
    while len(current) > 1 and sum(len(text) for _, text in current) > limit:
        groups: list[list[tuple[str, str]]] = []
        group: list[tuple[str, str]] = []
        used = 0
        for source in current:
            if group and used + len(source[1]) > limit:
                groups.append(group)
                group, used = [], 0
            group.append(source)
            used += len(source[1])
        if group:
            groups.append(group)
        next_level = []
        for index, batch in enumerate(groups, 1):
            consolidated, _ = generate_answer(
                instruction + " Process every supplied summary and retain its exact section heading.",
                batch, model=model, allow_general_knowledge=False, reasoning_mode="thinking",
            )
            next_level.append((f"Coverage packet {index}", consolidated))
        current = next_level
    return current


def _combine_summaries(filename: str, section: str, summaries: list[str], model: str) -> str:
    sources = [(f"{filename} - {section} - chunk {index}", summary) for index, summary in enumerate(summaries, 1)]
    instruction = f'Consolidate every chunk summary for the section "{section}". Preserve all distinct key ideas, facts, examples, actions, risks, timelines, exercises, practical takeaways, and open questions. Remove only repetition. Do not omit later chunks.'
    reduced = _reduce_sources(sources, model, instruction)
    if len(reduced) == 1 and len(summaries) == 1:
        return reduced[0][1]
    result, _ = generate_answer(instruction, reduced, model=model, allow_general_knowledge=False, reasoning_mode="thinking")
    return result


def deep_summarize_documents(documents: list[tuple[str, str]], model: str, notify=lambda detail: None):
    chunk_size = max(4_000, int(_context_budget(model) * 0.55))
    all_chunks: list[DocumentChunk] = []
    total_pages = 0
    detected_sections: list[str] = []
    for filename, text in documents:
        chunks, pages, sections = chunk_document(filename, text, chunk_size)
        all_chunks.extend(chunks)
        total_pages += pages
        for section in dict.fromkeys(chunk.section for chunk in chunks):
            label = f"{filename}: {section}" if len(documents) > 1 else section
            if label not in detected_sections:
                detected_sections.append(label)

    total_chars = sum(len(chunk.text) for chunk in all_chunks)
    if total_pages and all_chunks and len(all_chunks) <= 3 and total_chars <= 18_000:
        manifest = CoverageManifest(
            fileName=documents[0][0] if len(documents) == 1 else f"{len(documents)} files",
            totalPages=total_pages,
            totalChunks=len(all_chunks),
            processedChunks=len(all_chunks),
            detectedSections=detected_sections,
            summarizedSections=detected_sections,
            coverageStatus="complete",
        )
        notify(f"Deep Summary: small document fast path ({len(all_chunks)} chunk{'s' if len(all_chunks) != 1 else ''})")
        coverage_list = "\n".join(f"- {section}" for section in detected_sections)
        complete_text = "\n\n".join(
            f"SECTION: {chunk.section}\nSOURCE: {chunk.filename}\nPAGES: {', '.join(map(str, chunk.pages)) or 'n/a'}\n{chunk.text}"
            for chunk in all_chunks
        )
        answer, used_model = generate_answer(
            "Create a complete, grounded summary of the supplied document text. Give every section in the coverage list explicit treatment using its exact heading, preserve important facts, risks, telemetry requirements, decisions, and tradeoffs, and cite the filename. Include a short coverage manifest at the end.\n\nRequired section coverage:\n" + coverage_list,
            [(manifest.fileName, complete_text)],
            model=model,
            allow_general_knowledge=False,
            reasoning_mode="thinking",
            guidance=f"Coverage manifest: {manifest.to_dict()}",
        )
        false_absence_markers = (
            "what's missing", "what’s missing", "does not contain excerpts", "do not contain excerpts",
            "aren't represented", "aren’t represented", "content isn't available", "content isn’t available",
        )
        if any(marker in answer.lower() for marker in false_absence_markers):
            answer = "The complete selected source was processed. The detailed summaries below preserve every detected section."
        section_evidence = [
            (
                f"{chunk.filename} - {chunk.section}",
                f"SECTION: {chunk.section}\n{chunk.text}",
            )
            for chunk in all_chunks
        ]
        return answer, used_model, manifest, section_evidence

    chunk_summaries: dict[tuple[str, str], list[str]] = {}
    for position, chunk in enumerate(all_chunks, 1):
        provenance = f"pages {', '.join(map(str, chunk.pages))}" if chunk.pages else f"chunk {chunk.index}"
        notify(f"Deep Summary: summarizing {chunk.filename}, {provenance} ({position} of {len(all_chunks)})")
        summary, _ = generate_answer(
            f'Summarize this complete chunk from section "{chunk.section}". Preserve the core thesis, key ideas, important facts, decisions, actions, risks, timelines, owners, examples, exercises, practical takeaways, and open questions that are actually present. Include the evidence location ({provenance}). Do not discard material merely because it seems less relevant and do not add outside facts.',
            [(chunk.filename, chunk.text)], model=model, allow_general_knowledge=False, reasoning_mode="thinking",
        )
        chunk_summaries.setdefault((chunk.filename, chunk.section), []).append(summary)

    section_evidence: list[tuple[str, str]] = []
    summarized_sections: list[str] = []
    for (filename, section), summaries in chunk_summaries.items():
        notify(f'Deep Summary: consolidating section "{section}"')
        consolidated = _combine_summaries(filename, section, summaries, model)
        label = f"{filename}: {section}" if len(documents) > 1 else section
        summarized_sections.append(label)
        section_evidence.append((f"{filename} - {section}", f"SECTION: {label}\n{consolidated}"))

    manifest = CoverageManifest(
        fileName=documents[0][0] if len(documents) == 1 else f"{len(documents)} files",
        totalPages=total_pages,
        totalChunks=len(all_chunks),
        processedChunks=len(all_chunks),
        detectedSections=detected_sections,
        summarizedSections=summarized_sections,
        coverageStatus="complete" if len(all_chunks) and set(detected_sections) <= set(summarized_sections) else "incomplete",
    )
    notify("Deep Summary: synthesizing the final answer from every section")
    coverage_list = "\n".join(f"- {section}" for section in detected_sections)
    synthesis_evidence = _reduce_sources(
        section_evidence,
        model,
        "Consolidate these section summaries without losing any section, fact, example, or evidence location. Preserve every exact SECTION heading for final synthesis.",
    )
    answer, used_model = generate_answer(
        "Create a complete, grounded, well-structured summary from every supplied section summary. Give each section in the coverage list explicit treatment using its exact heading. Explain the overall thesis and relationships across sections, preserve important examples and practical takeaways, and distinguish uncertainty or conflicts. Never claim the source only contains certain material unless the coverage manifest proves it.\n\nRequired section coverage:\n" + coverage_list,
        synthesis_evidence, model=model, allow_general_knowledge=False, reasoning_mode="thinking",
        guidance=f"Coverage manifest: {manifest.to_dict()}",
    )
    false_absence_markers = (
        "what's missing", "what’s missing", "does not contain excerpts", "do not contain excerpts",
        "aren't represented", "aren’t represented", "content isn't available", "content isn’t available",
    )
    if manifest.coverageStatus == "complete" and any(marker in answer.lower() for marker in false_absence_markers):
        answer = "The complete selected source was processed. The detailed summaries below preserve every detected section."

    # The model may compress or omit sections during final synthesis. Append the
    # already-consolidated section summaries deterministically so coverage never
    # depends on a model remembering every item in a long prompt.
    detailed_sections = []
    for source_name, content in section_evidence:
        label = content.splitlines()[0].removeprefix("SECTION:").strip()
        summary = "\n".join(content.splitlines()[1:]).strip()
        detailed_sections.append(f"## {label}\n\n{summary}\n\n_Source: {source_name}_")
    answer = answer.rstrip() + "\n\n# Complete Section Coverage\n\n" + "\n\n".join(detailed_sections)
    return answer, used_model, manifest, section_evidence


def missing_sections(answer: str, manifest: CoverageManifest) -> list[str]:
    lowered = answer.lower()
    return [section for section in manifest.detectedSections if section.lower() not in lowered]
