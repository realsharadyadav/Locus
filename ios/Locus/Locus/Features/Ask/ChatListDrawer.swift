import SwiftUI

/// The chat rail as a sheet: new chat, pick a chat, swipe to delete, delete all.
struct ChatListDrawer: View {
    @Environment(\.locusPalette) private var palette
    @Environment(\.dismiss) private var dismiss
    let chats: [ChatSessionRead]
    let activeChatId: Int?
    let onNew: () -> Void
    let onOpen: (Int) -> Void
    let onDelete: (Int) -> Void
    let onDeleteAll: () -> Void

    @State private var confirmDeleteAll = false

    var body: some View {
        ZStack {
            GlowBackground()
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("Chats")
                        .font(LocusFont.title())
                        .foregroundStyle(palette.heading)
                    Spacer()
                    if !chats.isEmpty {
                        Button {
                            confirmDeleteAll = true
                        } label: {
                            Image(systemName: "trash")
                                .font(.system(size: 14, weight: .semibold))
                                .foregroundStyle(palette.danger)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 18)

                GradientPrimaryButton(title: "New chat", systemImage: "plus") {
                    LocusHaptics.light()
                    onNew()
                    dismiss()
                }
                .padding(.horizontal, 20)

                if chats.isEmpty {
                    EmptyStateCard(
                        systemImage: "bubble.left.and.bubble.right",
                        title: "No chats yet",
                        message: "Ask your first question to start one."
                    )
                    .padding(.horizontal, 20)
                    Spacer()
                } else {
                    List {
                        ForEach(chats) { chat in
                            Button {
                                LocusHaptics.light()
                                onOpen(chat.id)
                                dismiss()
                            } label: {
                                HStack(spacing: 10) {
                                    Image(systemName: "safari.fill")
                                        .font(.system(size: 13))
                                        .foregroundStyle(chat.id == activeChatId ? palette.accent : palette.subtle)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(chat.title)
                                            .font(.system(size: 14, weight: .semibold))
                                            .foregroundStyle(palette.heading)
                                            .lineLimit(1)
                                        Text("\(LocusFormat.plural(chat.messageCount, "message")) · \(LocusFormat.displayTime(chat.updatedAt))")
                                            .font(.system(size: 11))
                                            .foregroundStyle(palette.muted)
                                    }
                                    Spacer()
                                    if chat.id == activeChatId {
                                        Circle().fill(palette.accent).frame(width: 6, height: 6)
                                    }
                                }
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .listRowBackground(Color.clear)
                            .listRowSeparatorTint(palette.glassEdgeSoft)
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) {
                                    LocusHaptics.warning()
                                    onDelete(chat.id)
                                } label: {
                                    Label("Delete", systemImage: "trash")
                                }
                            }
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                }
            }
        }
        .confirmationDialog("Delete all chats?", isPresented: $confirmDeleteAll, titleVisibility: .visible) {
            Button("Delete all", role: .destructive) {
                LocusHaptics.warning()
                onDeleteAll()
                dismiss()
            }
            Button("Cancel", role: .cancel) {}
        }
    }
}
