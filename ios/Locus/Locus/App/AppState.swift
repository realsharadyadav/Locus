import SwiftUI

enum AppTab: Int, CaseIterable, Identifiable {
    case ask, library, privateChats, secret

    var id: Int { rawValue }

    var title: String {
        switch self {
        case .ask: return "Ask"
        case .library: return "Library"
        case .privateChats: return "Private"
        case .secret: return "Secret"
        }
    }

    var systemImage: String {
        switch self {
        case .ask: return "bubble.left.and.bubble.right.fill"
        case .library: return "books.vertical.fill"
        case .privateChats: return "touchid"
        case .secret: return "lock.fill"
        }
    }
}

struct ToastMessage: Equatable, Sendable {
    enum Kind: Sendable { case info, success, error }
    let kind: Kind
    let text: String
}

@MainActor
@Observable
final class AppState {
    enum AuthState {
        case checking
        case signedOut
        case signedIn
    }

    var auth: AuthState = .checking
    var tab: AppTab = .ask
    var showsSettings = false
    var scheme: LocusScheme = .dark
    var toast: ToastMessage?
    var serverOnline: Bool?


    /// Live default model label, refreshed after boot and whenever Settings changes it.
    var defaultModelLabel: String = ""

    private var toastTask: Task<Void, Never>?

    var palette: LocusPalette { LocusPalette(scheme: scheme) }

    init() {
        if let stored = UserDefaults.standard.string(forKey: "locus.theme"),
           let saved = LocusScheme(rawValue: stored) {
            scheme = saved
        }
        Task { [weak self] in
            await APIClient.shared.setUnauthorizedHandler {
                Task { @MainActor in self?.handleUnauthorized() }
            }
        }
    }

    // MARK: - Boot

    func boot() async {
        auth = .checking
        do {
            let status = try await APIClient.shared.authStatus()
            if !status.authRequired {
                auth = .signedIn
            } else if APIClient.shared.token != nil {
                // Token exists — trust it until a 401 says otherwise (offline-friendly).
                auth = .signedIn
            } else {
                auth = .signedOut
            }
        } catch {
            // Server unreachable: let a signed-in-before user in; gate the rest.
            auth = APIClient.shared.token != nil ? .signedIn : .signedOut
        }
        // Protected endpoints only once the gate has been resolved — asking earlier makes
        // every cold start fire a 401 while signed out.
        if auth == .signedIn { await refreshDefaultModel() }
        await ping()
    }

    func ping() async {
        serverOnline = (try? await APIClient.shared.health()) ?? false
    }

    func refreshDefaultModel() async {
        if let preference = try? await APIClient.shared.preference("explore_ai"),
           let model = preference.value["model"]?.string, !model.isEmpty {
            defaultModelLabel = model
        }
    }

    // MARK: - Auth

    func signIn(password: String) async throws {
        let response = try await APIClient.shared.login(password: password)
        APIClient.shared.saveToken(response.token)
        auth = .signedIn
        LocusHaptics.success()
        await refreshDefaultModel()
    }

    func signOut() {
        APIClient.shared.clearToken()
        auth = .signedOut
    }

    private func handleUnauthorized() {
        guard auth == .signedIn else { return }
        signOut()
        showToast(kind: .info, text: "Session expired — sign in again")
    }

    // MARK: - Theme

    func setScheme(_ newScheme: LocusScheme) {
        scheme = newScheme
        UserDefaults.standard.set(newScheme.rawValue, forKey: "locus.theme")
    }

    // MARK: - Toasts

    func showToast(kind: ToastMessage.Kind, text: String) {
        toastTask?.cancel()
        toast = ToastMessage(kind: kind, text: text)
        toastTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(3))
            guard !Task.isCancelled else { return }
            self?.toast = nil
        }
    }
}
