import SwiftUI

/// Calm sign-in gate — mirrors the web login (one shared password, no accounts).
struct LoginView: View {
    @Environment(AppState.self) private var app
    @Environment(\.locusPalette) private var palette

    @State private var password = ""
    @State private var errorMessage: String?
    @State private var busy = false

    var body: some View {
        ZStack {
            GlowBackground()
            VStack(spacing: 0) {
                Spacer()
                VStack(spacing: 18) {
                    LocusLogo(size: 64)

                    VStack(spacing: 6) {
                        Text("Welcome to Locus")
                            .font(.system(size: 26, weight: .bold))
                            .foregroundStyle(palette.heading)
                        Text("Enter the workspace password to continue.")
                            .font(.system(size: 14))
                            .foregroundStyle(palette.muted)
                            .multilineTextAlignment(.center)
                    }

                    GlassCard(padding: 18) {
                        VStack(spacing: 14) {
                            SecureField("Password", text: $password)
                                .textContentType(.password)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .font(.system(size: 16))
                                .foregroundStyle(palette.heading)
                                .padding(.horizontal, 14)
                                .padding(.vertical, 12)
                                .background(palette.glassFillSoft)
                                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                                        .strokeBorder(palette.glassEdge, lineWidth: 1)
                                )
                                .onSubmit(signIn)

                            if let errorMessage {
                                Text(errorMessage)
                                    .font(.system(size: 13, weight: .semibold))
                                    .foregroundStyle(palette.danger)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }

                            GradientPrimaryButton(title: busy ? "Signing in…" : "Sign in",
                                                  systemImage: "lock.open.fill",
                                                  disabled: busy || password.isEmpty) {
                                signIn()
                            }
                        }
                    }
                    .frame(maxWidth: 380)
                }
                .padding(.horizontal, 24)
                Spacer()
                Spacer()
            }
        }
    }

    private func signIn() {
        guard !password.isEmpty, !busy else { return }
        busy = true
        errorMessage = nil
        Task {
            do {
                try await app.signIn(password: password)
            } catch let apiError as APIError {
                errorMessage = apiError.message
                LocusHaptics.warning()
            } catch {
                errorMessage = "Sign in failed"
                LocusHaptics.warning()
            }
            busy = false
        }
    }
}
