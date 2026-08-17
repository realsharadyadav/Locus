import SwiftUI

/// Provider display names and icons, mirroring `PROVIDER_LABELS` / `PROVIDER_META` in
/// `src/lib/appState.js`. The provider is always *derived* from the chosen model and shown —
/// never picked directly (see the model-selection rule in CLAUDE.md).
enum ProviderMeta {
    static let labels: [String: String] = [
        "ollama": "Ollama", "groq": "Groq", "openai": "OpenAI", "gemini": "Gemini",
        "cerebras": "Cerebras", "openrouter": "OpenRouter", "tokenrouter": "TokenRouter",
        "opencode": "OpenCode Go",
    ]

    static let icons: [String: String] = [
        "ollama": "desktopcomputer", "groq": "bolt.fill", "openai": "brain",
        "gemini": "sparkle", "cerebras": "cpu", "openrouter": "arrow.triangle.branch",
        "tokenrouter": "arrow.triangle.swap", "opencode": "chevron.left.forwardslash.chevron.right",
    ]

    static func label(_ provider: String) -> String {
        labels[provider] ?? provider.capitalized
    }

    static func icon(_ provider: String) -> String {
        icons[provider] ?? "cpu"
    }
}

/// The record the backend writes when auto-select swaps a failing default.
struct AutoSwitchNote {
    let provider: String
    let model: String
    let previousModel: String
    let timestamp: Date?

    init?(_ value: [String: AnyCodable]?) {
        guard let value,
              let model = value["model"]?.string, !model.isEmpty,
              value["acknowledged"]?.bool != true else { return nil }
        self.model = model
        provider = value["provider"]?.string ?? ""
        previousModel = value["previous_model"]?.string ?? "the previous model"
        if let stamp = value["timestamp"]?.string {
            timestamp = ISO8601DateFormatter().date(from: stamp)
        } else {
            timestamp = nil
        }
    }
}

@MainActor
@Observable
final class SettingsModel {
    var config: LLMConfig?
    var health: [String: AnyCodable] = [:]
    var autoSelect = false
    var autoSwitchNote: AutoSwitchNote?

    /// Current draft of the `explore_ai` preference. Only the model is chosen; the provider
    /// rides along with it.
    var selectedProvider = ""
    var selectedModel = ""

    var loading = true
    var saving = false
    var testing: String?
    var testProgress = ""

    private var hasLoadedOnce = false

    var providerOrder: [String] {
        guard let config else { return [] }
        let listed = config.providerOrder.filter { config.providers[$0]?.isEmpty == false }
        let extras = config.providers.keys.filter { !listed.contains($0) && !(config.providers[$0]?.isEmpty ?? true) }
        return listed + extras.sorted()
    }

    func models(for provider: String) -> [String] {
        config?.providers[provider] ?? []
    }

    func health(for provider: String, model: String) -> ModelHealth? {
        guard let entry = health[provider]?[model]?.dict else { return nil }
        return ModelHealth(
            ok: entry["ok"]?.bool ?? false,
            latencyMs: entry["latency_ms"]?.int ?? 0,
            error: entry["error"]?.string ?? "",
            checkedAt: entry["checked_at"]?.string ?? ""
        )
    }

    var testedCount: Int {
        health.values.reduce(0) { $0 + ($1.dict?.count ?? 0) }
    }

    var respondingCount: Int {
        health.values.reduce(0) { total, models in
            total + (models.dict?.values.filter { $0["ok"]?.bool == true }.count ?? 0)
        }
    }

    func loadIfNeeded() async {
        guard !hasLoadedOnce else { return }
        hasLoadedOnce = true
        await load()
    }

    func load() async {
        async let configTask = try? await APIClient.shared.llmConfig()
        async let exploreTask = try? await APIClient.shared.preference("explore_ai")
        async let healthTask = try? await APIClient.shared.preference("model_health")
        async let autoTask = try? await APIClient.shared.preference("auto_select_model")
        async let switchTask = try? await APIClient.shared.preference("auto_select_last_switch")

        let (loadedConfig, explore, healthPref, auto, lastSwitch) =
            await (configTask, exploreTask, healthTask, autoTask, switchTask)

        config = loadedConfig
        health = healthPref?.value ?? [:]
        autoSelect = auto?.value["enabled"]?.bool ?? false
        autoSwitchNote = AutoSwitchNote(lastSwitch?.value)
        selectedModel = explore?.value["model"]?.string ?? loadedConfig?.model ?? ""
        selectedProvider = explore?.value["provider"]?.string ?? loadedConfig?.provider ?? ""
        loading = false
    }

    /// Saves the default model. Writes the same `explore_ai` shape the web writes, so both
    /// clients read each other's choice.
    func saveDefault(model: String, provider: String) async -> Bool {
        saving = true
        defer { saving = false }
        do {
            _ = try await APIClient.shared.updatePreference("explore_ai", value: [
                "provider": .string(provider),
                "model": .string(model),
                "reasoning_mode": .string("light"),
                "web_source_limit": .int(200),
            ])
            selectedModel = model
            selectedProvider = provider
            // Taking the wheel makes a previous automatic switch note stale.
            if autoSwitchNote != nil { await acknowledgeSwitch() }
            LocusHaptics.success()
            return true
        } catch {
            return false
        }
    }

    func setAutoSelect(_ enabled: Bool) async {
        autoSelect = enabled
        _ = try? await APIClient.shared.updatePreference("auto_select_model", value: [
            "enabled": .bool(enabled),
        ])
    }

    func acknowledgeSwitch() async {
        guard let note = autoSwitchNote else { return }
        autoSwitchNote = nil
        _ = try? await APIClient.shared.updatePreference("auto_select_last_switch", value: [
            "provider": .string(note.provider),
            "model": .string(note.model),
            "previous_model": .string(note.previousModel),
            "acknowledged": .bool(true),
        ])
    }

    /// Probes a provider's models. The endpoint caps a request at 40 models, so a long
    /// catalogue is sent in batches and the health map is merged as each batch lands.
    func test(provider: String) async {
        let all = models(for: provider)
        guard !all.isEmpty else { return }
        testing = provider
        defer { testing = nil; testProgress = "" }

        let batches = stride(from: 0, to: all.count, by: 40).map {
            Array(all[$0..<min($0 + 40, all.count)])
        }
        for (index, batch) in batches.enumerated() {
            testProgress = batches.count > 1 ? "batch \(index + 1)/\(batches.count)" : ""
            guard let response = try? await APIClient.shared.testModels(provider: provider, models: batch) else { continue }
            var providerHealth = health[provider]?.dict ?? [:]
            for (model, result) in response.results {
                providerHealth[model] = .dict([
                    "ok": .bool(result.ok),
                    "latency_ms": .int(result.latencyMs),
                    "error": .string(result.error),
                    "checked_at": .string(result.checkedAt),
                ])
            }
            health[provider] = .dict(providerHealth)
        }
        LocusHaptics.success()
    }
}
