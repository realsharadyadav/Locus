import SwiftUI

// MARK: - Glass primitive

extension View {
    /// Real Liquid Glass on iOS 26+, frosted material on older systems. Same layout either way.
    @ViewBuilder
    func locusGlass<S: InsettableShape>(in shape: S) -> some View {
        if #available(iOS 26.0, *) {
            self.glassEffect(.regular, in: shape)
        } else {
            self.background(shape.fill(.ultraThinMaterial))
        }
    }

    /// Standard card chrome: glass fill + hairline edge + soft shadow.
    func locusCard(cornerRadius: CGFloat = LocusMetrics.cardRadius) -> some View {
        modifier(LocusCardModifier(cornerRadius: cornerRadius))
    }
}

private struct LocusCardModifier: ViewModifier {
    @Environment(\.locusPalette) private var palette
    let cornerRadius: CGFloat

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        content
            .background(palette.glassFill)
            .clipShape(shape)
            .locusGlass(in: shape)
            .overlay(shape.strokeBorder(palette.glassEdge, lineWidth: 1))
            .shadow(color: Color.black.opacity(palette.scheme == .dark ? 0.28 : 0.08),
                    radius: 24, x: 0, y: 12)
    }
}

// MARK: - Components

/// Rounded glass card container.
struct GlassCard<Content: View>: View {
    var padding: CGFloat = 16
    var cornerRadius: CGFloat = LocusMetrics.cardRadius
    @ViewBuilder var content: Content

    var body: some View {
        content
            .padding(padding)
            .locusCard(cornerRadius: cornerRadius)
    }
}

/// Floating circular glass button — the header buttons in the web mobile view.
struct GlassCircleButton: View {
    @Environment(\.locusPalette) private var palette
    let systemImage: String
    var size: CGFloat = 42
    /// Spoken by VoiceOver and matched by UI tests. Falls back to the SF Symbol name,
    /// which is meaningless for both — always pass one for icon-only buttons.
    var label: String? = nil
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.system(size: size * 0.38, weight: .semibold))
                .foregroundStyle(palette.text)
                .frame(width: size, height: size)
                .background(palette.glassFill)
                .clipShape(Circle())
                .locusGlass(in: Circle())
                .overlay(Circle().strokeBorder(palette.glassEdge, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(label ?? systemImage.replacingOccurrences(of: ".", with: " ")))
    }
}

/// Pill chip — selectable filter/toggle used across composer, options and pickers.
struct PillChip: View {
    @Environment(\.locusPalette) private var palette
    let title: String
    var systemImage: String? = nil
    var active: Bool = false
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 5) {
                if let systemImage {
                    Image(systemName: systemImage)
                        .font(.system(size: 11, weight: .semibold))
                }
                Text(title)
                    .font(.system(size: 12, weight: .semibold))
            }
            .foregroundStyle(active ? palette.accent : palette.muted)
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .background(active ? palette.accentSoft : palette.glassFillSoft)
            .clipShape(Capsule())
            .locusGlass(in: Capsule())
            .overlay(Capsule().strokeBorder(active ? palette.accent.opacity(0.55) : palette.glassEdgeSoft, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

/// Full-width purple gradient primary action.
struct GradientPrimaryButton: View {
    @Environment(\.locusPalette) private var palette
    let title: String
    var systemImage: String? = nil
    var disabled: Bool = false
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if let systemImage {
                    Image(systemName: systemImage)
                        .font(.system(size: 15, weight: .semibold))
                }
                Text(title)
                    .font(.system(size: 16, weight: .bold))
            }
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14)
            .background(palette.accentGradient)
            .clipShape(RoundedRectangle(cornerRadius: LocusMetrics.buttonRadius, style: .continuous))
            .shadow(color: palette.accent.opacity(0.35), radius: 16, x: 0, y: 8)
        }
        .buttonStyle(.plain)
        .opacity(disabled ? 0.5 : 1)
        .disabled(disabled)
    }
}

/// One labelled row of wrap-around selectable capsules (Private room options, effort dial).
struct SegmentedPills: View {
    @Environment(\.locusPalette) private var palette
    let options: [String]
    @Binding var selection: String

    var body: some View {
        HStack(spacing: 8) {
            ForEach(options, id: \.self) { option in
                Button {
                    selection = option
                } label: {
                    Text(option)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(selection == option ? .white : palette.muted)
                        .padding(.horizontal, 13)
                        .padding(.vertical, 8)
                        .background(
                            selection == option
                                ? AnyShapeStyle(palette.accentGradient)
                                : AnyShapeStyle(palette.glassFillSoft)
                        )
                        .clipShape(Capsule())
                        .overlay(
                            Capsule().strokeBorder(
                                selection == option ? Color.clear : palette.glassEdgeSoft,
                                lineWidth: 1
                            )
                        )
                }
                .buttonStyle(.plain)
            }
        }
    }
}

/// Glass placeholder with a travelling sheen — the web's `.skeleton-card` while data loads.
struct SkeletonCard: View {
    @Environment(\.locusPalette) private var palette
    var height: CGFloat = 92
    var cornerRadius: CGFloat = 16
    @State private var shimmer = false

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(palette.glassFillSoft)
            .frame(height: height)
            .overlay(
                LinearGradient(
                    colors: [.clear, palette.glassEdgeSoft, .clear],
                    startPoint: .leading, endPoint: .trailing
                )
                .offset(x: shimmer ? 220 : -220)
                .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(palette.glassEdgeSoft, lineWidth: 1)
            )
            .onAppear {
                withAnimation(.linear(duration: 1.3).repeatForever(autoreverses: false)) {
                    shimmer = true
                }
            }
            .accessibilityHidden(true)
    }
}

/// Small dot + label status, e.g. server reachability.
struct StatusDot: View {
    @Environment(\.locusPalette) private var palette
    let ok: Bool

    var body: some View {
        Circle()
            .fill(ok ? palette.success : palette.danger)
            .frame(width: 7, height: 7)
            .shadow(color: (ok ? palette.success : palette.danger).opacity(0.5), radius: 4)
    }
}

/// The Locus mark — purple gradient disc with an orbit dot, like the web logo.
struct LocusLogo: View {
    @Environment(\.locusPalette) private var palette
    var size: CGFloat = 30

    var body: some View {
        ZStack {
            Circle()
                .fill(palette.accentGradient)
            Circle()
                .strokeBorder(Color.white.opacity(0.55), lineWidth: size * 0.045)
                .frame(width: size * 0.52, height: size * 0.52)
            Circle()
                .fill(Color.white)
                .frame(width: size * 0.14, height: size * 0.14)
                .offset(x: size * 0.26, y: -size * 0.26)
        }
        .frame(width: size, height: size)
        .shadow(color: palette.accent.opacity(0.45), radius: size * 0.3)
        .accessibilityHidden(true)
    }
}

enum LocusHaptics {
    static func selection() {
        UISelectionFeedbackGenerator().selectionChanged()
    }

    static func light() {
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
    }

    static func medium() {
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
    }

    static func warning() {
        UINotificationFeedbackGenerator().notificationOccurred(.warning)
    }

    static func success() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }
}
