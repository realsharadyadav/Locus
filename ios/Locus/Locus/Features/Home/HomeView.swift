import SwiftUI

/// Home — the web dashboard (`src/pages/HomePage.jsx`) as a native page: hero, live
/// capability strip, stats, quick actions and recent activity. Every number is live.
struct HomeView: View {
    @Environment(AppState.self) private var app
    @Environment(\.locusPalette) private var palette
    @State private var model = HomeModel()

    private var greeting: String {
        LocusFormat.greeting(forHour: Calendar.current.component(.hour, from: Date()))
    }

    var body: some View {
        PageScaffold(
            kicker: "Your second brain",
            title: model.isEmpty ? "Welcome to Locus" : greeting,
            subtitle: model.isEmpty
                ? "Upload files to a library, then ask a question."
                : "Your second brain is ready — ask it anything."
        ) {
            if model.loadingContent {
                skeletons
            } else {
                capabilities
                stats
                quickActions
                if model.isEmpty { onboarding } else { panels }
            }
        }
        .refreshable { await model.load() }
        .task { await model.loadIfNeeded() }
    }

    // MARK: - Sections

    private var skeletons: some View {
        VStack(spacing: 14) {
            ForEach(0..<3, id: \.self) { _ in SkeletonCard(height: 92) }
        }
    }

    private var capabilities: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "What Locus can do", subtitle: "Live from your setup — tap a card to jump in.")

            LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)], spacing: 12) {
                ForEach(model.capabilityChips) { chip in
                    Button {
                        LocusHaptics.light()
                        go(to: chip.destination)
                    } label: {
                        CapabilityCard(chip: chip)
                    }
                    .buttonStyle(.plain)
                }
                if !model.loadedCapabilities {
                    ForEach(0..<2, id: \.self) { _ in SkeletonCard(height: 104) }
                }
            }
        }
    }

    private var stats: some View {
        HStack(spacing: 12) {
            StatTile(systemImage: "folder.fill", value: model.stores.count, label: "Libraries") {
                go(to: .tab(.library))
            }
            StatTile(systemImage: "doc.text.fill", value: model.files.count, label: "Files") {
                go(to: .tab(.library))
            }
            StatTile(systemImage: "safari.fill", value: model.chats.count, label: "Chats") {
                go(to: .tab(.ask))
            }
        }
    }

    private var quickActions: some View {
        HStack(spacing: 8) {
            PillChip(title: "Create library", systemImage: "folder.badge.plus") {
                LocusHaptics.light()
                app.libraryIntent = .create
                app.tab = .library
            }
            PillChip(title: "Upload", systemImage: "arrow.up.doc.fill") {
                LocusHaptics.light()
                app.libraryIntent = .upload
                app.tab = .library
            }
            PillChip(title: "Ask", systemImage: "safari.fill") {
                LocusHaptics.light()
                app.tab = .ask
            }
        }
    }

    private var onboarding: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                Text("Get started in two steps")
                    .font(LocusFont.section())
                    .foregroundStyle(palette.heading)
                StepRow(number: 1, text: "Create a library and upload your documents.")
                StepRow(number: 2, text: "Open Ask and ask questions grounded in those files.")
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var panels: some View {
        VStack(spacing: 14) {
            PanelCard(title: "Recent files", actionTitle: "View all") {
                go(to: .tab(.library))
            } content: {
                ForEach(model.recentFiles) { file in
                    PanelRow(
                        systemImage: "doc.text.fill",
                        title: file.name,
                        subtitle: LocusFormat.fileMetaLine(file),
                        trailing: LocusFormat.displayTime(file.createdAt)
                    ) {
                        LocusHaptics.light()
                        app.tab = .library
                    }
                }
            }

            PanelCard(title: "Recent chats", actionTitle: "View all") {
                go(to: .tab(.ask))
            } content: {
                if model.recentChats.isEmpty {
                    Text("No chats yet. Start one in Ask.")
                        .font(LocusFont.caption())
                        .foregroundStyle(palette.muted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, 4)
                } else {
                    ForEach(model.recentChats) { chat in
                        PanelRow(
                            systemImage: "safari.fill",
                            title: chat.title,
                            subtitle: LocusFormat.plural(chat.messageCount, "message"),
                            trailing: LocusFormat.displayTime(chat.updatedAt)
                        ) {
                            LocusHaptics.light()
                            app.pendingChatId = chat.id
                            app.tab = .ask
                        }
                    }
                }
            }
        }
    }

    // MARK: - Navigation

    private func go(to destination: HomeDestination) {
        switch destination {
        case .tab(let tab): app.tab = tab
        case .settings: app.showsSettings = true
        }
    }
}

// MARK: - Pieces

private struct SectionHeader: View {
    @Environment(\.locusPalette) private var palette
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(LocusFont.section())
                .foregroundStyle(palette.heading)
            Text(subtitle)
                .font(LocusFont.caption())
                .foregroundStyle(palette.muted)
        }
    }
}

private struct CapabilityCard: View {
    @Environment(\.locusPalette) private var palette
    let chip: CapabilityChip

    private var tint: Color { chip.accent ?? palette.accent }

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Image(systemName: chip.systemImage)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 30, height: 30)
                .background(tint.opacity(0.16))
                .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
            Text(chip.title)
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(palette.heading)
                .lineLimit(2)
                .multilineTextAlignment(.leading)
            Text(chip.subtitle)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(palette.muted)
                .lineLimit(4)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, minHeight: 104, alignment: .topLeading)
        .padding(13)
        .locusCard(cornerRadius: 16)
    }
}

private struct StatTile: View {
    @Environment(\.locusPalette) private var palette
    let systemImage: String
    let value: Int
    let label: String
    let action: () -> Void

    var body: some View {
        Button {
            LocusHaptics.light()
            action()
        } label: {
            VStack(alignment: .leading, spacing: 5) {
                Image(systemName: systemImage)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(palette.accent)
                Text("\(value)")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(palette.heading)
                    .contentTransition(.numericText())
                Text(label)
                    .font(LocusFont.caption())
                    .foregroundStyle(palette.muted)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(13)
            .locusCard(cornerRadius: 16)
        }
        .buttonStyle(.plain)
    }
}

private struct StepRow: View {
    @Environment(\.locusPalette) private var palette
    let number: Int
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Text("\(number)")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 22, height: 22)
                .background(palette.accentGradient)
                .clipShape(Circle())
            Text(text)
                .font(LocusFont.body())
                .foregroundStyle(palette.text)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

private struct PanelCard<Content: View>: View {
    @Environment(\.locusPalette) private var palette
    let title: String
    let actionTitle: String
    let action: () -> Void
    @ViewBuilder var content: Content

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text(title)
                        .font(LocusFont.section())
                        .foregroundStyle(palette.heading)
                    Spacer()
                    Button(actionTitle) {
                        LocusHaptics.light()
                        action()
                    }
                    .font(LocusFont.caption())
                    .foregroundStyle(palette.accent)
                    .buttonStyle(.plain)
                }
                content
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

private struct PanelRow: View {
    @Environment(\.locusPalette) private var palette
    let systemImage: String
    let title: String
    let subtitle: String
    let trailing: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: systemImage)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(palette.accent)
                    .frame(width: 18)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(palette.heading)
                        .lineLimit(1)
                    Text(subtitle)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(palette.muted)
                        .lineLimit(1)
                }
                Spacer(minLength: 8)
                Text(trailing)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(palette.subtle)
            }
            .padding(.vertical, 7)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
