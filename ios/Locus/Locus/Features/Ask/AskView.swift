import SwiftUI

/// Ask — the question→answer loop: transcript, live pipeline card, floating composer.
struct AskView: View {
    @Environment(AppState.self) private var app
    @Environment(\.locusPalette) private var palette
    @State private var model = AskModel()
    @State private var showsChats = false
    @State private var showsFiles = false
    @State private var pendingTruncate: AskMessage?

    var body: some View {
        ZStack(alignment: .bottom) {
            transcript
            chatsButton
            composer
        }
        .task {
            model.app_defaultModelLabel = app.defaultModelLabel
            await model.loadIfNeeded()
        }
        .onChange(of: app.defaultModelLabel) { _, label in model.app_defaultModelLabel = label }
        .onChange(of: app.pendingChatId) { _, chatId in
            guard let chatId else { return }
            app.pendingChatId = nil
            Task { await model.open(chatId: chatId) }
        }
        .sheet(isPresented: $showsChats) {
            ChatListDrawer(
                chats: model.chats,
                activeChatId: model.activeChatId,
                onNew: { model.newChat() },
                onOpen: { id in Task { await model.open(chatId: id) } },
                onDelete: { id in Task { await model.delete(chatId: id) } },
                onDeleteAll: { Task { await model.deleteAllChats() } }
            )
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showsFiles) {
            FilePickerSheet(selection: $model.selectedFileIds)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .confirmationDialog(
            "Delete from this message onward?",
            isPresented: .init(get: { pendingTruncate != nil }, set: { if !$0 { pendingTruncate = nil } }),
            titleVisibility: .visible
        ) {
            Button("Delete from here", role: .destructive) {
                if let message = pendingTruncate {
                    Task { await model.truncate(from: message) }
                }
                pendingTruncate = nil
            }
            Button("Cancel", role: .cancel) { pendingTruncate = nil }
        }
    }

    // MARK: - Transcript

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    headerRow

                    if model.messages.isEmpty && model.activeJob == nil {
                        EmptyStateCard(
                            systemImage: "sparkles",
                            title: "Ask anything",
                            message: "Grounded in your libraries, or the web when a question needs it."
                        )
                        .padding(.top, 6)
                    }

                    ForEach(model.messages) { message in
                        MessageBubble(message: message)
                            .id(message.id)
                            .contextMenu {
                                Button {
                                    UIPasteboard.general.string = message.text
                                    LocusHaptics.light()
                                } label: {
                                    Label("Copy", systemImage: "doc.on.doc")
                                }
                                if message.serverId != nil {
                                    Button(role: .destructive) {
                                        pendingTruncate = message
                                    } label: {
                                        Label("Delete from here", systemImage: "trash")
                                    }
                                }
                            }
                    }

                    if let job = model.activeJob, let startedAt = model.jobStartedAt {
                        PipelineActivityCard(
                            job: job,
                            startedAt: startedAt,
                            fileCount: model.selectedFileIds?.count ?? 0
                        )
                        .id("pipeline")
                    }

                    if !model.suggestions.isEmpty {
                        suggestionChips
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 56)
                .padding(.bottom, 150)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .scrollIndicators(.hidden)
            .onChange(of: model.messages.count) { _, _ in
                withAnimation(.easeOut(duration: 0.25)) {
                    proxy.scrollTo(model.messages.last?.id, anchor: .bottom)
                }
            }
            .onChange(of: model.messages.last?.text.count) { _, _ in
                guard model.streaming else { return }
                proxy.scrollTo(model.messages.last?.id, anchor: .bottom)
            }
            .onChange(of: model.activeJob?.stage) { _, _ in
                withAnimation(.easeOut(duration: 0.25)) { proxy.scrollTo("pipeline", anchor: .bottom) }
            }
        }
    }

    private var headerRow: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                Text("ASK")
                    .font(LocusFont.kicker())
                    .tracking(2)
                    .foregroundStyle(palette.accent)
                Text(model.chats.first { $0.id == model.activeChatId }?.title ?? "What are you working on?")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(palette.heading)
                    .lineLimit(2)
            }
            Spacer(minLength: 52) // clear the floating chats button
        }
    }

    /// One floating button, mirroring the hamburger on the opposite edge. Chats and "New chat"
    /// used to be two; the sheet already opens with New chat at the top, so they merged.
    private var chatsButton: some View {
        VStack {
            HStack {
                Spacer()
                GlassCircleButton(systemImage: "bubble.left.and.bubble.right.fill", label: "Chats") {
                    LocusHaptics.light()
                    showsChats = true
                }
                .padding(.trailing, 16)
            }
            .padding(.top, 6)
            Spacer()
        }
    }

    private var suggestionChips: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("Follow-ups")
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(palette.subtle)
            ForEach(model.suggestions, id: \.self) { suggestion in
                Button {
                    LocusHaptics.light()
                    model.question = suggestion
                } label: {
                    HStack(spacing: 7) {
                        Image(systemName: "arrow.turn.down.right")
                            .font(.system(size: 10, weight: .semibold))
                        Text(suggestion)
                            .font(.system(size: 13))
                            .multilineTextAlignment(.leading)
                        Spacer(minLength: 0)
                    }
                    .foregroundStyle(palette.text)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 9)
                    .background(palette.glassFillSoft)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .strokeBorder(palette.glassEdgeSoft, lineWidth: 1)
                    )
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: - Composer

    private var composer: some View {
        FloatingComposer(
            text: $model.question,
            placeholder: "Ask anything…",
            busy: model.isBusy,
            menuItems: [
                ComposerMenuItem(title: "Add files", systemImage: "doc.badge.plus") { showsFiles = true },
                ComposerMenuItem(title: "New chat", systemImage: "square.and.pencil") { model.newChat() },
            ],
            chips: {
                ComposerDropdown(
                    options: EffortMode.allCases,
                    title: { $0.friendlyLabel },
                    systemImage: { $0.systemImage },
                    selection: $model.effort
                )
                ComposerIconButton(
                    systemImage: model.selectedFileIds == nil ? "tray.full" : "doc.text",
                    badge: model.selectedFileIds?.count,
                    active: model.selectedFileIds?.isEmpty == false || model.selectedFileIds == nil,
                    accessibilityLabel: fileScopeLabel
                ) {
                    LocusHaptics.light()
                    showsFiles = true
                }
                ComposerIconButton(
                    systemImage: "cpu",
                    active: model.allowGeneralKnowledge,
                    accessibilityLabel: model.allowGeneralKnowledge
                        ? "Answering with \(app.defaultModelLabel.isEmpty ? "the default model" : app.defaultModelLabel). General knowledge on."
                        : "Files only"
                ) {
                    LocusHaptics.selection()
                    model.allowGeneralKnowledge.toggle()
                }
                Spacer(minLength: 0)
            },
            onSend: { Task { await model.send() } },
            onStop: { Task { await model.stop() } }
        )
        .padding(.horizontal, 16)
        .padding(.bottom, LocusMetrics.bottomClearance)
    }

    private var fileScopeLabel: String {
        guard let ids = model.selectedFileIds else { return "All files" }
        return ids.isEmpty ? "No files" : LocusFormat.plural(ids.count, "file")
    }
}

/// The direct-stream trace: what the stream is doing before the first token lands.
private struct StreamTrace: View {
    @Environment(\.locusPalette) private var palette
    let steps: [StreamStep]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(steps) { step in
                HStack(alignment: .top, spacing: 8) {
                    icon(for: step.state)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(step.label)
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(step.state == .pending ? palette.subtle : palette.heading)
                        Text(step.detail)
                            .font(.system(size: 11))
                            .foregroundStyle(palette.muted)
                            .lineLimit(1)
                    }
                }
            }
        }
        .animation(.easeInOut(duration: 0.2), value: steps)
    }

    @ViewBuilder
    private func icon(for state: StreamStep.State) -> some View {
        switch state {
        case .pending:
            Circle().strokeBorder(palette.subtle, lineWidth: 1).frame(width: 9, height: 9).padding(.top, 3)
        case .live:
            Circle().fill(palette.accent).frame(width: 9, height: 9).padding(.top, 3)
        case .done:
            Image(systemName: "checkmark")
                .font(.system(size: 8, weight: .bold))
                .foregroundStyle(palette.success)
                .frame(width: 9).padding(.top, 3)
        case .failed:
            Image(systemName: "xmark")
                .font(.system(size: 8, weight: .bold))
                .foregroundStyle(palette.danger)
                .frame(width: 9).padding(.top, 3)
        }
    }
}

/// Blinking block cursor while tokens are still arriving.
private struct TypingCursor: View {
    @Environment(\.locusPalette) private var palette
    @State private var on = true

    var body: some View {
        RoundedRectangle(cornerRadius: 1)
            .fill(palette.accent)
            .frame(width: 7, height: 15)
            .opacity(on ? 1 : 0.15)
            .onAppear {
                withAnimation(.easeInOut(duration: 0.55).repeatForever()) { on = false }
            }
            .accessibilityLabel("Answering")
    }
}

// MARK: - Message bubble

private struct MessageBubble: View {
    @Environment(\.locusPalette) private var palette
    let message: AskMessage
    @State private var sourcesExpanded = false

    var body: some View {
        if message.role == .user {
            HStack {
                Spacer(minLength: 40)
                Text(message.text)
                    .font(.system(size: 15))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(palette.accentGradient)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            }
        } else {
            VStack(alignment: .leading, spacing: 9) {
                HStack(spacing: 6) {
                    Image(systemName: message.isError ? "exclamationmark.triangle.fill" : "sparkles")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(message.isError ? palette.danger : palette.accent)
                    Text(message.isError ? "Failed" : "Locus\(message.model.map { " · \($0)" } ?? "")")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(palette.muted)
                        .lineLimit(1)
                    Spacer()
                    if message.totalTokens > 0 {
                        Text("\(message.totalTokens.formatted()) tokens")
                            .font(.system(size: 10))
                            .foregroundStyle(palette.subtle)
                    }
                }

                if message.streaming && !message.activity.isEmpty && message.text.isEmpty {
                    StreamTrace(steps: message.activity)
                }

                if !message.text.isEmpty {
                    MarkdownText(markdown: message.text, streaming: message.streaming)
                        .foregroundStyle(message.isError ? palette.danger : palette.text)
                }

                if message.streaming {
                    TypingCursor()
                }

                if !message.sources.isEmpty {
                    sources
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(14)
            .locusCard()
        }
    }

    private var sources: some View {
        VStack(alignment: .leading, spacing: 7) {
            Button {
                LocusHaptics.light()
                withAnimation(.spring(duration: 0.28)) { sourcesExpanded.toggle() }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: sourcesExpanded ? "chevron.down" : "chevron.right")
                        .font(.system(size: 10, weight: .bold))
                    Text(LocusFormat.plural(message.sources.count, "source"))
                        .font(.system(size: 12, weight: .semibold))
                }
                .foregroundStyle(palette.accent)
            }
            .buttonStyle(.plain)

            if sourcesExpanded {
                ForEach(message.sources) { source in
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 6) {
                            Image(systemName: source.url.isEmpty ? "doc.text.fill" : "globe")
                                .font(.system(size: 10))
                                .foregroundStyle(palette.accent)
                            if let url = URL(string: source.url), !source.url.isEmpty {
                                Link(source.name, destination: url)
                                    .font(.system(size: 12, weight: .semibold))
                                    .foregroundStyle(palette.accent)
                                    .lineLimit(1)
                            } else {
                                Text(source.name)
                                    .font(.system(size: 12, weight: .semibold))
                                    .foregroundStyle(palette.heading)
                                    .lineLimit(1)
                            }
                        }
                        if !source.excerpt.isEmpty {
                            Text(source.excerpt)
                                .font(.system(size: 11))
                                .foregroundStyle(palette.muted)
                                .lineLimit(3)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(9)
                    .background(palette.glassFillSoft)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                }
            }
        }
    }
}
