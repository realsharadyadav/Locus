import SwiftUI

/// Create a room: topic plus the three lifetimes. `link_expires_at` only stops *new* guests
/// joining — anyone already in keeps chatting — while `expires_at` ends the room for everybody,
/// so the two are deliberately separate controls (AGENTS.md "Private chat rules").
struct NewRoomSheet: View {
    @Environment(\.locusPalette) private var palette
    @Environment(\.dismiss) private var dismiss

    let onCreate: (String, Int, Int, Int) async -> Void

    @State private var title = ""
    @State private var ttlIndex = 0
    @State private var linkIndex = 0
    @State private var roomIndex = 0
    @State private var creating = false

    var body: some View {
        ZStack {
            GlowBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("New private chat")
                            .font(LocusFont.title())
                            .foregroundStyle(palette.heading)
                        Text("Share the link with one person. Only they can read it.")
                            .font(LocusFont.body())
                            .foregroundStyle(palette.muted)
                    }
                    .padding(.top, 18)

                    GlassCard {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Topic")
                                .font(LocusFont.bodySemibold())
                                .foregroundStyle(palette.heading)
                            TextField("What is this chat about?", text: $title)
                                .font(.system(size: 15))
                                .foregroundStyle(palette.heading)
                                .tint(palette.accent)
                                .padding(11)
                                .background(palette.glassFillSoft)
                                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    optionCard(
                        title: "Disappearing messages",
                        note: "Messages vanish for everyone once the timer runs out.",
                        labels: RoomOption.messageTTL.map(\.label),
                        index: $ttlIndex
                    )
                    optionCard(
                        title: "Invite link expires",
                        note: "Stops new people joining. Anyone already here keeps chatting.",
                        labels: RoomOption.linkExpiry.map(\.label),
                        index: $linkIndex
                    )
                    optionCard(
                        title: "Delete whole chat",
                        note: "Ends the chat for everyone and removes the messages.",
                        labels: RoomOption.roomExpiry.map(\.label),
                        index: $roomIndex
                    )

                    GradientPrimaryButton(
                        title: creating ? "Creating…" : "Create chat",
                        systemImage: "plus",
                        disabled: creating
                    ) {
                        creating = true
                        LocusHaptics.medium()
                        Task {
                            await onCreate(
                                title,
                                RoomOption.messageTTL[ttlIndex].seconds,
                                RoomOption.linkExpiry[linkIndex].minutes,
                                RoomOption.roomExpiry[roomIndex].minutes
                            )
                            dismiss()
                        }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 32)
            }
            .scrollIndicators(.hidden)
        }
    }

    private func optionCard(title: String, note: String, labels: [String], index: Binding<Int>) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 9) {
                Text(title)
                    .font(LocusFont.bodySemibold())
                    .foregroundStyle(palette.heading)
                Text(note)
                    .font(.system(size: 11))
                    .foregroundStyle(palette.muted)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 7) {
                        ForEach(Array(labels.enumerated()), id: \.offset) { offset, label in
                            PillChip(title: label, active: index.wrappedValue == offset) {
                                LocusHaptics.selection()
                                index.wrappedValue = offset
                            }
                        }
                    }
                    .padding(.vertical, 1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
