import SwiftUI

/// The three library colours the web offers (`STORE_COLORS`), with their swatches.
enum LibraryColor: String, CaseIterable, Identifiable {
    case violet, peach, green

    var id: String { rawValue }

    func tint(_ palette: LocusPalette) -> Color {
        switch self {
        case .violet: return palette.accent
        case .peach: return Color(red: 158 / 255, green: 98 / 255, blue: 77 / 255)   // #9e624d
        case .green: return Color(red: 88 / 255, green: 116 / 255, blue: 82 / 255)   // #587452
        }
    }

    func fill(_ palette: LocusPalette) -> Color {
        switch self {
        case .violet: return palette.accentSoft
        case .peach: return Color(red: 238 / 255, green: 219 / 255, blue: 209 / 255) // #eedbd1
        case .green: return Color(red: 217 / 255, green: 226 / 255, blue: 212 / 255) // #d9e2d4
        }
    }

    static func named(_ value: String) -> LibraryColor {
        LibraryColor(rawValue: value) ?? .violet
    }
}

/// Indexing state of a file, ported from the web's `embeddingMeta`.
struct IndexingState {
    let label: String
    let detail: String
    let isFailure: Bool
    let isWorking: Bool

    init(file: StoredFileRead) {
        let status = file.embeddingStatus.isEmpty ? "pending" : file.embeddingStatus
        switch status {
        case "embedded": label = "\(file.embeddingChunks) chunks indexed"
        case "indexing": label = "Embedding now"
        case "pending": label = "Waiting to index"
        case "empty": label = "No searchable text"
        case "failed": label = "Index failed"
        default: label = "Index pending"
        }
        detail = status == "embedded"
            ? "\(file.embeddingBackend) · \(file.embeddingModel)"
            : (file.embeddingError.isEmpty ? file.embeddingModel : file.embeddingError)
        isFailure = status == "failed"
        isWorking = status == "indexing" || status == "pending"
    }
}

@MainActor
@Observable
final class LibraryModel {
    var stores: [CollectionRead] = []
    var files: [StoredFileRead] = []
    var loading = true
    var uploading = false
    var errorMessage: String?

    private var hasLoadedOnce = false
    private var indexingPoll: Task<Void, Never>?

    func loadIfNeeded() async {
        guard !hasLoadedOnce else { return }
        hasLoadedOnce = true
        await refresh()
    }

    func refresh() async {
        async let storesTask = try? await APIClient.shared.collections()
        async let filesTask = try? await APIClient.shared.files()
        let (loadedStores, loadedFiles) = await (storesTask, filesTask)
        stores = loadedStores ?? []
        files = loadedFiles ?? []
        loading = false
        scheduleIndexingPollIfNeeded()
    }

    func files(in storeId: Int) -> [StoredFileRead] {
        files.filter { $0.storeId == storeId }.sorted { $0.createdAt > $1.createdAt }
    }

    /// Embedding runs in the background, so a freshly uploaded file keeps reporting
    /// "Waiting to index" until it is re-read — poll only while something is still working.
    private func scheduleIndexingPollIfNeeded() {
        let working = files.contains { IndexingState(file: $0).isWorking }
        guard working else {
            indexingPoll?.cancel()
            indexingPoll = nil
            return
        }
        guard indexingPoll == nil else { return }
        indexingPoll = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(3))
                guard let self, !Task.isCancelled else { return }
                self.files = (try? await APIClient.shared.files()) ?? self.files
                if !self.files.contains(where: { IndexingState(file: $0).isWorking }) {
                    self.indexingPoll = nil
                    return
                }
            }
        }
    }

    func createStore(title: String, description: String, color: LibraryColor) async {
        do {
            let created = try await APIClient.shared.createCollection(
                title: title.trimmingCharacters(in: .whitespacesAndNewlines),
                description: description,
                color: color.rawValue
            )
            stores.insert(created, at: 0)
            LocusHaptics.success()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func deleteStore(_ store: CollectionRead) async {
        do {
            try await APIClient.shared.deleteCollection(store.id)
            stores.removeAll { $0.id == store.id }
            files.removeAll { $0.storeId == store.id }
            LocusHaptics.warning()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func upload(data: Data, fileName: String, contentType: String, storeId: Int) async {
        uploading = true
        do {
            let created = try await APIClient.shared.uploadFile(
                storeId: storeId, fileName: fileName, contentType: contentType, data: data
            )
            files.insert(created, at: 0)
            await refresh() // picks up the store's new file count
            LocusHaptics.success()
        } catch {
            errorMessage = error.localizedDescription
            LocusHaptics.warning()
        }
        uploading = false
    }

    func deleteFile(_ file: StoredFileRead) async {
        do {
            try await APIClient.shared.deleteFile(file.id)
            files.removeAll { $0.id == file.id }
            await refresh()
            LocusHaptics.warning()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
