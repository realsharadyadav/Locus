import SwiftUI

/// Who is in the room and what device they are on. Host-key authorised — a link guest can chat
/// but never sees anyone's device details.
struct GuestsPanel: View {
    @Environment(\.locusPalette) private var palette
    let guests: [SecretChatParticipantDetail]
    let refresh: () async -> Void

    var body: some View {
        ZStack {
            GlowBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Guests")
                            .font(LocusFont.title())
                            .foregroundStyle(palette.heading)
                        Text("Everyone who has opened this chat's link.")
                            .font(LocusFont.caption())
                            .foregroundStyle(palette.muted)
                    }
                    .padding(.top, 18)

                    if guests.isEmpty {
                        EmptyStateCard(
                            systemImage: "person.2",
                            title: "No one yet",
                            message: "Share the link and they'll appear here as soon as they open it."
                        )
                    } else {
                        ForEach(guests) { guest in
                            GlassCard {
                                VStack(alignment: .leading, spacing: 8) {
                                    HStack(spacing: 8) {
                                        StatusDot(ok: guest.online)
                                        Text(guest.name.isEmpty ? "Anonymous" : guest.name)
                                            .font(.system(size: 15, weight: .bold))
                                            .foregroundStyle(palette.heading)
                                        if guest.role == "host" {
                                            Text("HOST")
                                                .font(.system(size: 9, weight: .bold))
                                                .foregroundStyle(palette.accent)
                                                .padding(.horizontal, 6)
                                                .padding(.vertical, 2)
                                                .background(palette.accentSoft)
                                                .clipShape(Capsule())
                                        }
                                        Spacer()
                                        if guest.typing {
                                            Text("typing…")
                                                .font(.system(size: 10, weight: .semibold))
                                                .foregroundStyle(palette.accent)
                                        }
                                    }

                                    detail("Device", [guest.device, guest.os, client(for: guest)])
                                    detail("Network", [guest.ip, guest.timezone, guest.language])
                                    detail("Screen", [guest.screen, guest.viewport])
                                    detail("Activity", [
                                        LocusFormat.plural(guest.messageCount, "message"),
                                        "\(guest.minutesInRoom) min in chat",
                                        "seen \(LocusFormat.displayTime(guest.lastSeen))",
                                    ])
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 30)
            }
            .scrollIndicators(.hidden)
            .refreshable { await refresh() }
        }
    }

    /// The backend derives "browser" from the User-Agent, which has no meaning for a native
    /// client — so a Locus app connection is labelled as the app rather than "Unknown browser".
    private func client(for guest: SecretChatParticipantDetail) -> String {
        guest.userAgent.contains("Locus/") ? "Locus app" : guest.browser
    }

    private func detail(_ label: String, _ values: [String]) -> some View {
        let shown = values.filter { !$0.isEmpty }
        return Group {
            if !shown.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text(label.uppercased())
                        .font(.system(size: 9, weight: .bold))
                        .tracking(1)
                        .foregroundStyle(palette.subtle)
                    Text(shown.joined(separator: " · "))
                        .font(.system(size: 12))
                        .foregroundStyle(palette.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }
}
