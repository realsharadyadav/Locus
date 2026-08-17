import SwiftUI

/// Locus color scheme. The web app ships "Bright" and "Dark"; dark is the default here,
/// matching the developer-focused purple-accented look.
enum LocusScheme: String, CaseIterable {
    case dark
    case bright

    var title: String { self == .dark ? "Dark" : "Bright" }
    var systemImage: String { self == .dark ? "moon.fill" : "sun.max.fill" }
}

/// Every color token, ported 1:1 from the web stylesheets
/// (`src/styles/34-glass.css`, `00-base.css`, `13-theme-dark.css`).
struct LocusPalette {
    let scheme: LocusScheme

    // Canvas gradient (top → mid → bottom)
    let canvasTop: Color
    let canvasMid: Color
    let canvasBottom: Color

    // Radial glows floating above the canvas
    let glowViolet: Color
    let glowBlue: Color
    let glowDeep: Color
    let glowSoft: Color

    // Text
    let text: Color
    let heading: Color
    let muted: Color
    let subtle: Color

    // Glass surfaces
    let glassFill: Color
    let glassFillStrong: Color
    let glassFillSoft: Color
    let glassEdge: Color
    let glassEdgeSoft: Color

    // Accents
    let accent: Color
    let accentGradientTop: Color
    let accentGradientBottom: Color
    let accentSoft: Color
    let success: Color
    let successBright: Color
    let danger: Color

    init(scheme: LocusScheme) {
        self.scheme = scheme
        switch scheme {
        case .dark:
            canvasTop = Color(red: 5 / 255, green: 7 / 255, blue: 12 / 255)       // #05070C
            canvasMid = Color(red: 10 / 255, green: 13 / 255, blue: 20 / 255)     // #0A0D14
            canvasBottom = Color(red: 7 / 255, green: 9 / 255, blue: 16 / 255)    // #070910
            glowViolet = Color(red: 139 / 255, green: 92 / 255, blue: 246 / 255).opacity(0.28)
            glowBlue = Color(red: 88 / 255, green: 166 / 255, blue: 255 / 255).opacity(0.12)
            glowDeep = Color(red: 124 / 255, green: 58 / 255, blue: 237 / 255).opacity(0.16)
            glowSoft = Color(red: 167 / 255, green: 139 / 255, blue: 250 / 255).opacity(0.08)
            text = Color(red: 201 / 255, green: 209 / 255, blue: 217 / 255)       // #C9D1D9
            heading = Color(red: 220 / 255, green: 228 / 255, blue: 238 / 255)    // #DCE4EE
            muted = Color(red: 139 / 255, green: 148 / 255, blue: 158 / 255)      // #8B949E
            subtle = Color(red: 110 / 255, green: 118 / 255, blue: 129 / 255)     // #6E7681
            glassFill = Color(red: 22 / 255, green: 27 / 255, blue: 34 / 255).opacity(0.48)
            glassFillStrong = Color(red: 22 / 255, green: 27 / 255, blue: 34 / 255).opacity(0.72)
            glassFillSoft = Color(red: 13 / 255, green: 17 / 255, blue: 23 / 255).opacity(0.36)
            glassEdge = Color.white.opacity(0.14)
            glassEdgeSoft = Color.white.opacity(0.08)
            accent = Color(red: 116 / 255, green: 92 / 255, blue: 255 / 255)      // #745CFF
            accentGradientTop = Color(red: 124 / 255, green: 108 / 255, blue: 255 / 255)  // #7C6CFF
            accentGradientBottom = Color(red: 109 / 255, green: 40 / 255, blue: 217 / 255) // #6D28D9
            accentSoft = Color(red: 139 / 255, green: 116 / 255, blue: 246 / 255).opacity(0.18)
            success = Color(red: 63 / 255, green: 185 / 255, blue: 80 / 255)      // #3FB950
            successBright = Color(red: 126 / 255, green: 231 / 255, blue: 135 / 255) // #7EE787
            danger = Color(red: 248 / 255, green: 81 / 255, blue: 73 / 255)       // #F85149
        case .bright:
            canvasTop = Color(red: 243 / 255, green: 240 / 255, blue: 248 / 255)  // #F3F0F8
            canvasMid = Color(red: 235 / 255, green: 230 / 255, blue: 242 / 255)  // #EBE6F2
            canvasBottom = Color(red: 228 / 255, green: 224 / 255, blue: 234 / 255) // #E4E0EA
            glowViolet = Color(red: 167 / 255, green: 139 / 255, blue: 250 / 255).opacity(0.22)
            glowBlue = Color(red: 118 / 255, green: 99 / 255, blue: 170 / 255).opacity(0.16)
            glowDeep = Color(red: 139 / 255, green: 116 / 255, blue: 246 / 255).opacity(0.12)
            glowSoft = Color.white.opacity(0.35)
            text = Color(red: 23 / 255, green: 38 / 255, blue: 58 / 255)          // #17263A
            heading = Color(red: 18 / 255, green: 30 / 255, blue: 46 / 255)
            muted = Color(red: 113 / 255, green: 121 / 255, blue: 131 / 255)      // #717983
            subtle = Color(red: 130 / 255, green: 136 / 255, blue: 145 / 255)
            glassFill = Color.white.opacity(0.52)
            glassFillStrong = Color.white.opacity(0.72)
            glassFillSoft = Color.white.opacity(0.34)
            glassEdge = Color.white.opacity(0.38)
            glassEdgeSoft = Color.white.opacity(0.18)
            accent = Color(red: 118 / 255, green: 99 / 255, blue: 170 / 255)      // #7663AA
            accentGradientTop = Color(red: 124 / 255, green: 108 / 255, blue: 255 / 255)
            accentGradientBottom = Color(red: 109 / 255, green: 40 / 255, blue: 217 / 255)
            accentSoft = Color(red: 118 / 255, green: 99 / 255, blue: 170 / 255).opacity(0.14)
            success = Color(red: 46 / 255, green: 140 / 255, blue: 62 / 255)
            successBright = Color(red: 46 / 255, green: 140 / 255, blue: 62 / 255)
            danger = Color(red: 207 / 255, green: 44 / 255, blue: 38 / 255)
        }
    }

    var accentGradient: LinearGradient {
        LinearGradient(colors: [accentGradientTop, accentGradientBottom],
                       startPoint: .topLeading, endPoint: .bottomTrailing)
    }
}

private enum LocusPaletteKey: EnvironmentKey {
    static let defaultValue = LocusPalette(scheme: .dark)
}

extension EnvironmentValues {
    var locusPalette: LocusPalette {
        get { self[LocusPaletteKey.self] }
        set { self[LocusPaletteKey.self] = newValue }
    }
}

enum LocusMetrics {
    /// Bottom breathing room. With navigation moved into the side menu there is no dock to
    /// clear, so this is just the home-indicator gap — the rest of the screen is content.
    static let bottomClearance: CGFloat = 26
    static let cardRadius: CGFloat = 20
    static let buttonRadius: CGFloat = 14
}

enum LocusFont {
    static func kicker() -> Font { .system(size: 11, weight: .bold) }
    static func title() -> Font { .system(size: 30, weight: .bold) }
    static func section() -> Font { .system(size: 19, weight: .bold) }
    static func body() -> Font { .system(size: 15, weight: .regular) }
    static func bodySemibold() -> Font { .system(size: 15, weight: .semibold) }
    static func caption() -> Font { .system(size: 12, weight: .medium) }
    static func micro() -> Font { .system(size: 10, weight: .semibold) }
}
