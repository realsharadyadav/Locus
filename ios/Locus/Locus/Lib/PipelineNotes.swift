import Foundation

/// Live "working notes" for the pipeline card — a 1:1 port of `src/lib/pipelineNotes.js` so the
/// running commentary reads the same on both clients.
enum PipelineNotes {
    struct Note: Identifiable, Equatable {
        let id: String
        let text: String
        let live: Bool
    }

    static func humanize(_ detail: String) -> String {
        let text = detail.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return "Starting the pipeline." }
        let lowered = text.lowercased()

        if lowered.hasPrefix("auto-enabled") {
            return "Search intent detected. Auto-enabling web research and collecting sources."
        }
        if lowered.contains("planning up to") {
            return "Planning the query first, so the search is not random."
        }
        if lowered.contains("round") && lowered.contains("follow-up") {
            return "Initial results were weak, trying the next search angle: \(text)"
        }
        if lowered.contains("search") && lowered.contains(":") {
            let tail = text.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
                .dropFirst().joined(separator: ":").trimmingCharacters(in: .whitespaces)
            return "Running search: \(tail.isEmpty ? text : tail)"
        }
        if text.hasPrefix("→") {
            return "Found source: \(text.replacingOccurrences(of: "^→\\s*", with: "", options: .regularExpression))"
        }
        if lowered.contains("collected") && lowered.contains("unique sources") {
            return "Collecting sources: \(text)"
        }
        if lowered.contains("semantic retrieval") {
            return "Searching local files for relevant chunks: \(text)"
        }
        if lowered.hasPrefix("searching") { return "Scanning uploaded files: \(text)" }
        if lowered.contains("analysis plan ready") {
            return "Plan is ready. Building the answer against the evidence now."
        }
        if lowered.contains("calling") && lowered.contains("understand") {
            return "Understanding the question's intent and building the answer structure."
        }
        if lowered.hasPrefix("preparing") { return "Composing the draft: \(text)" }
        if lowered.contains("synthesizing") { return "Merging sources and writing the final answer." }
        if lowered.contains("verify") || lowered.contains("quality") {
            return "Checking answer quality and grounding."
        }
        if lowered.contains("repair") { return "Found a gap, refining the answer." }
        if lowered.contains("answer ready") || lowered.contains("ready") { return "Answer is ready." }
        if lowered.contains("still") || lowered.contains("active") { return "Still working: \(text)" }
        return text.count > 170 ? String(text.prefix(167)) + "..." : text
    }

    /// Newest four distinct notes, oldest first, with the current pipeline detail marked live.
    static func build(events: [[String: AnyCodable]], stage: String, detail: String) -> [Note] {
        var candidates: [Note] = events.compactMap { event in
            guard let eventDetail = event["detail"]?.string, !eventDetail.isEmpty else { return nil }
            let at = event["at"]?.string ?? ""
            let eventStage = event["stage"]?.string ?? stage
            return Note(id: "\(at)-\(eventStage)-\(eventDetail)", text: humanize(eventDetail), live: false)
        }
        if !detail.isEmpty {
            candidates.append(Note(id: "current-\(stage)-\(detail)", text: humanize(detail), live: true))
        }

        var notes: [Note] = []
        var seen = Set<String>()
        for item in candidates.reversed() {
            let key = item.text.lowercased()
            if item.text.isEmpty || seen.contains(key) { continue }
            seen.insert(key)
            notes.insert(item, at: 0)
            if notes.count >= 4 { break }
        }
        return notes.isEmpty
            ? [Note(id: "start", text: "Got it. Processing the request.", live: true)]
            : notes
    }

    /// "1m 4s" / "2h 5m" — the web's `formatElapsedTime`.
    static func elapsed(_ totalSeconds: Int) -> String {
        let days = totalSeconds / 86_400
        let hours = (totalSeconds % 86_400) / 3600
        let minutes = (totalSeconds % 3600) / 60
        let seconds = totalSeconds % 60
        if days > 0 { return "\(days)d \(hours)h" }
        if hours > 0 { return "\(hours)h \(minutes)m" }
        if minutes > 0 { return "\(minutes)m \(seconds)s" }
        return "\(seconds)s"
    }
}
