import SwiftUI

/// Reply copilot. Suggest mode never sends anything on its own — tapping a draft only loads it
/// into the composer, so the host still presses send.
struct CopilotSheet: View {
    @Environment(\.locusPalette) private var palette
    @Environment(\.dismiss) private var dismiss
    let model: RoomModel

    var body: some View {
        ZStack {
            GlowBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Reply copilot")
                            .font(LocusFont.title())
                            .foregroundStyle(palette.heading)
                        Text("Drafts in your tone. Nothing sends until you do.")
                            .font(LocusFont.caption())
                            .foregroundStyle(palette.muted)
                    }
                    .padding(.top, 18)

                    if model.copilotBusy {
                        VStack(spacing: 10) {
                            ForEach(0..<3, id: \.self) { _ in SkeletonCard(height: 60) }
                        }
                    } else if model.copilotSuggestions.isEmpty {
                        EmptyStateCard(
                            systemImage: "sparkles",
                            title: "No drafts yet",
                            message: "Ask for suggestions and pick one to edit before sending."
                        )
                    } else {
                        ForEach(model.copilotSuggestions, id: \.self) { suggestion in
                            Button {
                                LocusHaptics.light()
                                model.draft = suggestion
                                dismiss()
                            } label: {
                                GlassCard {
                                    HStack(alignment: .top, spacing: 9) {
                                        Image(systemName: "text.bubble")
                                            .font(.system(size: 12, weight: .semibold))
                                            .foregroundStyle(palette.accent)
                                        Text(suggestion)
                                            .font(.system(size: 14))
                                            .foregroundStyle(palette.text)
                                            .multilineTextAlignment(.leading)
                                            .fixedSize(horizontal: false, vertical: true)
                                        Spacer(minLength: 0)
                                    }
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }

                    GradientPrimaryButton(
                        title: model.copilotBusy ? "Thinking…" : "Suggest replies",
                        systemImage: "sparkles",
                        disabled: model.copilotBusy
                    ) {
                        LocusHaptics.light()
                        Task { await model.suggestReplies() }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 30)
            }
            .scrollIndicators(.hidden)
        }
        .task {
            if model.copilotSuggestions.isEmpty { await model.suggestReplies() }
        }
    }
}
