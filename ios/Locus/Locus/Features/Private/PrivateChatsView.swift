import SwiftUI

/// Private Chats — the host side of `/secret-chat`: rooms you created on this device, each with
/// its own share link. Room management is authorised by this device's host key, so a link guest
/// can chat but can never manage a room or see anyone's device details.
struct PrivateChatsView: View {
    @Environment(\.locusPalette) private var palette
    @State private var model = PrivateChatsModel()
    @State private var showsNewRoom = false
    @State private var openToken: String?
    @State private var pendingDelete: SecretChatRoomSummary?

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            PageScaffold(
                kicker: "Signals",
                title: "Private chats",
                subtitle: "Each chat gets its own link. Share it — guests see only that chat."
            ) {
                if let bridge = model.bridge, bridge.configured {
                    bridgeRow(bridge)
                }

                if model.loading {
                    VStack(spacing: 12) {
                        ForEach(0..<3, id: \.self) { _ in SkeletonCard(height: 84) }
                    }
                } else if model.rooms.isEmpty {
                    EmptyStateCard(
                        systemImage: "bubble.left.and.text.bubble.right",
                        title: "No private chats yet",
                        message: "Create one, share the link, and the conversation stays between you two."
                    )
                } else {
                    ForEach(model.rooms) { room in
                        RoomCard(room: room) {
                            LocusHaptics.light()
                            openToken = room.token
                        } onShare: {
                            LocusHaptics.light()
                        } onDelete: {
                            pendingDelete = room
                        }
                    }
                }

                if let error = model.errorMessage {
                    Text(error)
                        .font(LocusFont.caption())
                        .foregroundStyle(palette.danger)
                }
            }
            .refreshable { await model.refresh() }

            Button {
                LocusHaptics.light()
                showsNewRoom = true
            } label: {
                HStack(spacing: 7) {
                    Image(systemName: "plus")
                        .font(.system(size: 14, weight: .bold))
                    Text("New chat")
                        .font(.system(size: 14, weight: .semibold))
                }
                .foregroundStyle(.white)
                .padding(.horizontal, 15)
                .frame(minHeight: LocusMetrics.minimumTapTarget)
                .background(palette.accentGradient)
                .clipShape(Capsule())
                .shadow(color: palette.accent.opacity(0.4), radius: 16, y: 8)
            }
            .buttonStyle(.plain)
            .padding(.trailing, 20)
            .padding(.bottom, LocusMetrics.bottomClearance)
        }
        .task { await model.loadIfNeeded() }
        .sheet(isPresented: $showsNewRoom) {
            NewRoomSheet { title, ttl, link, room in
                if let token = await model.createRoom(
                    title: title, ttlSeconds: ttl, linkExpiryMinutes: link, roomExpiryMinutes: room
                ) {
                    openToken = token
                }
            }
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
        }
        .fullScreenCover(item: Binding(
            get: { openToken.map { RoomToken(value: $0) } },
            set: { openToken = $0?.value }
        )) { token in
            RoomView(token: token.value) { Task { await model.refresh() } }
        }
        .alert("Couldn't create the chat", isPresented: Binding(
            get: { model.createError != nil },
            set: { if !$0 { model.createError = nil } }
        )) {
            Button("OK", role: .cancel) { model.createError = nil }
        } message: {
            Text(model.createError ?? "")
        }
        .confirmationDialog(
            "Delete this chat for everyone?",
            isPresented: Binding(get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } }),
            titleVisibility: .visible
        ) {
            Button("Delete chat", role: .destructive) {
                if let room = pendingDelete {
                    LocusHaptics.warning()
                    Task { await model.delete(room.token) }
                }
                pendingDelete = nil
            }
            Button("Cancel", role: .cancel) { pendingDelete = nil }
        } message: {
            Text("The link stops working and every message is removed.")
        }
    }

    private func bridgeRow(_ bridge: SecretChatBridgeStatus) -> some View {
        GlassCard(padding: 12) {
            HStack(spacing: 9) {
                Image(systemName: "link")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(palette.accent)
                VStack(alignment: .leading, spacing: 1) {
                    Text("\(bridge.platform.capitalized) bridge")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(palette.heading)
                    Text(bridge.connected
                         ? (bridge.account.isEmpty ? "Connected" : "Connected as \(bridge.account)")
                         : (bridge.error.isEmpty ? "Not connected" : bridge.error))
                        .font(.system(size: 11))
                        .foregroundStyle(palette.muted)
                        .lineLimit(2)
                }
                Spacer()
                StatusDot(ok: bridge.connected)
            }
        }
    }
}

/// `fullScreenCover(item:)` needs an Identifiable, and a bare token string is not one.
private struct RoomToken: Identifiable {
    let value: String
    var id: String { value }
}

private struct RoomCard: View {
    @Environment(\.locusPalette) private var palette
    let room: SecretChatRoomSummary
    let onOpen: () -> Void
    let onShare: () -> Void
    let onDelete: () -> Void

    var body: some View {
        Button(action: onOpen) {
            GlassCard {
                VStack(alignment: .leading, spacing: 9) {
                    HStack(spacing: 8) {
                        Text(room.title)
                            .font(.system(size: 16, weight: .bold))
                            .foregroundStyle(palette.heading)
                            .lineLimit(1)
                        if room.unreadCount > 0 {
                            Text("\(room.unreadCount)")
                                .font(.system(size: 10, weight: .bold))
                                .foregroundStyle(.white)
                                .padding(.horizontal, 7)
                                .padding(.vertical, 2)
                                .background(palette.accentGradient)
                                .clipShape(Capsule())
                        }
                        Spacer()
                        Text(LocusFormat.displayTime(room.lastActivity))
                            .font(.system(size: 11))
                            .foregroundStyle(palette.subtle)
                    }

                    if !room.lastMessagePreview.isEmpty {
                        Text("\(room.lastSender.isEmpty ? "" : room.lastSender + ": ")\(room.lastMessagePreview)")
                            .font(.system(size: 13))
                            .foregroundStyle(palette.muted)
                            .lineLimit(1)
                    }

                    HStack(spacing: 7) {
                        metaChip("person.2.fill", "\(room.onlineCount)/\(room.participantCount)")
                        if room.messageTTLSeconds > 0 {
                            metaChip("timer", RoomOption.label(forTTL: room.messageTTLSeconds))
                        }
                        if room.linkExpired {
                            metaChip("link.badge.plus", "Link expired", tint: palette.danger)
                        }
                        if !room.bridgePlatform.isEmpty {
                            metaChip("paperplane.fill", room.bridgeName.isEmpty ? room.bridgePlatform : room.bridgeName)
                        }
                        Spacer()
                        if let url = PrivateChatsModel.shareURL(for: room) {
                            ShareLink(item: url) {
                                Image(systemName: "square.and.arrow.up")
                                    .font(.system(size: 13, weight: .semibold))
                                    .foregroundStyle(palette.accent)
                            }
                            .buttonStyle(.plain)
                            .simultaneousGesture(TapGesture().onEnded { onShare() })
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .buttonStyle(.plain)
        .contextMenu {
            if let url = PrivateChatsModel.shareURL(for: room) {
                ShareLink(item: url) { Label("Share link", systemImage: "square.and.arrow.up") }
                Button {
                    UIPasteboard.general.string = url.absoluteString
                    LocusHaptics.light()
                } label: {
                    Label("Copy link", systemImage: "doc.on.doc")
                }
            }
            Button(role: .destructive, action: onDelete) {
                Label("Delete chat", systemImage: "trash")
            }
        }
    }

    private func metaChip(_ systemImage: String, _ text: String, tint: Color? = nil) -> some View {
        HStack(spacing: 4) {
            Image(systemName: systemImage)
                .font(.system(size: 9, weight: .semibold))
            Text(text)
                .font(.system(size: 10, weight: .medium))
        }
        .foregroundStyle(tint ?? palette.muted)
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(palette.glassFillSoft)
        .clipShape(Capsule())
    }
}
