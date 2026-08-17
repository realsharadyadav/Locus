import SwiftUI

/// Pick which files an answer is grounded in: libraries → files, multi-select.
/// "Search everything" (no explicit scope) is the default and maps to `file_ids: null`;
/// an explicit empty selection is what tells the backend to go to the web at High/Max.
struct FilePickerSheet: View {
    @Environment(\.locusPalette) private var palette
    @Environment(\.dismiss) private var dismiss
    @Binding var selection: [Int]?

    @State private var stores: [CollectionRead] = []
    @State private var files: [StoredFileRead] = []
    @State private var loading = true
    @State private var draft: Set<Int> = []
    @State private var scoped = false

    private func filesIn(_ storeId: Int) -> [StoredFileRead] {
        files.filter { $0.storeId == storeId }
    }

    var body: some View {
        ZStack {
            GlowBackground()
            VStack(spacing: 0) {
                header

                if loading {
                    VStack(spacing: 12) {
                        ForEach(0..<3, id: \.self) { _ in SkeletonCard(height: 62) }
                    }
                    .padding(20)
                    Spacer()
                } else if files.isEmpty {
                    EmptyStateCard(
                        systemImage: "doc.badge.plus",
                        title: "No files yet",
                        message: "Upload documents in Library, then scope an answer to them."
                    )
                    .padding(20)
                    Spacer()
                } else {
                    List {
                        Section {
                            Toggle(isOn: $scoped) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("Limit to selected files")
                                        .font(.system(size: 14, weight: .semibold))
                                        .foregroundStyle(palette.heading)
                                    Text(scoped
                                         ? "Only the files you tick are in scope."
                                         : "Searching your whole library.")
                                        .font(.system(size: 11))
                                        .foregroundStyle(palette.muted)
                                }
                            }
                            .tint(palette.accent)
                            .listRowBackground(Color.clear)
                        }

                        ForEach(stores) { store in
                            let storeFiles = filesIn(store.id)
                            if !storeFiles.isEmpty {
                                Section {
                                    ForEach(storeFiles) { file in
                                        Button {
                                            LocusHaptics.selection()
                                            if draft.contains(file.id) { draft.remove(file.id) } else { draft.insert(file.id) }
                                            scoped = true
                                        } label: {
                                            HStack(spacing: 10) {
                                                Image(systemName: draft.contains(file.id) ? "checkmark.circle.fill" : "circle")
                                                    .foregroundStyle(draft.contains(file.id) ? palette.accent : palette.subtle)
                                                VStack(alignment: .leading, spacing: 2) {
                                                    Text(file.name)
                                                        .font(.system(size: 14, weight: .medium))
                                                        .foregroundStyle(palette.heading)
                                                        .lineLimit(1)
                                                    Text(LocusFormat.fileMetaLine(file))
                                                        .font(.system(size: 11))
                                                        .foregroundStyle(palette.muted)
                                                }
                                                Spacer()
                                            }
                                            .contentShape(Rectangle())
                                        }
                                        .buttonStyle(.plain)
                                        .listRowBackground(Color.clear)
                                    }
                                } header: {
                                    Text(store.title)
                                        .font(.system(size: 11, weight: .bold))
                                        .foregroundStyle(palette.accent)
                                }
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
                    .scrollContentBackground(.hidden)
                }

                GradientPrimaryButton(title: applyTitle, systemImage: "checkmark") {
                    LocusHaptics.light()
                    selection = scoped ? Array(draft) : nil
                    dismiss()
                }
                .padding(20)
            }
        }
        .task { await load() }
    }

    private var applyTitle: String {
        guard scoped else { return "Search everything" }
        return draft.isEmpty ? "Use no files (web only)" : "Use \(LocusFormat.plural(draft.count, "file"))"
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Add files")
                    .font(LocusFont.title())
                    .foregroundStyle(palette.heading)
                Text("Scope the answer to specific documents.")
                    .font(LocusFont.caption())
                    .foregroundStyle(palette.muted)
            }
            Spacer()
        }
        .padding(.horizontal, 20)
        .padding(.top, 18)
    }

    private func load() async {
        async let storesTask = try? await APIClient.shared.collections()
        async let filesTask = try? await APIClient.shared.files()
        let (loadedStores, loadedFiles) = await (storesTask, filesTask)
        stores = loadedStores ?? []
        files = loadedFiles ?? []
        if let selection {
            draft = Set(selection)
            scoped = true
        }
        loading = false
    }
}
