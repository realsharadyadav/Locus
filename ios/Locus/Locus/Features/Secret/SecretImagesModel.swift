import SwiftUI

@MainActor
@Observable
final class SecretImagesModel {
    var images: [SecretImageRead] = []
    var configured = true
    var loading = true
    var uploading = false
    var errorMessage: String?

    /// Decoded thumbnails, keyed by image id. The bytes are fetched once and reused for both
    /// the grid tile and the full-screen viewer.
    var loaded: [Int: UIImage] = [:]

    private var hasLoadedOnce = false
    private var inFlight: Set<Int> = []

    func loadIfNeeded() async {
        guard !hasLoadedOnce else { return }
        hasLoadedOnce = true
        await refresh()
    }

    func refresh() async {
        do {
            configured = (try await APIClient.shared.secretImagesStatus()).configured
            if configured {
                images = try await APIClient.shared.secretImages()
                errorMessage = nil
            }
        } catch {
            errorMessage = error.localizedDescription
        }
        loading = false
    }

    /// The view endpoint sits behind the Sign-in Gate and returns a *relative* path, so the
    /// bytes have to be fetched through the authenticated client rather than handed to an
    /// image view as a URL — the same reason the web fetches blobs instead of using `<img src>`.
    func load(_ image: SecretImageRead) async {
        guard loaded[image.id] == nil, !inFlight.contains(image.id) else { return }
        inFlight.insert(image.id)
        defer { inFlight.remove(image.id) }
        guard let (data, _) = try? await APIClient.shared.authenticatedData(
            path: "/secret-images/view/\(image.id)"
        ), let decoded = UIImage(data: data) else { return }
        loaded[image.id] = decoded
    }

    func upload(data: Data, fileName: String, contentType: String) async {
        uploading = true
        do {
            let created = try await APIClient.shared.secretImageUpload(
                fileName: fileName, contentType: contentType, data: data
            )
            images.insert(created, at: 0)
            LocusHaptics.success()
        } catch {
            errorMessage = error.localizedDescription
            LocusHaptics.warning()
        }
        uploading = false
    }

    func delete(_ image: SecretImageRead) async {
        do {
            try await APIClient.shared.secretImageDelete(image.id)
            images.removeAll { $0.id == image.id }
            loaded[image.id] = nil
            LocusHaptics.warning()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
