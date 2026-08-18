import SwiftUI

/// Point a room at a phone number on Telegram instead of a share link. Host-only: the bridge
/// messages from the host's own account, so the backend authorises this with the host key.
///
/// Only reachable when the deployment actually has a Telegram account connected
/// (`/bridge/status` reports `connected`) — without that, linking cannot resolve a contact.
struct TelegramConnectSheet: View {
    @Environment(\.locusPalette) private var palette
    @Environment(\.dismiss) private var dismiss
    let token: String
    let status: SecretChatBridgeStatus
    /// Called after a successful link or unlink so the room can refresh its header.
    let onChange: () -> Void

    @State private var bridge: SecretChatBridgeRead?
    @State private var phone = ""
    @State private var greeting = ""
    @State private var loading = true
    @State private var busy = false
    @State private var errorMessage: String?
    @State private var confirmUnlink = false

    var body: some View {
        ZStack {
            GlowBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header

                    if loading {
                        SkeletonCard(height: 110)
                    } else if let bridge {
                        linkedCard(bridge)
                    } else {
                        connectCard
                    }

                    if let errorMessage {
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .font(.system(size: 12))
                                .foregroundStyle(palette.danger)
                            Text(errorMessage)
                                .font(.system(size: 12))
                                .foregroundStyle(palette.danger)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .padding(11)
                        .background(palette.danger.opacity(0.12))
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 32)
            }
            .scrollIndicators(.hidden)
        }
        .task { await load() }
        .confirmationDialog("Disconnect this number?", isPresented: $confirmUnlink, titleVisibility: .visible) {
            Button("Disconnect", role: .destructive) {
                Task { await unlink() }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Messages already delivered stay on their phone.")
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Telegram")
                .font(LocusFont.title())
                .foregroundStyle(palette.heading)
            Text(status.connected
                 ? "Sends from \(status.account.isEmpty ? "your account" : status.account). They chat in Telegram; you see it here."
                 : "This server has no Telegram account connected.")
                .font(LocusFont.body())
                .foregroundStyle(palette.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.top, 18)
    }

    private func linkedCard(_ bridge: SecretChatBridgeRead) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 10) {
                    Image(systemName: "paperplane.fill")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(palette.accent)
                        .frame(width: 38, height: 38)
                        .background(palette.accentSoft)
                        .clipShape(RoundedRectangle(cornerRadius: 11, style: .continuous))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(bridge.displayName)
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(palette.heading)
                        Text(bridge.peerUsername.isEmpty ? bridge.phone : "@\(bridge.peerUsername) · \(bridge.phone)")
                            .font(.system(size: 11))
                            .foregroundStyle(palette.muted)
                    }
                    Spacer(minLength: 0)
                }

                if let outbound = bridge.lastOutboundAt {
                    detail("Last sent", LocusFormat.displayTime(outbound))
                }
                if let inbound = bridge.lastInboundAt {
                    detail("Last received", LocusFormat.displayTime(inbound))
                }
                if !bridge.lastError.isEmpty {
                    detail("Last error", bridge.lastError, tint: palette.danger)
                }

                Button {
                    LocusHaptics.light()
                    confirmUnlink = true
                } label: {
                    HStack(spacing: 7) {
                        Image(systemName: "link.badge.plus")
                            .font(.system(size: 12, weight: .semibold))
                        Text("Disconnect")
                            .font(.system(size: 14, weight: .semibold))
                    }
                    .foregroundStyle(palette.danger)
                }
                .buttonStyle(.plain)
                .disabled(busy)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var connectCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Phone number")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(palette.muted)
                    TextField("+91 98765 43210", text: $phone)
                        .keyboardType(.phonePad)
                        .textContentType(.telephoneNumber)
                        .font(.system(size: 15))
                        .foregroundStyle(palette.heading)
                        .tint(palette.accent)
                        .padding(11)
                        .background(palette.glassFillSoft)
                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                    Text("They must already be a Telegram contact reachable from your account.")
                        .font(.system(size: 10))
                        .foregroundStyle(palette.subtle)
                }

                VStack(alignment: .leading, spacing: 5) {
                    Text("First message (optional)")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(palette.muted)
                    TextField("So they know why a chat just appeared", text: $greeting, axis: .vertical)
                        .lineLimit(1...3)
                        .font(.system(size: 14))
                        .foregroundStyle(palette.heading)
                        .tint(palette.accent)
                        .padding(11)
                        .background(palette.glassFillSoft)
                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                }

                GradientPrimaryButton(
                    title: busy ? "Connecting…" : "Connect",
                    systemImage: "paperplane.fill",
                    disabled: busy || !status.connected || phone.trimmingCharacters(in: .whitespaces).count < 6
                ) {
                    Task { await link() }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func detail(_ label: String, _ value: String, tint: Color? = nil) -> some View {
        HStack(spacing: 6) {
            Text(label.uppercased())
                .font(.system(size: 9, weight: .bold))
                .tracking(1)
                .foregroundStyle(palette.subtle)
            Text(value)
                .font(.system(size: 11))
                .foregroundStyle(tint ?? palette.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func load() async {
        bridge = try? await APIClient.shared.secretChatBridge(token, hostKey: PrivateIdentity.hostKey)
        loading = false
    }

    private func link() async {
        busy = true
        errorMessage = nil
        do {
            bridge = try await APIClient.shared.secretChatLinkBridge(
                token,
                hostKey: PrivateIdentity.hostKey,
                phone: phone.trimmingCharacters(in: .whitespaces),
                greeting: greeting.trimmingCharacters(in: .whitespacesAndNewlines)
            )
            LocusHaptics.success()
            onChange()
        } catch {
            // The backend explains the real reasons: not a contact, or already bridged to
            // another room (inbound routing has to stay unambiguous).
            errorMessage = error.localizedDescription
            LocusHaptics.warning()
        }
        busy = false
    }

    private func unlink() async {
        busy = true
        try? await APIClient.shared.secretChatUnlinkBridge(token, hostKey: PrivateIdentity.hostKey)
        bridge = nil
        busy = false
        LocusHaptics.warning()
        onChange()
    }
}
