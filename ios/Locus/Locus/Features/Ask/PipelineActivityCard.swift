import SwiftUI

/// The live answer card — a native port of `src/components/PipelineActivity.jsx`. Collapsed it
/// shows mode, elapsed time, live usage and working notes; expanded it becomes the developer
/// trace with the stage track, telemetry counters and the runtime console.
struct PipelineActivityCard: View {
    @Environment(\.locusPalette) private var palette
    let job: ChatJobRead
    let startedAt: Date
    let fileCount: Int
    @State private var expanded = false
    @State private var elapsed = 0

    private var events: [[String: AnyCodable]] { job.events }

    private var directModelChat: Bool {
        !job.webSearch && job.reasoningMode == "light" && fileCount == 0
    }

    private struct Stage {
        let id: String
        let label: String
        let systemImage: String
        let headline: String
    }

    private var stages: [Stage] {
        let response = [
            Stage(id: "understanding", label: "Plan", systemImage: "brain", headline: "Understanding intent"),
            Stage(id: "gathering", label: "Gather", systemImage: "cylinder.split.1x2", headline: "Collecting evidence"),
            Stage(id: "drafting", label: "Compose", systemImage: "pencil.line", headline: "Building the answer"),
        ]
        let quality = [
            Stage(id: "verifying", label: "Verify", systemImage: "checkmark.shield", headline: "Checking quality"),
            Stage(id: "repairing", label: "Refine", systemImage: "sparkles", headline: "Resolving gaps"),
        ]
        if job.stage == "action" {
            return [Stage(id: "action", label: "Apply", systemImage: "bolt.fill", headline: "Applying changes")]
        }
        if directModelChat {
            return [Stage(id: "drafting", label: "Chat", systemImage: "cpu", headline: "Direct model chat")]
        }
        return ["thinking", "deep_summary"].contains(job.reasoningMode) ? response + quality : response
    }

    private var currentIndex: Int { stages.firstIndex { $0.id == job.stage } ?? -1 }
    private var activeIndex: Int { max(0, currentIndex) }

    private var modeLabel: String {
        if job.webSearch { return "Web Research" }
        if directModelChat { return "Direct chat" }
        switch job.reasoningMode {
        case "deep_summary": return "Max effort"
        case "thinking": return "High effort"
        case "web_research": return "Web Research"
        default: return "Normal effort"
        }
    }

    private var notes: [PipelineNotes.Note] {
        PipelineNotes.build(events: events, stage: job.stage, detail: job.detail)
    }

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                header
                if expanded { trace } else { thinking }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .task(id: startedAt) {
            while !Task.isCancelled {
                elapsed = max(0, Int(Date().timeIntervalSince(startedAt)))
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    // MARK: - Header

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "sparkles")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(palette.accent)
            Text("Locus · \(job.model)")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(palette.muted)
                .lineLimit(1)
            Spacer()
            Button {
                LocusHaptics.light()
                withAnimation(.spring(duration: 0.3)) { expanded.toggle() }
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: expanded ? "xmark" : "terminal")
                    Text(expanded ? "Hide" : "Trace")
                }
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(palette.accent)
            }
            .buttonStyle(.plain)
        }
    }

    // MARK: - Collapsed

    private var thinking: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Text(modeLabel)
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(palette.accent)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(palette.accentSoft)
                    .clipShape(Capsule())
                Text(PipelineNotes.elapsed(elapsed))
                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                    .foregroundStyle(palette.muted)
                Text(LocusFormat.plural(fileCount, "file"))
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(palette.subtle)
            }

            if job.llmHits > 0 || job.webQueries > 0 || job.totalTokens > 0 {
                HStack(spacing: 12) {
                    if job.llmHits > 0 {
                        statChip(systemImage: "cpu", value: "\(job.llmHits)", label: job.llmHits == 1 ? "LLM hit" : "LLM hits")
                    }
                    if job.webQueries > 0 {
                        statChip(systemImage: "magnifyingglass", value: "\(job.webQueries)", label: job.webQueries == 1 ? "search" : "searches")
                    }
                    if job.totalTokens > 0 {
                        statChip(systemImage: "bolt.fill", value: job.totalTokens.formatted(), label: "tokens")
                    }
                }
            }

            VStack(alignment: .leading, spacing: 7) {
                ForEach(notes) { note in
                    HStack(alignment: .top, spacing: 8) {
                        if note.live {
                            Circle()
                                .fill(palette.accent)
                                .frame(width: 7, height: 7)
                                .padding(.top, 5)
                        } else {
                            Image(systemName: "checkmark")
                                .font(.system(size: 8, weight: .bold))
                                .foregroundStyle(palette.success)
                                .frame(width: 7)
                                .padding(.top, 5)
                        }
                        Text(note.text)
                            .font(.system(size: 13))
                            .foregroundStyle(note.live ? palette.text : palette.muted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            .animation(.easeInOut(duration: 0.25), value: notes)
        }
    }

    private func statChip(systemImage: String, value: String, label: String) -> some View {
        HStack(spacing: 4) {
            Image(systemName: systemImage)
                .font(.system(size: 9, weight: .semibold))
            Text(value).font(.system(size: 11, weight: .bold))
            Text(label).font(.system(size: 11))
        }
        .foregroundStyle(palette.muted)
    }

    // MARK: - Expanded trace

    private var trace: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text("DEVELOPER TRACE")
                    .font(.system(size: 9, weight: .bold))
                    .tracking(1.5)
                    .foregroundStyle(palette.subtle)
                HStack {
                    Text(stages[activeIndex].headline)
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(palette.heading)
                    Spacer()
                    Text(PipelineNotes.elapsed(elapsed))
                        .font(.system(size: 12, weight: .bold, design: .monospaced))
                        .foregroundStyle(palette.accent)
                }
                Text(compact(job.detail))
                    .font(.system(size: 11))
                    .foregroundStyle(palette.muted)
                    .lineLimit(2)
            }

            // Stage track
            HStack(spacing: 6) {
                ForEach(Array(stages.enumerated()), id: \.element.id) { index, stage in
                    HStack(spacing: 4) {
                        Image(systemName: index < currentIndex ? "checkmark" : stage.systemImage)
                            .font(.system(size: 9, weight: .bold))
                        Text(stage.label)
                            .font(.system(size: 10, weight: .semibold))
                    }
                    .foregroundStyle(index == currentIndex ? palette.accent : index < currentIndex ? palette.success : palette.subtle)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .background(index == currentIndex ? palette.accentSoft : palette.glassFillSoft)
                    .clipShape(Capsule())
                }
            }

            GeometryReader { geometry in
                ZStack(alignment: .leading) {
                    Capsule().fill(palette.glassFillSoft)
                    Capsule()
                        .fill(palette.accentGradient)
                        .frame(width: geometry.size.width * progress)
                }
            }
            .frame(height: 4)

            // Telemetry
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                telemetry("waveform.path.ecg", "\(events.count)", "events")
                telemetry("cpu", "\(job.llmHits)", job.llmHits == 1 ? "LLM hit" : "LLM hits")
                telemetry("square.stack.3d.up", "\(evidenceSteps)", "evidence")
                telemetry("dot.radiowaves.left.and.right", "\(heartbeats)", "heartbeats")
                telemetry("magnifyingglass", "\(webSources)", "web sources")
                telemetry("doc.text", "\(fileCount)", fileCount == 1 ? "file" : "files")
            }

            // Runtime console
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Label("Runtime console", systemImage: "terminal")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(palette.muted)
                    Spacer()
                    Text(modeLabel)
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(palette.subtle)
                }
                VStack(alignment: .leading, spacing: 5) {
                    ForEach(Array(visibleEvents.enumerated()), id: \.offset) { index, event in
                        consoleRow(event, isLatest: index == visibleEvents.count - 1)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(10)
                .background(palette.glassFillSoft)
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
        }
    }

    private var progress: CGFloat {
        max(0.08, CGFloat(Double(activeIndex) + 0.35) / CGFloat(stages.count))
    }

    private var visibleEvents: [[String: AnyCodable]] { Array(events.suffix(12)) }

    private var evidenceSteps: Int {
        events.filter { ["chunk", "reduce", "synthesis"].contains($0["type"]?.string ?? "") }.count
    }

    private var heartbeats: Int {
        events.filter { $0["type"]?.string == "heartbeat" }.count
    }

    private var webSources: Int {
        let keys = events.filter { $0["type"]?.string == "web" }.compactMap { event -> String? in
            if let tags = event["tags"]?.array,
               let url = tags.compactMap({ $0.string }).first(where: { $0.hasPrefix("http") }) {
                return url
            }
            return event["detail"]?.string
        }
        return Set(keys).count
    }

    private func telemetry(_ systemImage: String, _ value: String, _ label: String) -> some View {
        HStack(spacing: 4) {
            Image(systemName: systemImage)
                .font(.system(size: 9))
                .foregroundStyle(palette.accent)
            Text(value)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(palette.heading)
            Text(label)
                .font(.system(size: 10))
                .foregroundStyle(palette.subtle)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func consoleRow(_ event: [String: AnyCodable], isLatest: Bool) -> some View {
        let type = event["type"]?.string ?? "status"
        let method = event["method"]?.string ?? "pipeline.tick()"
        let detail = event["detail"]?.string ?? "Event received"
        return HStack(alignment: .top, spacing: 6) {
            Text(Self.badge(for: type))
                .font(.system(size: 8, weight: .bold, design: .monospaced))
                .foregroundStyle(isLatest ? palette.accent : palette.subtle)
                .frame(width: 42, alignment: .leading)
            VStack(alignment: .leading, spacing: 1) {
                Text(method)
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(isLatest ? palette.heading : palette.muted)
                    .lineLimit(1)
                Text(compact(detail))
                    .font(.system(size: 10))
                    .foregroundStyle(palette.subtle)
                    .lineLimit(2)
            }
        }
    }

    private static func badge(for type: String) -> String {
        switch type {
        case "request": return "REQ"
        case "llm_call": return "CALL"
        case "llm_result": return "RECV"
        case "retrieval": return "READ"
        case "chunk": return "MAP"
        case "reduce": return "REDUCE"
        case "synthesis": return "MERGE"
        case "quality": return "QA"
        case "tool": return "TOOL"
        case "heartbeat": return "PING"
        case "complete": return "DONE"
        case "error": return "ERR"
        case "web", "web_search": return "WEB"
        default: return "LOG"
        }
    }

    private func compact(_ value: String, limit: Int = 180) -> String {
        let text = value.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
        if text.isEmpty { return "Waiting for signal..." }
        return text.count > limit ? String(text.prefix(limit - 3)) + "..." : text
    }
}
