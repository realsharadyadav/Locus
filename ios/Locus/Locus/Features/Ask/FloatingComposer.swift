import SwiftUI

/// The floating glass composer: chips row + `+` menu + growing text field + send.
/// Ask owns the effort dial and file scope; Private Chats (Phase 4) reuses the same shell with
/// `chips` and `menuItems` left empty.
struct FloatingComposer<Chips: View>: View {
    @Environment(\.locusPalette) private var palette
    @Binding var text: String
    var placeholder: String = "Ask anything…"
    var busy: Bool = false
    var menuItems: [ComposerMenuItem] = []
    @ViewBuilder var chips: Chips
    var onSend: () -> Void
    var onStop: (() -> Void)?

    @FocusState private var focused: Bool

    private var canSend: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            // One fixed row — a dropdown plus icons, so nothing ever scrolls sideways.
            // Rooms pass no chips, so the row collapses rather than leaving a gap.
            if Chips.self != EmptyView.self {
                HStack(spacing: 8) { chips }
            }

            HStack(alignment: .bottom, spacing: 9) {
                if !menuItems.isEmpty {
                    Menu {
                        ForEach(menuItems) { item in
                            Button {
                                LocusHaptics.light()
                                item.action()
                            } label: {
                                Label(item.title, systemImage: item.systemImage)
                            }
                        }
                    } label: {
                        Image(systemName: "plus")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(palette.text)
                            .frame(width: 34, height: 34)
                            .background(palette.glassFillSoft)
                            .clipShape(Circle())
                            .overlay(Circle().strokeBorder(palette.glassEdgeSoft, lineWidth: 1))
                    }
                }

                TextField(placeholder, text: $text, axis: .vertical)
                    .lineLimit(1...5)
                    .font(.system(size: 15))
                    .foregroundStyle(palette.heading)
                    .tint(palette.accent)
                    .focused($focused)
                    .padding(.vertical, 8)
                    .submitLabel(.send)

                Button {
                    if busy { onStop?() } else { onSend() }
                } label: {
                    Image(systemName: busy ? "stop.fill" : "arrow.up")
                        .font(.system(size: 15, weight: .bold))
                        // White only when the button has a filled background; on the empty
                        // state it sits on glass, where white is invisible in Bright mode.
                        .foregroundStyle(busy || canSend ? AnyShapeStyle(.white) : AnyShapeStyle(palette.muted))
                        .frame(width: 34, height: 34)
                        .background(
                            busy
                                ? AnyShapeStyle(palette.danger)
                                : AnyShapeStyle(canSend ? AnyShapeStyle(palette.accentGradient) : AnyShapeStyle(palette.glassFillSoft))
                        )
                        .clipShape(Circle())
                }
                .buttonStyle(.plain)
                .disabled(!busy && !canSend)
                .animation(.spring(duration: 0.25), value: busy)
            }
        }
        .padding(.horizontal, 13)
        .padding(.vertical, 11)
        .background(palette.glassFillStrong)
        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .locusGlass(in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .strokeBorder(focused ? palette.accent.opacity(0.45) : palette.glassEdge, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.3), radius: 20, y: 10)
        .animation(.spring(duration: 0.28), value: focused)
    }
}

struct ComposerMenuItem: Identifiable {
    let id = UUID()
    let title: String
    let systemImage: String
    let action: () -> Void
}

/// Compact labelled dropdown for the composer row (the effort dial).
struct ComposerDropdown<Option: Hashable>: View {
    @Environment(\.locusPalette) private var palette
    let options: [Option]
    let title: (Option) -> String
    let systemImage: (Option) -> String
    @Binding var selection: Option

    var body: some View {
        Menu {
            ForEach(options, id: \.self) { option in
                Button {
                    LocusHaptics.selection()
                    selection = option
                } label: {
                    Label(title(option), systemImage: systemImage(option))
                }
            }
        } label: {
            HStack(spacing: 5) {
                Image(systemName: systemImage(selection))
                    .font(.system(size: 11, weight: .semibold))
                Text(title(selection))
                    .font(.system(size: 12, weight: .semibold))
                Image(systemName: "chevron.up.chevron.down")
                    .font(.system(size: 8, weight: .bold))
                    .opacity(0.7)
            }
            .foregroundStyle(palette.accent)
            .padding(.horizontal, 11)
            .padding(.vertical, 7)
            .background(palette.accentSoft)
            .clipShape(Capsule())
            .overlay(Capsule().strokeBorder(palette.accent.opacity(0.45), lineWidth: 1))
        }
    }
}

/// Icon-only composer control, with an optional count badge so a scoped selection is still
/// readable without spending a whole label on it.
struct ComposerIconButton: View {
    @Environment(\.locusPalette) private var palette
    let systemImage: String
    var badge: Int?
    var active: Bool = false
    var accessibilityLabel: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack(alignment: .topTrailing) {
                Image(systemName: systemImage)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(active ? palette.accent : palette.muted)
                    .frame(width: 32, height: 30)
                    .background(active ? palette.accentSoft : palette.glassFillSoft)
                    .clipShape(Capsule())
                    .overlay(
                        Capsule().strokeBorder(
                            active ? palette.accent.opacity(0.45) : palette.glassEdgeSoft,
                            lineWidth: 1
                        )
                    )
                if let badge, badge > 0 {
                    Text("\(badge)")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 4)
                        .padding(.vertical, 1)
                        .background(palette.accentGradient)
                        .clipShape(Capsule())
                        .offset(x: 4, y: -3)
                }
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(accessibilityLabel))
    }
}
