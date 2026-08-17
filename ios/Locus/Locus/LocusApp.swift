import SwiftUI

@main
struct LocusApp: App {
    @State private var app = AppState()

    var body: some Scene {
        WindowGroup {
            Group {
                switch app.auth {
                case .checking:
                    BootView()
                case .signedOut:
                    LoginView()
                case .signedIn:
                    AppShell()
                }
            }
            .environment(app)
            .environment(\.locusPalette, app.palette)
            .preferredColorScheme(app.scheme == .dark ? .dark : .light)
            .task { await app.boot() }
        }
    }
}

/// Shown while the auth gate status is being resolved.
struct BootView: View {
    @Environment(\.locusPalette) private var palette

    var body: some View {
        ZStack {
            GlowBackground()
            VStack(spacing: 18) {
                LocusLogo(size: 72)
                ProgressView()
                    .tint(palette.accent)
            }
        }
    }
}
