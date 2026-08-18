import SwiftUI

/// Left slide-in navigation, replacing the bottom dock so pages get the full screen.
/// Mirrors the web sidebar: Workspace, Signals, then theme and Settings at the foot.
struct SideMenu: View {
    @Environment(AppState.self) private var app
    @Environment(\.locusPalette) private var palette
    @Binding var isOpen: Bool
    /// Live library count, shown as a badge like the web sidebar.
    var libraryCount: Int?

    private let width: CGFloat = 252
    @State private var drag: CGFloat = 0

    var body: some View {
        ZStack(alignment: .leading) {
            if isOpen {
                Color.black.opacity(0.45)
                    .ignoresSafeArea()
                    .transition(.opacity)
                    .onTapGesture { close() }
            }

            if isOpen {
                panel
                    .frame(width: width)
                    .frame(maxHeight: .infinity)
                    .background(palette.glassFillStrong)
                    .background(palette.canvasMid)
                    .overlay(alignment: .trailing) {
                        Rectangle().fill(palette.glassEdgeSoft).frame(width: 1)
                    }
                    .ignoresSafeArea(edges: .vertical)
                    .offset(x: min(0, drag))
                    .gesture(
                        DragGesture()
                            .onChanged { value in drag = min(0, value.translation.width) }
                            .onEnded { value in
                                if value.translation.width < -60 { close() }
                                drag = 0
                            }
                    )
                    .transition(.move(edge: .leading))
            }
        }
        .animation(.spring(duration: 0.32), value: isOpen)
    }

    private var panel: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                LocusLogo(size: 30)
                Text("Locus")
                    .font(.system(size: 21, weight: .bold))
                    .foregroundStyle(palette.heading)
                Spacer()
                Button { close() } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(palette.muted)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 20)
            .padding(.top, 64)
            .padding(.bottom, 10)

            sectionLabel("Workspace")
            row(.home, "square.grid.2x2.fill")
            row(.library, "books.vertical.fill", badge: libraryCount)
            row(.ask, "bubble.left.and.bubble.right.fill")

            sectionLabel("Signals")
            row(.privateChats, "touchid")
            row(.secret, "lock.fill", title: "Secret Images")

            Spacer(minLength: 20)

            Rectangle()
                .fill(palette.glassEdgeSoft)
                .frame(height: 1)
                .padding(.horizontal, 20)
                .padding(.bottom, 14)

            HStack(spacing: 8) {
                ForEach(LocusScheme.allCases, id: \.self) { scheme in
                    Button {
                        LocusHaptics.selection()
                        app.setScheme(scheme)
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: scheme.systemImage)
                                .font(.system(size: 12, weight: .semibold))
                            Text(scheme.title)
                                .font(.system(size: 13, weight: .semibold))
                        }
                        .foregroundStyle(app.scheme == scheme ? palette.heading : palette.muted)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                        .background(app.scheme == scheme ? palette.accentSoft : Color.clear)
                        .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(4)
            .background(palette.glassFillSoft)
            .clipShape(Capsule())
            .padding(.horizontal, 16)

            Button {
                LocusHaptics.light()
                close()
                app.showsSettings = true
            } label: {
                HStack(spacing: 12) {
                    iconTile("slider.horizontal.3", active: false)
                    Text("Settings")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(palette.text)
                    Spacer()
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 6)
                .frame(minHeight: LocusMetrics.minimumTapTarget)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .padding(.bottom, 18)
        }
    }

    private func sectionLabel(_ text: String) -> some View {
        Text(text.uppercased())
            .font(.system(size: 11, weight: .bold))
            .tracking(1.4)
            .foregroundStyle(palette.subtle)
            .padding(.horizontal, 18)
            .padding(.top, 10)
            .padding(.bottom, 4)
    }

    private func row(_ tab: AppTab, _ systemImage: String, title: String? = nil, badge: Int? = nil) -> some View {
        let active = app.tab == tab
        return Button {
            LocusHaptics.light()
            app.tab = tab
            close()
        } label: {
            HStack(spacing: 12) {
                iconTile(systemImage, active: active)
                Text(title ?? tab.title)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(active ? palette.heading : palette.text)
                Spacer()
                if let badge {
                    Text("\(badge)")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(palette.muted)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(palette.glassFillSoft)
                        .clipShape(Capsule())
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .frame(minHeight: LocusMetrics.minimumTapTarget)
            .background(active ? palette.accentSoft : Color.clear)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .padding(.horizontal, 6)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func iconTile(_ systemImage: String, active: Bool) -> some View {
        Image(systemName: systemImage)
            .font(.system(size: 14, weight: .medium))
            .symbolRenderingMode(.monochrome)
            .frame(width: 17, height: 17)
            .foregroundStyle(active ? .white : palette.muted)
            .frame(width: 32, height: 32)
            .background(active ? AnyShapeStyle(palette.accentGradient) : AnyShapeStyle(palette.glassFillSoft))
            .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
    }

    private func close() {
        withAnimation(.spring(duration: 0.32)) { isOpen = false }
    }
}
