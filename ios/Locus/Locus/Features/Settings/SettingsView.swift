import SwiftUI

/// Settings — the one place a default model is chosen. The model is picked from a searchable
/// list grouped by provider; the provider is derived from that choice and only displayed
/// (see the model-selection rule in CLAUDE.md). Saved as the `explore_ai` preference, so the
/// web picks up the same default.
struct SettingsView: View {
    @Environment(AppState.self) private var app
    @Environment(\.locusPalette) private var palette
    @State private var model = SettingsModel()
    @State private var showsPicker = false
    @State private var serverURL: String = ServerConfig.baseURL

    var body: some View {
        ZStack {
            GlowBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("SETTINGS")
                            .font(LocusFont.kicker())
                            .tracking(2)
                            .foregroundStyle(palette.accent)
                        Text("Settings")
                            .font(LocusFont.title())
                            .foregroundStyle(palette.heading)
                    }
                    .padding(.top, 18)

                    if model.loading {
                        ForEach(0..<3, id: \.self) { _ in SkeletonCard(height: 96) }
                    } else {
                        defaultModelCard
                        autoSelectCard
                        providersCard
                    }

                    appearanceCard
                    serverCard
                    sessionCard
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 34)
            }
            .scrollIndicators(.hidden)
        }
        .task { await model.loadIfNeeded() }
        .sheet(isPresented: $showsPicker) {
            ModelPickerSheet(model: model) { picked, provider in
                if await model.saveDefault(model: picked, provider: provider) {
                    app.defaultModelLabel = picked
                    app.showToast(kind: .success, text: "Default model saved")
                } else {
                    app.showToast(kind: .error, text: "Could not save the default model")
                }
            }
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
        }
    }

    // MARK: - Default model

    private var defaultModelCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 11) {
                Text("Default model")
                    .font(LocusFont.bodySemibold())
                    .foregroundStyle(palette.heading)

                Button {
                    LocusHaptics.light()
                    showsPicker = true
                } label: {
                    HStack(spacing: 10) {
                        Image(systemName: ProviderMeta.icon(model.selectedProvider))
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundStyle(palette.accent)
                            .frame(width: 36, height: 36)
                            .background(palette.accentSoft)
                            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(model.selectedModel.isEmpty ? "Pick a model" : model.selectedModel)
                                .font(.system(size: 15, weight: .semibold))
                                .foregroundStyle(palette.heading)
                                .lineLimit(1)
                            Text("Runs on \(ProviderMeta.label(model.selectedProvider)) — taken from the model you picked.")
                                .font(.system(size: 11))
                                .foregroundStyle(palette.muted)
                                .lineLimit(2)
                                .multilineTextAlignment(.leading)
                        }
                        Spacer(minLength: 0)
                        Image(systemName: "chevron.right")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(palette.subtle)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                if let note = model.autoSwitchNote {
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: "arrow.triangle.2.circlepath")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(palette.accent)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Auto-switched to \(ProviderMeta.label(note.provider)) / \(note.model) — \(note.previousModel) wasn't responding\(note.timestamp.map { " at \(LocusFormat.displayTime($0))" } ?? ""). It is now the default.")
                                .font(.system(size: 11))
                                .foregroundStyle(palette.muted)
                                .fixedSize(horizontal: false, vertical: true)
                            Button("Got it") {
                                LocusHaptics.light()
                                Task { await model.acknowledgeSwitch() }
                            }
                            .font(.system(size: 11, weight: .bold))
                            .foregroundStyle(palette.accent)
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(10)
                    .background(palette.accentSoft)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var autoSelectCard: some View {
        GlassCard {
            Toggle(isOn: Binding(
                get: { model.autoSelect },
                set: { next in Task { await model.setAutoSelect(next) } }
            )) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Auto-select a working model if the default fails")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(palette.heading)
                    Text("If the default errors out mid-request, Locus retries with the fastest model that passed a health check and keeps it. Untested or hidden models are never chosen.")
                        .font(.system(size: 11))
                        .foregroundStyle(palette.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .tint(palette.accent)
        }
    }

    // MARK: - Providers

    private var providersCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("Providers & models")
                        .font(LocusFont.bodySemibold())
                        .foregroundStyle(palette.heading)
                    Spacer()
                    if model.testedCount > 0 {
                        Text("\(model.respondingCount)/\(model.testedCount) responding")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(palette.success)
                    }
                }

                ForEach(model.providerOrder, id: \.self) { provider in
                    let models = model.models(for: provider)
                    HStack(spacing: 10) {
                        Image(systemName: ProviderMeta.icon(provider))
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(palette.accent)
                            .frame(width: 30, height: 30)
                            .background(palette.accentSoft)
                            .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
                        VStack(alignment: .leading, spacing: 1) {
                            Text(ProviderMeta.label(provider))
                                .font(.system(size: 14, weight: .semibold))
                                .foregroundStyle(palette.heading)
                            Text(LocusFormat.plural(models.count, "model"))
                                .font(.system(size: 11))
                                .foregroundStyle(palette.muted)
                        }
                        Spacer(minLength: 0)
                        if model.testing == provider {
                            HStack(spacing: 5) {
                                ProgressView().scaleEffect(0.6)
                                if !model.testProgress.isEmpty {
                                    Text(model.testProgress)
                                        .font(.system(size: 10))
                                        .foregroundStyle(palette.muted)
                                }
                            }
                        } else {
                            PillChip(title: "Test", systemImage: "bolt.fill") {
                                LocusHaptics.light()
                                Task { await model.test(provider: provider) }
                            }
                            .disabled(model.testing != nil)
                        }
                    }
                }

                Text("Testing pings each model once and tags the ones that answer. Long catalogues are sent in batches of 40 — the server's per-request cap.")
                    .font(.system(size: 10))
                    .foregroundStyle(palette.subtle)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    // MARK: - App

    private var appearanceCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                Text("Appearance")
                    .font(LocusFont.bodySemibold())
                    .foregroundStyle(palette.heading)
                HStack(spacing: 10) {
                    ForEach(LocusScheme.allCases, id: \.self) { scheme in
                        PillChip(title: scheme.title, systemImage: scheme.systemImage,
                                 active: app.scheme == scheme) {
                            LocusHaptics.selection()
                            app.setScheme(scheme)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var serverCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                Text("Server")
                    .font(LocusFont.bodySemibold())
                    .foregroundStyle(palette.heading)
                TextField("http://127.0.0.1:8000", text: $serverURL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                    .font(.system(size: 14, design: .monospaced))
                    .foregroundStyle(palette.heading)
                    .padding(10)
                    .background(palette.glassFillSoft)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                    .onSubmit {
                        ServerConfig.baseURL = serverURL
                        app.showToast(kind: .success, text: "Server URL saved")
                    }
                HStack(spacing: 6) {
                    StatusDot(ok: app.serverOnline == true)
                    Text(app.serverOnline == true ? "Connected" : app.serverOnline == false ? "Unreachable" : "Checking…")
                        .font(LocusFont.caption())
                        .foregroundStyle(palette.muted)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var sessionCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                Text("Session")
                    .font(LocusFont.bodySemibold())
                    .foregroundStyle(palette.heading)
                Button {
                    LocusHaptics.warning()
                    app.signOut()
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "rectangle.portrait.and.arrow.right")
                        Text("Sign out")
                    }
                    .font(LocusFont.bodySemibold())
                    .foregroundStyle(palette.danger)
                }
                .buttonStyle(.plain)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

// MARK: - Model picker

/// Searchable model list grouped by provider, with health tags and a responding-only filter.
/// A catalogue of several hundred models has to stay usable, so the list is lazy and filtered.
private struct ModelPickerSheet: View {
    @Environment(\.locusPalette) private var palette
    @Environment(\.dismiss) private var dismiss
    let model: SettingsModel
    let onPick: (String, String) async -> Void

    @State private var search = ""
    @State private var respondingOnly = false
    @State private var customModel = ""

    private func matches(_ provider: String) -> [String] {
        model.models(for: provider).filter { candidate in
            if respondingOnly, model.health(for: provider, model: candidate)?.ok != true { return false }
            guard !search.isEmpty else { return true }
            return candidate.localizedCaseInsensitiveContains(search)
                || ProviderMeta.label(provider).localizedCaseInsensitiveContains(search)
        }
    }

    var body: some View {
        ZStack {
            GlowBackground()
            VStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Default model")
                        .font(LocusFont.title())
                        .foregroundStyle(palette.heading)

                    HStack(spacing: 8) {
                        Image(systemName: "magnifyingglass")
                            .font(.system(size: 12))
                            .foregroundStyle(palette.subtle)
                        TextField("Search models", text: $search)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .font(.system(size: 14))
                            .foregroundStyle(palette.heading)
                    }
                    .padding(10)
                    .background(palette.glassFillSoft)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))

                    PillChip(title: "Responding only", systemImage: "bolt.fill", active: respondingOnly) {
                        LocusHaptics.selection()
                        respondingOnly.toggle()
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 18)
                .padding(.bottom, 12)

                List {
                    ForEach(model.providerOrder, id: \.self) { provider in
                        let models = matches(provider)
                        if !models.isEmpty {
                            Section {
                                ForEach(models, id: \.self) { candidate in
                                    row(provider: provider, candidate: candidate)
                                }
                            } header: {
                                HStack(spacing: 6) {
                                    Image(systemName: ProviderMeta.icon(provider))
                                        .font(.system(size: 10, weight: .semibold))
                                    Text(ProviderMeta.label(provider))
                                        .font(.system(size: 11, weight: .bold))
                                    Text("· \(models.count)")
                                        .font(.system(size: 11))
                                        .foregroundStyle(palette.subtle)
                                }
                                .foregroundStyle(palette.accent)
                            }
                        }
                    }

                    Section {
                        HStack(spacing: 8) {
                            TextField("Custom model id", text: $customModel)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .font(.system(size: 14, design: .monospaced))
                                .foregroundStyle(palette.heading)
                            Button("Use") {
                                let value = customModel.trimmingCharacters(in: .whitespacesAndNewlines)
                                guard !value.isEmpty else { return }
                                LocusHaptics.light()
                                Task {
                                    // A hand-typed id runs on the currently selected provider —
                                    // this overrides the id, not the provider.
                                    await onPick(value, model.selectedProvider)
                                    dismiss()
                                }
                            }
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(palette.accent)
                            .buttonStyle(.plain)
                        }
                        .listRowBackground(Color.clear)
                    } header: {
                        Text("Custom")
                            .font(.system(size: 11, weight: .bold))
                            .foregroundStyle(palette.accent)
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }
        }
    }

    private func row(provider: String, candidate: String) -> some View {
        let state = model.health(for: provider, model: candidate)
        let isCurrent = candidate == model.selectedModel
        return Button {
            LocusHaptics.light()
            Task {
                await onPick(candidate, provider)
                dismiss()
            }
        } label: {
            HStack(spacing: 9) {
                Image(systemName: isCurrent ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 13))
                    .foregroundStyle(isCurrent ? palette.accent : palette.subtle)
                Text(candidate)
                    .font(.system(size: 13))
                    .foregroundStyle(palette.heading)
                    .lineLimit(1)
                Spacer(minLength: 6)
                if let state {
                    // A model that has never been tested stays untagged rather than guessed at.
                    Text(state.ok ? "\(state.latencyMs) ms" : "no answer")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(state.ok ? palette.success : palette.danger)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 3)
                        .background((state.ok ? palette.success : palette.danger).opacity(0.14))
                        .clipShape(Capsule())
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .listRowBackground(Color.clear)
    }
}
