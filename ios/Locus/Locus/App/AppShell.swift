import SwiftUI

/// Root shell: glow background, the active page (all kept alive so scroll/stream state
/// survives tab switches), a floating hamburger, the side menu and the toast stack.
/// Navigation lives in the drawer rather than a bottom dock, so every page gets the full
/// screen and the only chrome over content is a transparent glass button.
struct AppShell: View {
    @Environment(AppState.self) private var app
    @Environment(\.locusPalette) private var palette
    @State private var menuOpen = false
    @State private var libraryCount: Int?

    var body: some View {
        @Bindable var bindable = app
        ZStack {
            GlowBackground()

            // Pages — kept alive, hidden with opacity so state survives tab switches.
            ZStack {
                HomeView()
                    .locusPageVisibility(active: app.tab == .home)
                AskView()
                    .locusPageVisibility(active: app.tab == .ask)
                LibraryView()
                    .locusPageVisibility(active: app.tab == .library)
                PrivateChatsView()
                    .locusPageVisibility(active: app.tab == .privateChats)
                SecretImagesView()
                    .locusPageVisibility(active: app.tab == .secret)
            }

            // The only persistent chrome: a floating glass hamburger.
            VStack {
                HStack {
                    GlassCircleButton(systemImage: "line.3.horizontal", label: "Open menu") {
                        LocusHaptics.light()
                        withAnimation(.spring(duration: 0.32)) { menuOpen = true }
                    }
                    .padding(.leading, 16)
                    Spacer()
                }
                .padding(.top, 6)
                Spacer()
            }

            SideMenu(isOpen: $menuOpen, libraryCount: libraryCount)

            if let toast = app.toast {
                VStack {
                    ToastView(toast: toast)
                        .padding(.top, 10)
                    Spacer()
                }
                .transition(.move(edge: .top).combined(with: .opacity))
                .zIndex(10)
            }
        }
        .animation(.spring(duration: 0.3), value: app.toast)
        // No shell-wide drag gesture: a parent DragGesture competes with the pages' scroll
        // views and menus, which showed up as the drawer opening on an unrelated tap.
        .task {
            libraryCount = (try? await APIClient.shared.collections())?.count
        }
        .onChange(of: menuOpen) { _, open in
            guard open else { return }
            Task { libraryCount = (try? await APIClient.shared.collections())?.count }
        }
        .sheet(isPresented: $bindable.showsSettings) {
            SettingsView()
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
    }
}

private extension View {
    func locusPageVisibility(active: Bool) -> some View {
        self
            .opacity(active ? 1 : 0)
            .allowsHitTesting(active)
            .accessibilityHidden(!active)
    }
}

struct ToastView: View {
    @Environment(\.locusPalette) private var palette
    let toast: ToastMessage

    private var tint: Color {
        switch toast.kind {
        case .info: return palette.accent
        case .success: return palette.success
        case .error: return palette.danger
        }
    }

    private var icon: String {
        switch toast.kind {
        case .info: return "info.circle.fill"
        case .success: return "checkmark.circle.fill"
        case .error: return "exclamationmark.triangle.fill"
        }
    }

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .foregroundStyle(tint)
            Text(toast.text)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(palette.heading)
                .lineLimit(2)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(palette.glassFillStrong)
        .clipShape(Capsule())
        .locusGlass(in: Capsule())
        .overlay(Capsule().strokeBorder(palette.glassEdge, lineWidth: 1))
        .shadow(color: Color.black.opacity(0.35), radius: 18, x: 0, y: 8)
        .padding(.horizontal, 24)
    }
}
