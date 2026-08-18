import SwiftUI

/// Consistent page scaffolding: kicker + title + subtitle header, scrollable content,
/// and automatic bottom clearance so nothing hides behind the floating dock.
struct PageScaffold<Content: View>: View {
    @Environment(\.locusPalette) private var palette
    let kicker: String
    let title: String
    let subtitle: String
    @ViewBuilder var content: Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(kicker.uppercased())
                        .font(LocusFont.kicker())
                        .tracking(2)
                        .foregroundStyle(palette.accent)
                    Text(title)
                        .font(LocusFont.title())
                        .foregroundStyle(palette.heading)
                    if !subtitle.isEmpty {
                        Text(subtitle)
                            .font(LocusFont.body())
                            .foregroundStyle(palette.muted)
                    }
                }
                .padding(.top, 56) // clear the floating hamburger

                content
            }
            .padding(.horizontal, 16)
            .padding(.bottom, LocusMetrics.bottomClearance)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .scrollIndicators(.hidden)
    }
}

/// Friendly empty state used across pages.
struct EmptyStateCard: View {
    @Environment(\.locusPalette) private var palette
    let systemImage: String
    let title: String
    let message: String

    var body: some View {
        GlassCard(padding: 28) {
            VStack(spacing: 12) {
                Image(systemName: systemImage)
                    .font(.system(size: 30, weight: .medium))
                    .foregroundStyle(palette.accent)
                Text(title)
                    .font(LocusFont.section())
                    .foregroundStyle(palette.heading)
                Text(message)
                    .font(LocusFont.caption())
                    .foregroundStyle(palette.muted)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity)
        }
    }
}
