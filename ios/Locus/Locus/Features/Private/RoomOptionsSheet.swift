import SwiftUI

/// Edit a live room: topic, the three lifetimes, and the AI reply settings.
struct RoomOptionsSheet: View {
    @Environment(\.locusPalette) private var palette
    @Environment(\.dismiss) private var dismiss
    let session: SecretChatSessionRead
    let onSave: (String, Int, Int, Int, String, String, Bool, Bool) async -> Void

    @State private var title: String
    @State private var ttlIndex: Int
    @State private var linkIndex = 0
    @State private var roomIndex = 0
    @State private var tone: String
    @State private var persona: String
    @State private var autopilot: Bool
    @State private var mimicMe: Bool
    @State private var saving = false

    private let tones = ["friendly", "professional", "playful", "brief"]

    init(session: SecretChatSessionRead, onSave: @escaping (String, Int, Int, Int, String, String, Bool, Bool) async -> Void) {
        self.session = session
        self.onSave = onSave
        _title = State(initialValue: session.title)
        _ttlIndex = State(initialValue: RoomOption.messageTTL.firstIndex { $0.seconds == session.messageTTLSeconds } ?? 0)
        _tone = State(initialValue: session.aiTone.isEmpty ? "friendly" : session.aiTone)
        _persona = State(initialValue: session.aiPersona)
        _autopilot = State(initialValue: session.aiAutopilot)
        _mimicMe = State(initialValue: session.aiMimicMe)
    }

    var body: some View {
        ZStack {
            GlowBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Chat options")
                        .font(LocusFont.title())
                        .foregroundStyle(palette.heading)
                        .padding(.top, 18)

                    GlassCard {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Topic")
                                .font(LocusFont.bodySemibold())
                                .foregroundStyle(palette.heading)
                            TextField("Topic", text: $title)
                                .font(.system(size: 15))
                                .foregroundStyle(palette.heading)
                                .tint(palette.accent)
                                .padding(11)
                                .background(palette.glassFillSoft)
                                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    picker("Disappearing messages", RoomOption.messageTTL.map(\.label), $ttlIndex)
                    // Both expiry pickers start at "Never": the backend takes a *duration from
                    // now*, not an absolute time, so leaving them alone must not silently
                    // re-arm a timer that is already running.
                    picker("Reset invite link expiry", RoomOption.linkExpiry.map(\.label), $linkIndex)
                    picker("Reset chat deletion", RoomOption.roomExpiry.map(\.label), $roomIndex)

                    GlassCard {
                        VStack(alignment: .leading, spacing: 11) {
                            Text("AI replies")
                                .font(LocusFont.bodySemibold())
                                .foregroundStyle(palette.heading)

                            Toggle(isOn: $autopilot) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("Autopilot")
                                        .font(.system(size: 14, weight: .semibold))
                                        .foregroundStyle(palette.heading)
                                    Text("Replies are drafted on the server and held for review, so they keep coming with the app closed.")
                                        .font(.system(size: 11))
                                        .foregroundStyle(palette.muted)
                                }
                            }
                            .tint(palette.accent)

                            Toggle(isOn: $mimicMe) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("Talk like me")
                                        .font(.system(size: 14, weight: .semibold))
                                        .foregroundStyle(palette.heading)
                                    Text("Uses your own past messages as style samples.")
                                        .font(.system(size: 11))
                                        .foregroundStyle(palette.muted)
                                }
                            }
                            .tint(palette.accent)

                            VStack(alignment: .leading, spacing: 7) {
                                Text("Tone")
                                    .font(.system(size: 12, weight: .semibold))
                                    .foregroundStyle(palette.muted)
                                ScrollView(.horizontal, showsIndicators: false) {
                                    HStack(spacing: 7) {
                                        ForEach(tones, id: \.self) { option in
                                            PillChip(title: option.capitalized, active: tone == option) {
                                                LocusHaptics.selection()
                                                tone = option
                                            }
                                        }
                                    }
                                    .padding(.vertical, 1)
                                }
                            }

                            VStack(alignment: .leading, spacing: 6) {
                                Text("Persona")
                                    .font(.system(size: 12, weight: .semibold))
                                    .foregroundStyle(palette.muted)
                                TextField("e.g. a busy founder who keeps it short", text: $persona, axis: .vertical)
                                    .lineLimit(1...3)
                                    .font(.system(size: 14))
                                    .foregroundStyle(palette.heading)
                                    .tint(palette.accent)
                                    .padding(11)
                                    .background(palette.glassFillSoft)
                                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    GradientPrimaryButton(title: saving ? "Saving…" : "Save changes",
                                          systemImage: "checkmark", disabled: saving) {
                        saving = true
                        LocusHaptics.light()
                        Task {
                            await onSave(
                                title,
                                RoomOption.messageTTL[ttlIndex].seconds,
                                RoomOption.linkExpiry[linkIndex].minutes,
                                RoomOption.roomExpiry[roomIndex].minutes,
                                tone, persona, autopilot, mimicMe
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

    private func picker(_ title: String, _ labels: [String], _ index: Binding<Int>) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 9) {
                Text(title)
                    .font(LocusFont.bodySemibold())
                    .foregroundStyle(palette.heading)
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
