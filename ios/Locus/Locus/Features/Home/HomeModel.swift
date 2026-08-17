import SwiftUI

/// Where a capability card or stat sends you when tapped.
enum HomeDestination: Equatable {
    case tab(AppTab)
    case settings
}

/// One card in the "What Locus can do" strip. Everything here is derived from a real backend
/// response — nothing is hardcoded marketing copy about capabilities the server doesn't have.
struct CapabilityChip: Identifiable {
    let id: String
    let systemImage: String
    let title: String
    let subtitle: String
    var accent: Color?
    let destination: HomeDestination
}

/// The three user-facing effort modes, mirroring `SLASH_COMMANDS` in `src/lib/ask.js`.
/// Titles, blurbs and accent colors are the web's, so both clients describe effort the same way.
enum EffortMode: String, CaseIterable {
    case light, thinking, deepSummary

    var friendlyLabel: String {
        switch self {
        case .light: return "Normal"
        case .thinking: return "High"
        case .deepSummary: return "Max"
        }
    }

    var friendlyDescription: String {
        switch self {
        case .light: return "Fast answer from the most relevant context"
        case .thinking: return "Inspects every selected file, or researches the web if none are selected"
        case .deepSummary: return "Covers every document section, or the widest web research if none are selected"
        }
    }

    var systemImage: String {
        switch self {
        case .light: return "dot.radiowaves.left.and.right"
        case .thinking: return "sparkles"
        case .deepSummary: return "book"
        }
    }

    var accent: Color {
        switch self {
        case .light: return Color(red: 124 / 255, green: 108 / 255, blue: 255 / 255)   // #7c6cff
        case .thinking: return Color(red: 167 / 255, green: 139 / 255, blue: 250 / 255) // #a78bfa
        case .deepSummary: return Color(red: 96 / 255, green: 165 / 255, blue: 250 / 255) // #60a5fa
        }
    }
}

@MainActor
@Observable
final class HomeModel {
    var stores: [CollectionRead] = []
    var files: [StoredFileRead] = []
    var chats: [ChatSessionRead] = []

    var config: LLMConfig?
    var health: [String: AnyCodable]?
    var autoSelectOn: Bool?

    /// Content loading (collections/files/chats) drives the page skeletons; the capability
    /// strip has its own flag so it can show its own placeholders while the rest is ready.
    var loadingContent = true
    var loadedCapabilities = false

    private var hasLoadedOnce = false

    var isEmpty: Bool { files.isEmpty }

    func loadIfNeeded() async {
        guard !hasLoadedOnce else { return }
        hasLoadedOnce = true
        await load()
    }

    /// Every request degrades to its empty value on failure — the web page does the same, so a
    /// single dead endpoint never blanks the whole dashboard.
    func load() async {
        async let storesTask = try? await APIClient.shared.collections()
        async let filesTask = try? await APIClient.shared.files()
        async let chatsTask = try? await APIClient.shared.chats()
        async let configTask = try? await APIClient.shared.llmConfig()
        async let healthTask = try? await APIClient.shared.preference("model_health")
        async let autoSelectTask = try? await APIClient.shared.preference("auto_select_model")

        let (loadedStores, loadedFiles, loadedChats) = await (storesTask, filesTask, chatsTask)
        stores = loadedStores ?? []
        files = loadedFiles ?? []
        chats = loadedChats ?? []
        loadingContent = false

        let (loadedConfig, loadedHealth, loadedAutoSelect) = await (configTask, healthTask, autoSelectTask)
        config = loadedConfig
        health = loadedHealth?.value
        autoSelectOn = loadedAutoSelect?.value["enabled"]?.bool
        loadedCapabilities = true
    }

    // MARK: - Derived data

    var recentFiles: [StoredFileRead] {
        files.sorted { $0.createdAt > $1.createdAt }.prefix(5).map { $0 }
    }

    var recentChats: [ChatSessionRead] {
        chats.sorted { $0.updatedAt > $1.updatedAt }.prefix(5).map { $0 }
    }

    /// model_health is `{provider: {model: {ok, latency_ms, checked_at}}}`. Counted the same
    /// way the web counts it, and only surfaced once a probe has actually run.
    private var healthCounts: (responding: Int, tested: Int) {
        guard let health else { return (0, 0) }
        var tested = 0
        var responding = 0
        for (_, models) in health {
            guard let models = models.dict else { continue }
            for (_, entry) in models {
                guard let entry = entry.dict else { continue }
                tested += 1
                if entry["ok"]?.bool == true { responding += 1 }
            }
        }
        return (responding, tested)
    }

    var capabilityChips: [CapabilityChip] {
        var chips = EffortMode.allCases.map { mode in
            CapabilityChip(
                id: "mode-\(mode.rawValue)",
                systemImage: mode.systemImage,
                title: mode.friendlyLabel,
                subtitle: mode.friendlyDescription,
                accent: mode.accent,
                destination: .tab(.ask)
            )
        }

        if let config {
            // A provider only counts when it actually lists a reachable model — an empty list
            // means no key configured, which isn't a "ready" provider.
            let providerCount = config.providers.values.filter { !$0.isEmpty }.count
            let modelCount = config.providers.values.reduce(0) { $0 + $1.count }
            chips.append(CapabilityChip(
                id: "models",
                systemImage: "cpu",
                title: "\(LocusFormat.plural(providerCount, "provider")) · \(LocusFormat.plural(modelCount, "model"))",
                subtitle: config.model.isEmpty ? "Set a default in Settings" : "Default: \(config.model)",
                destination: .settings
            ))
        }

        let counts = healthCounts
        if counts.tested > 0 {
            chips.append(CapabilityChip(
                id: "health",
                systemImage: "bolt.fill",
                title: "\(counts.responding)/\(counts.tested) models responding",
                subtitle: "verified by live probes",
                destination: .settings
            ))
        }

        if loadedCapabilities {
            let autoOn = autoSelectOn ?? false
            chips.append(CapabilityChip(
                id: "auto-fallback",
                systemImage: "arrow.triangle.2.circlepath",
                title: autoOn ? "Auto-fallback on" : "Auto-fallback off",
                subtitle: autoOn
                    ? "a failing default swaps itself mid-answer"
                    : "turn it on to never hit a dead model",
                destination: .settings
            ))
        }

        chips.append(CapabilityChip(
            id: "web-research",
            systemImage: "globe",
            title: "Web research",
            subtitle: "multi-round search + synthesis",
            destination: .tab(.ask)
        ))
        chips.append(CapabilityChip(
            id: "private-chats",
            systemImage: "bubble.left.and.bubble.right.fill",
            title: "Private Chats",
            subtitle: "ephemeral, guest-shareable rooms",
            destination: .tab(.privateChats)
        ))

        return chips
    }
}
