import SwiftUI

/// A live private room, host side: messages, presence, disappear countdowns, the autopilot
/// review card, and the host tools (guests, options, copilot, clear, delete).
struct RoomView: View {
    @Environment(\.locusPalette) private var palette
    @Environment(\.dismiss) private var dismiss
    @State private var model: RoomModel
    @State private var showsGuests = false
    @State private var showsOptions = false
    @State private var showsCopilot = false
    @State private var confirmClear = false
    @State private var confirmDelete = false
    @State private var showsTelegram = false
    /// Only offered when the server actually has a Telegram account connected — without one
    /// the link call cannot resolve a contact.
    @State private var bridgeStatus: SecretChatBridgeStatus?
    @State private var roomBridge: SecretChatBridgeRead?
    private let onLeave: () -> Void

    init(token: String, onLeave: @escaping () -> Void) {
        _model = State(initialValue: RoomModel(token: token))
        self.onLeave = onLeave
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            GlowBackground()

            switch model.status {
            case .loading:
                ProgressView().tint(palette.accent)
            case .ended:
                endedState
            case .ready:
                transcript
                composer
            }

            header
        }
        .task {
            await model.open()
            await refreshBridge()
        }
        .onDisappear {
            model.close()
            onLeave()
        }
        .sheet(isPresented: $showsGuests) {
            GuestsPanel(guests: model.guests) { await model.loadGuests() }
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showsOptions) {
            if let session = model.session {
                RoomOptionsSheet(session: session) { title, ttl, link, room, tone, persona, autopilot, mimic in
                    await model.updateOptions(
                        title: title, ttlSeconds: ttl, linkExpiryMinutes: link, roomExpiryMinutes: room,
                        tone: tone, persona: persona, autopilot: autopilot, mimicMe: mimic
                    )
                }
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
            }
        }
        .sheet(isPresented: $showsCopilot) {
            CopilotSheet(model: model)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showsTelegram) {
            if let bridgeStatus {
                TelegramConnectSheet(token: model.token, status: bridgeStatus) {
                    Task { await refreshBridge() }
                }
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
            }
        }
        .confirmationDialog("Clear every message?", isPresented: $confirmClear, titleVisibility: .visible) {
            Button("Clear chat", role: .destructive) {
                LocusHaptics.warning()
                Task { await model.clearMessages() }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Messages are removed for everyone in this chat.")
        }
        .confirmationDialog("Delete this chat?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete chat", role: .destructive) {
                LocusHaptics.warning()
                Task {
                    await model.deleteRoom()
                    dismiss()
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The link stops working and every message is removed.")
        }
    }

    private func refreshBridge() async {
        bridgeStatus = try? await APIClient.shared.secretChatBridgeStatus()
        guard bridgeStatus?.configured == true else { return }
        roomBridge = try? await APIClient.shared.secretChatBridge(model.token, hostKey: PrivateIdentity.hostKey)
    }

    // MARK: - Header

    private var header: some View {
        VStack {
            HStack(spacing: 10) {
                GlassCircleButton(systemImage: "chevron.left", size: 38, label: "Back to chats") {
                    LocusHaptics.light()
                    dismiss()
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(model.title)
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(palette.heading)
                        .lineLimit(1)
                    HStack(spacing: 5) {
                        StatusDot(ok: model.onlineGuests > 0)
                        Text(model.onlineGuests > 0
                             ? "\(LocusFormat.plural(model.onlineGuests, "guest")) online"
                             : "No one else here yet")
                            .font(.system(size: 11))
                            .foregroundStyle(palette.muted)
                    }
                }
                Spacer()
                Menu {
                    Button { showsGuests = true } label: { Label("Guests", systemImage: "person.2.fill") }
                    if bridgeStatus?.configured == true {
                        Button { showsTelegram = true } label: {
                            Label(roomBridge.map { "Telegram · \($0.displayName)" } ?? "Connect Telegram",
                                  systemImage: "paperplane.fill")
                        }
                    }
                    Button { showsCopilot = true } label: { Label("Reply copilot", systemImage: "sparkles") }
                    Button { showsOptions = true } label: { Label("Chat options", systemImage: "slider.horizontal.3") }
                    if let session = model.session,
                       let url = URL(string: ServerConfig.baseURL + "/secret-chat/" + session.token) {
                        ShareLink(item: url) { Label("Share link", systemImage: "square.and.arrow.up") }
                    }
                    Divider()
                    Button(role: .destructive) { confirmClear = true } label: {
                        Label("Clear chat", systemImage: "eraser")
                    }
                    Button(role: .destructive) { confirmDelete = true } label: {
                        Label("Delete chat", systemImage: "trash")
                    }
                } label: {
                    Image(systemName: "ellipsis")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(palette.text)
                        .frame(width: 38, height: 38)
                        .background(palette.glassFill)
                        .clipShape(Circle())
                        .locusGlass(in: Circle())
                        .overlay(Circle().strokeBorder(palette.glassEdge, lineWidth: 1))
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 6)
            Spacer()
        }
    }

    // MARK: - Transcript

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    if model.session?.messageTTLSeconds ?? 0 > 0 {
                        disappearingBanner
                    }

                    ForEach(model.visibleMessages) { message in
                        if message.id == model.unreadFromId {
                            newMessagesDivider
                        }
                        MessageRow(
                            message: message,
                            isMine: message.sender == PrivateIdentity.displayName,
                            remaining: model.remainingSeconds(for: message)
                        )
                        .id(message.id)
                    }

                    if model.someoneTyping { typingBubble }

                    if let draft = model.autopilotDraft {
                        AutopilotDraftCard(draft: draft) { action in
                            Task { await model.decideAutopilot(action) }
                        }
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 62)
                .padding(.bottom, 130)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .scrollIndicators(.hidden)
            .onChange(of: model.visibleMessages.count) { _, _ in
                withAnimation(.easeOut(duration: 0.25)) {
                    proxy.scrollTo(model.visibleMessages.last?.id, anchor: .bottom)
                }
            }
        }
    }

    private var disappearingBanner: some View {
        HStack(spacing: 6) {
            Image(systemName: "timer")
                .font(.system(size: 10, weight: .semibold))
            Text("Messages disappear after \(RoomOption.label(forTTL: model.session?.messageTTLSeconds ?? 0))")
                .font(.system(size: 11, weight: .medium))
        }
        .foregroundStyle(palette.muted)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 8)
    }

    private var newMessagesDivider: some View {
        HStack(spacing: 8) {
            Rectangle().fill(palette.accent.opacity(0.4)).frame(height: 1)
            Text("New messages")
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(palette.accent)
            Rectangle().fill(palette.accent.opacity(0.4)).frame(height: 1)
        }
        .padding(.vertical, 4)
    }

    private var typingBubble: some View {
        HStack(spacing: 4) {
            ForEach(0..<3, id: \.self) { index in
                Circle()
                    .fill(palette.muted)
                    .frame(width: 6, height: 6)
                    .opacity(0.4)
                    .phaseAnimator([false, true]) { view, phase in
                        view.opacity(phase ? 1 : 0.3)
                    } animation: { _ in .easeInOut(duration: 0.5).delay(Double(index) * 0.15) }
            }
        }
        .padding(.horizontal, 13)
        .padding(.vertical, 10)
        .background(palette.glassFillSoft)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private var composer: some View {
        FloatingComposer(
            text: Binding(
                get: { model.draft },
                set: { model.draft = $0; model.markTyping() }
            ),
            placeholder: "Message…",
            busy: false,
            menuItems: [],
            chips: { EmptyView() },
            onSend: { Task { await model.send() } }
        )
        .padding(.horizontal, 16)
        .padding(.bottom, LocusMetrics.bottomClearance)
    }

    private var endedState: some View {
        VStack(spacing: 14) {
            EmptyStateCard(
                systemImage: "lock.slash",
                title: "Chat ended",
                message: model.endedReason ?? "This private chat has ended."
            )
            GradientPrimaryButton(title: "Back to chats", systemImage: "chevron.left") {
                dismiss()
            }
        }
        .padding(20)
    }
}

// MARK: - Message row

private struct MessageRow: View {
    @Environment(\.locusPalette) private var palette
    let message: SecretChatMessageRead
    let isMine: Bool
    let remaining: Int?

    var body: some View {
        HStack {
            if isMine { Spacer(minLength: 40) }
            VStack(alignment: isMine ? .trailing : .leading, spacing: 3) {
                if !isMine {
                    Text(message.sender)
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(palette.accent)
                }
                Text(message.content)
                    .font(.system(size: 15))
                    .foregroundStyle(isMine ? .white : palette.text)
                    .padding(.horizontal, 13)
                    .padding(.vertical, 9)
                    .background(
                        isMine
                            ? AnyShapeStyle(palette.accentGradient)
                            : AnyShapeStyle(palette.glassFillSoft)
                    )
                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                HStack(spacing: 5) {
                    Text(message.createdAt.formatted(date: .omitted, time: .shortened))
                        .font(.system(size: 9))
                        .foregroundStyle(palette.subtle)
                    // via_ai is tagged only in the author's own view — a guest is never shown
                    // that a reply was drafted for them.
                    if message.viaAI && isMine {
                        Label("AI", systemImage: "sparkles")
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(palette.accent)
                    }
                    if let remaining {
                        Label("\(remaining)s", systemImage: "timer")
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(remaining <= 10 ? palette.danger : palette.subtle)
                    }
                }
            }
            if !isMine { Spacer(minLength: 40) }
        }
    }
}

// MARK: - Autopilot review

private struct AutopilotDraftCard: View {
    @Environment(\.locusPalette) private var palette
    let draft: SecretChatAutopilotDraft
    let decide: (String) -> Void
    @State private var remaining: Double

    init(draft: SecretChatAutopilotDraft, decide: @escaping (String) -> Void) {
        self.draft = draft
        self.decide = decide
        _remaining = State(initialValue: draft.remainingSeconds)
    }

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 9) {
                HStack(spacing: 6) {
                    Image(systemName: "sparkles")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(palette.accent)
                    Text("Autopilot reply")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(palette.heading)
                    Spacer()
                    Text("sends in \(Int(max(0, remaining)))s")
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundStyle(palette.muted)
                }
                Text(draft.content)
                    .font(.system(size: 14))
                    .foregroundStyle(palette.text)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 8) {
                    PillChip(title: "Stop", systemImage: "hand.raised.fill") { decide("cancel") }
                    PillChip(title: "Send now", systemImage: "paperplane.fill", active: true) { decide("send") }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .task(id: draft.id) {
            while remaining > 0, !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(250))
                remaining -= 0.25
            }
        }
    }
}
