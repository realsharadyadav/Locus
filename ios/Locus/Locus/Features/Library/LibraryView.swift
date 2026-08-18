import SwiftUI
import PhotosUI
import UniformTypeIdentifiers

/// Library — collections and the files inside them. Same store as the web, so anything uploaded
/// here is immediately askable in Ask and visible on the web.
struct LibraryView: View {
    @Environment(AppState.self) private var app
    @Environment(\.locusPalette) private var palette
    @State private var model = LibraryModel()
    @State private var showsCreate = false
    @State private var openStore: CollectionRead?
    @State private var pendingDelete: CollectionRead?

    private let columns = [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)]

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            PageScaffold(
                kicker: "Workspace",
                title: "Library",
                subtitle: "Group your documents, then ask questions grounded in them."
            ) {
                if model.loading {
                    LazyVGrid(columns: columns, spacing: 12) {
                        ForEach(0..<4, id: \.self) { _ in SkeletonCard(height: 120) }
                    }
                } else if model.stores.isEmpty {
                    EmptyStateCard(
                        systemImage: "folder.badge.plus",
                        title: "No libraries yet",
                        message: "Create one and upload documents to ask questions about them."
                    )
                } else {
                    LazyVGrid(columns: columns, spacing: 12) {
                        ForEach(model.stores) { store in
                            StoreCard(store: store, fileCount: model.files(in: store.id).count)
                                .onTapGesture {
                                    LocusHaptics.light()
                                    openStore = store
                                }
                                .contextMenu {
                                    Button(role: .destructive) {
                                        pendingDelete = store
                                    } label: {
                                        Label("Delete library", systemImage: "trash")
                                    }
                                }
                        }
                    }
                }

                if let error = model.errorMessage {
                    Text(error)
                        .font(LocusFont.caption())
                        .foregroundStyle(palette.danger)
                }
            }
            .refreshable { await model.refresh() }

            Button {
                LocusHaptics.light()
                showsCreate = true
            } label: {
                HStack(spacing: 7) {
                    Image(systemName: "plus")
                        .font(.system(size: 14, weight: .bold))
                    Text("New library")
                        .font(.system(size: 14, weight: .semibold))
                }
                .foregroundStyle(.white)
                .padding(.horizontal, 15)
                .frame(minHeight: LocusMetrics.minimumTapTarget)
                .background(palette.accentGradient)
                .clipShape(Capsule())
                .shadow(color: palette.accent.opacity(0.4), radius: 16, y: 8)
            }
            .buttonStyle(.plain)
            .padding(.trailing, 20)
            .padding(.bottom, LocusMetrics.bottomClearance)
        }
        .task { await model.loadIfNeeded() }
        .sheet(isPresented: $showsCreate) {
            CreateLibrarySheet { title, description, color in
                await model.createStore(title: title, description: description, color: color)
            }
            .presentationDetents([.medium])
            .presentationDragIndicator(.visible)
        }
        .sheet(item: $openStore) { store in
            LibraryDetailView(store: store, model: model)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .confirmationDialog(
            "Delete this library?",
            isPresented: Binding(get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } }),
            titleVisibility: .visible
        ) {
            Button("Delete library", role: .destructive) {
                if let store = pendingDelete {
                    Task { await model.deleteStore(store) }
                }
                pendingDelete = nil
            }
            Button("Cancel", role: .cancel) { pendingDelete = nil }
        } message: {
            Text("Its files are removed and can no longer be used for answers.")
        }
    }
}

private struct StoreCard: View {
    @Environment(\.locusPalette) private var palette
    let store: CollectionRead
    let fileCount: Int

    private var color: LibraryColor { LibraryColor.named(store.color) }

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 9) {
                Image(systemName: "folder.fill")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(color.tint(palette))
                    .frame(width: 40, height: 40)
                    .background(color.fill(palette))
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                Text(store.title)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(palette.heading)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                Text(LocusFormat.plural(fileCount, "file"))
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(palette.muted)
            }
            .frame(maxWidth: .infinity, minHeight: 118, alignment: .topLeading)
        }
    }
}

// MARK: - Create

private struct CreateLibrarySheet: View {
    @Environment(\.locusPalette) private var palette
    @Environment(\.dismiss) private var dismiss
    let onCreate: (String, String, LibraryColor) async -> Void

    @State private var title = ""
    @State private var description = ""
    @State private var color: LibraryColor = .violet
    @State private var busy = false

    var body: some View {
        ZStack {
            GlowBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("New library")
                        .font(LocusFont.title())
                        .foregroundStyle(palette.heading)
                        .padding(.top, 18)

                    GlassCard {
                        VStack(alignment: .leading, spacing: 12) {
                            field("Name", placeholder: "Product thinking", text: $title)
                            field("Description", placeholder: "What goes in here?", text: $description)
                            VStack(alignment: .leading, spacing: 7) {
                                Text("Colour")
                                    .font(.system(size: 12, weight: .semibold))
                                    .foregroundStyle(palette.muted)
                                HStack(spacing: 10) {
                                    ForEach(LibraryColor.allCases) { option in
                                        Button {
                                            LocusHaptics.selection()
                                            color = option
                                        } label: {
                                            Image(systemName: "folder.fill")
                                                .font(.system(size: 15, weight: .semibold))
                                                .foregroundStyle(option.tint(palette))
                                                .frame(width: 42, height: 42)
                                                .background(option.fill(palette))
                                                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                                                .overlay(
                                                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                                                        .strokeBorder(color == option ? palette.accent : .clear, lineWidth: 2)
                                                )
                                        }
                                        .buttonStyle(.plain)
                                    }
                                }
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    GradientPrimaryButton(
                        title: busy ? "Creating…" : "Create library",
                        systemImage: "plus",
                        disabled: busy || title.trimmingCharacters(in: .whitespaces).isEmpty
                    ) {
                        busy = true
                        Task {
                            await onCreate(title, description, color)
                            dismiss()
                        }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 30)
            }
            .scrollIndicators(.hidden)
        }
    }

    private func field(_ label: String, placeholder: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(palette.muted)
            TextField(placeholder, text: text)
                .font(.system(size: 15))
                .foregroundStyle(palette.heading)
                .tint(palette.accent)
                .padding(11)
                .background(palette.glassFillSoft)
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
    }
}

// MARK: - Detail

private struct LibraryDetailView: View {
    @Environment(\.locusPalette) private var palette
    let store: CollectionRead
    let model: LibraryModel

    @State private var picked: [PhotosPickerItem] = []
    @State private var showsPhotoPicker = false
    @State private var showsFileImporter = false
    @State private var pendingDelete: StoredFileRead?

    private var files: [StoredFileRead] { model.files(in: store.id) }

    var body: some View {
        ZStack(alignment: .bottom) {
            GlowBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(store.title)
                            .font(LocusFont.title())
                            .foregroundStyle(palette.heading)
                        if !store.description.isEmpty {
                            Text(store.description)
                                .font(LocusFont.body())
                                .foregroundStyle(palette.muted)
                        }
                    }
                    .padding(.top, 18)

                    // Without this the sheet swallows failures: an upload that never reached
                    // the server just closed the picker and showed nothing.
                    if let error = model.errorMessage {
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .font(.system(size: 12))
                                .foregroundStyle(palette.danger)
                            Text(error)
                                .font(.system(size: 12))
                                .foregroundStyle(palette.danger)
                                .fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 0)
                            Button("Dismiss") { model.errorMessage = nil }
                                .font(.system(size: 11, weight: .semibold))
                                .foregroundStyle(palette.muted)
                                .buttonStyle(.plain)
                        }
                        .padding(11)
                        .background(palette.danger.opacity(0.12))
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    }

                    if files.isEmpty {
                        EmptyStateCard(
                            systemImage: "doc.badge.plus",
                            title: "No files yet",
                            message: "Add a document — it becomes searchable once indexing finishes."
                        )
                    } else {
                        ForEach(files) { file in
                            FileRow(file: file)
                                .contextMenu {
                                    Button(role: .destructive) {
                                        pendingDelete = file
                                    } label: {
                                        Label("Delete file", systemImage: "trash")
                                    }
                                }
                        }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 110)
            }
            .scrollIndicators(.hidden)

            Menu {
                Button {
                    showsFileImporter = true
                } label: {
                    Label("From Files", systemImage: "folder")
                }
                Button {
                    showsPhotoPicker = true
                } label: {
                    Label("From Photos", systemImage: "photo.on.rectangle")
                }
            } label: {
                HStack(spacing: 7) {
                    if model.uploading {
                        ProgressView().tint(.white)
                    } else {
                        Image(systemName: "arrow.up.doc.fill")
                            .font(.system(size: 14, weight: .bold))
                    }
                    Text(model.uploading ? "Uploading…" : "Add files")
                        .font(.system(size: 15, weight: .bold))
                }
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(palette.accentGradient)
                .clipShape(RoundedRectangle(cornerRadius: LocusMetrics.buttonRadius, style: .continuous))
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 20)
        }
        .photosPicker(isPresented: $showsPhotoPicker, selection: $picked, maxSelectionCount: 5, matching: .images)
        .onChange(of: picked) { _, items in
            guard !items.isEmpty else { return }
            Task {
                for item in items {
                    if let data = try? await item.loadTransferable(type: Data.self) {
                        await model.upload(
                            data: data,
                            fileName: "photo-\(Int(Date().timeIntervalSince1970)).jpg",
                            contentType: "image/jpeg",
                            storeId: store.id
                        )
                    }
                }
                picked = []
            }
        }
        .fileImporter(
            isPresented: $showsFileImporter,
            allowedContentTypes: [.pdf, .plainText, .rtf, .data],
            allowsMultipleSelection: true
        ) { result in
            guard case .success(let urls) = result else { return }
            Task {
                for url in urls {
                    guard url.startAccessingSecurityScopedResource() else { continue }
                    defer { url.stopAccessingSecurityScopedResource() }
                    guard let data = try? Data(contentsOf: url) else { continue }
                    let type = UTType(filenameExtension: url.pathExtension)?.preferredMIMEType
                        ?? "application/octet-stream"
                    await model.upload(
                        data: data,
                        fileName: url.lastPathComponent,
                        contentType: type,
                        storeId: store.id
                    )
                }
            }
        }
        .confirmationDialog(
            "Delete this file?",
            isPresented: Binding(get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } }),
            titleVisibility: .visible
        ) {
            Button("Delete", role: .destructive) {
                if let file = pendingDelete {
                    Task { await model.deleteFile(file) }
                }
                pendingDelete = nil
            }
            Button("Cancel", role: .cancel) { pendingDelete = nil }
        }
    }
}

private struct FileRow: View {
    @Environment(\.locusPalette) private var palette
    let file: StoredFileRead

    private var indexing: IndexingState { IndexingState(file: file) }

    private var icon: String {
        if file.contentType.hasPrefix("image/") { return "photo" }
        if file.contentType.contains("pdf") { return "doc.richtext" }
        if file.contentType.contains("csv") || file.contentType.contains("sheet") { return "tablecells" }
        return "doc.text"
    }

    var body: some View {
        GlassCard(padding: 13) {
            HStack(spacing: 11) {
                Image(systemName: icon)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(palette.accent)
                    .frame(width: 34, height: 34)
                    .background(palette.accentSoft)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))

                VStack(alignment: .leading, spacing: 3) {
                    Text(file.name)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(palette.heading)
                        .lineLimit(1)
                    HStack(spacing: 5) {
                        Text(LocusFormat.fileSize(file.size))
                        Text("·")
                        if indexing.isWorking {
                            ProgressView().scaleEffect(0.5).frame(width: 10, height: 10)
                        }
                        Text(indexing.label)
                            .foregroundStyle(indexing.isFailure ? palette.danger : palette.muted)
                    }
                    .font(.system(size: 11))
                    .foregroundStyle(palette.muted)
                }
                Spacer(minLength: 0)
                Text(LocusFormat.displayTime(file.createdAt))
                    .font(.system(size: 10))
                    .foregroundStyle(palette.subtle)
            }
        }
    }
}
