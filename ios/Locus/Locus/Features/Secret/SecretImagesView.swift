import SwiftUI
import PhotosUI

/// Secret Images — a private photo vault. Same store as the web (`/api/secret-images`), so a
/// photo added here shows up there and vice versa.
struct SecretImagesView: View {
    @Environment(\.locusPalette) private var palette
    @State private var model = SecretImagesModel()
    @State private var picked: [PhotosPickerItem] = []
    @State private var showsPhotoPicker = false
    @State private var showsFileImporter = false
    @State private var viewing: SecretImageRead?
    @State private var pendingDelete: SecretImageRead?

    private let columns = [
        GridItem(.flexible(), spacing: 10),
        GridItem(.flexible(), spacing: 10),
        GridItem(.flexible(), spacing: 10),
    ]

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            PageScaffold(
                kicker: "Signals",
                title: "Secret images",
                subtitle: model.configured
                    ? "Private to you. Nothing here is used for answers."
                    : "Image storage isn't configured on this server."
            ) {
                if model.loading {
                    LazyVGrid(columns: columns, spacing: 10) {
                        ForEach(0..<6, id: \.self) { _ in SkeletonCard(height: 108, cornerRadius: 14) }
                    }
                } else if !model.configured {
                    EmptyStateCard(
                        systemImage: "externaldrive.badge.xmark",
                        title: "Storage not configured",
                        message: "Set the image storage variables on the server, then reload."
                    )
                } else if let error = model.errorMessage, model.images.isEmpty {
                    EmptyStateCard(
                        systemImage: "exclamationmark.triangle",
                        title: "Couldn't load the vault",
                        message: error
                    )
                } else if model.images.isEmpty {
                    EmptyStateCard(
                        systemImage: "lock.rectangle.on.rectangle",
                        title: "Nothing here yet",
                        message: "Add a photo — it stays private to you."
                    )
                } else {
                    LazyVGrid(columns: columns, spacing: 10) {
                        ForEach(model.images) { image in
                            Tile(image: image, decoded: model.loaded[image.id])
                                .onTapGesture {
                                    LocusHaptics.light()
                                    viewing = image
                                }
                                .contextMenu {
                                    Button(role: .destructive) {
                                        pendingDelete = image
                                    } label: {
                                        Label("Delete", systemImage: "trash")
                                    }
                                }
                                .task { await model.load(image) }
                        }
                    }
                }
            }
            .refreshable { await model.refresh() }

            if model.configured {
                addButton
            }
        }
        .task { await model.loadIfNeeded() }
        // Presented from the menu's button rather than embedding a PhotosPicker inside the
        // Menu, which never opens — menu rows have to be plain buttons.
        .photosPicker(isPresented: $showsPhotoPicker, selection: $picked,
                      maxSelectionCount: 10, matching: .images)
        .onChange(of: picked) { _, items in
            guard !items.isEmpty else { return }
            Task {
                for item in items {
                    if let data = try? await item.loadTransferable(type: Data.self) {
                        await model.upload(
                            data: data,
                            fileName: "photo-\(Int(Date().timeIntervalSince1970)).jpg",
                            contentType: "image/jpeg"
                        )
                    }
                }
                picked = []
            }
        }
        .fileImporter(isPresented: $showsFileImporter, allowedContentTypes: [.image], allowsMultipleSelection: true) { result in
            guard case .success(let urls) = result else { return }
            Task {
                for url in urls {
                    guard url.startAccessingSecurityScopedResource() else { continue }
                    defer { url.stopAccessingSecurityScopedResource() }
                    if let data = try? Data(contentsOf: url) {
                        await model.upload(
                            data: data,
                            fileName: url.lastPathComponent,
                            contentType: "image/" + (url.pathExtension.isEmpty ? "jpeg" : url.pathExtension)
                        )
                    }
                }
            }
        }
        .fullScreenCover(item: $viewing) { image in
            ImageViewer(image: image, decoded: model.loaded[image.id]) {
                pendingDelete = image
                viewing = nil
            }
        }
        .confirmationDialog(
            "Delete this image?",
            isPresented: Binding(get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } }),
            titleVisibility: .visible
        ) {
            Button("Delete", role: .destructive) {
                if let image = pendingDelete {
                    Task { await model.delete(image) }
                }
                pendingDelete = nil
            }
            Button("Cancel", role: .cancel) { pendingDelete = nil }
        } message: {
            Text("It is removed from the vault for good.")
        }
    }

    private var addButton: some View {
        Menu {
            Button {
                showsPhotoPicker = true
            } label: {
                Label("From Photos", systemImage: "photo.on.rectangle")
            }
            Button {
                showsFileImporter = true
            } label: {
                Label("From Files", systemImage: "folder")
            }
        } label: {
            HStack(spacing: 7) {
                if model.uploading {
                    ProgressView().tint(.white)
                } else {
                    Image(systemName: "plus")
                        .font(.system(size: 14, weight: .bold))
                }
                Text(model.uploading ? "Adding…" : "Add photo")
                    .font(.system(size: 15, weight: .bold))
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 18)
            .padding(.vertical, 13)
            .background(palette.accentGradient)
            .clipShape(Capsule())
            .shadow(color: palette.accent.opacity(0.4), radius: 16, y: 8)
        }
        .padding(.trailing, 20)
        .padding(.bottom, LocusMetrics.bottomClearance)
    }
}

private struct Tile: View {
    @Environment(\.locusPalette) private var palette
    let image: SecretImageRead
    let decoded: UIImage?

    var body: some View {
        ZStack {
            if let decoded {
                Image(uiImage: decoded)
                    .resizable()
                    .scaledToFill()
            } else {
                palette.glassFillSoft
                ProgressView().tint(palette.accent)
            }
        }
        .frame(height: 108)
        .clipped()
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(palette.glassEdgeSoft, lineWidth: 1)
        )
    }
}

/// Full-screen viewer: pinch to zoom, drag to pan when zoomed, swipe down to dismiss.
private struct ImageViewer: View {
    @Environment(\.locusPalette) private var palette
    @Environment(\.dismiss) private var dismiss
    let image: SecretImageRead
    let decoded: UIImage?
    let onDelete: () -> Void

    @State private var scale: CGFloat = 1
    @State private var lastScale: CGFloat = 1
    @State private var offset: CGSize = .zero
    @State private var lastOffset: CGSize = .zero

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            if let decoded {
                Image(uiImage: decoded)
                    .resizable()
                    .scaledToFit()
                    .scaleEffect(scale)
                    .offset(offset)
                    .gesture(
                        MagnifyGesture()
                            .onChanged { value in scale = max(1, lastScale * value.magnification) }
                            .onEnded { _ in
                                lastScale = scale
                                if scale <= 1 { withAnimation(.spring) { reset() } }
                            }
                    )
                    .simultaneousGesture(
                        DragGesture()
                            .onChanged { value in
                                if scale > 1 {
                                    offset = CGSize(
                                        width: lastOffset.width + value.translation.width,
                                        height: lastOffset.height + value.translation.height
                                    )
                                } else {
                                    // Not zoomed: a downward drag is the dismiss gesture.
                                    offset = CGSize(width: 0, height: max(0, value.translation.height))
                                }
                            }
                            .onEnded { value in
                                if scale > 1 {
                                    lastOffset = offset
                                } else if value.translation.height > 120 {
                                    dismiss()
                                } else {
                                    withAnimation(.spring) { reset() }
                                }
                            }
                    )
                    .onTapGesture(count: 2) {
                        withAnimation(.spring) {
                            if scale > 1 { reset() } else { scale = 2.5; lastScale = 2.5 }
                        }
                    }
            } else {
                ProgressView().tint(.white)
            }

            VStack {
                HStack {
                    Button {
                        LocusHaptics.light()
                        dismiss()
                    } label: {
                        circleIcon("xmark")
                    }
                    Spacer()
                    Button {
                        LocusHaptics.light()
                        onDelete()
                    } label: {
                        circleIcon("trash", tint: palette.danger)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 12)
                Spacer()
                Text("\(image.originalFilename) · \(LocusFormat.fileSize(image.sizeBytes))")
                    .font(.system(size: 11))
                    .foregroundStyle(.white.opacity(0.7))
                    .padding(.bottom, 20)
            }
        }
        .statusBarHidden()
    }

    private func circleIcon(_ systemImage: String, tint: Color = .white) -> some View {
        Image(systemName: systemImage)
            .font(.system(size: 15, weight: .bold))
            .foregroundStyle(tint)
            .frame(width: 40, height: 40)
            .background(.ultraThinMaterial, in: Circle())
    }

    private func reset() {
        scale = 1
        lastScale = 1
        offset = .zero
        lastOffset = .zero
    }
}
