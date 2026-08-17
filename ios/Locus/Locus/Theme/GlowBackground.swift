import SwiftUI

/// The background every screen sits on: the deep canvas gradient with four soft radial
/// glows, matching the web `body` background in `34-glass.css`.
struct GlowBackground: View {
    @Environment(\.locusPalette) private var palette

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [palette.canvasTop, palette.canvasMid, palette.canvasBottom],
                startPoint: UnitPoint(x: 0.15, y: 0),
                endPoint: UnitPoint(x: 0.85, y: 1)
            )
            RadialGradient(colors: [palette.glowViolet, .clear],
                           center: .topLeading, startRadius: 0, endRadius: 430)
            RadialGradient(colors: [palette.glowBlue, .clear],
                           center: .topTrailing, startRadius: 0, endRadius: 330)
            RadialGradient(colors: [palette.glowDeep, .clear],
                           center: .bottomTrailing, startRadius: 0, endRadius: 400)
            RadialGradient(colors: [palette.glowSoft, .clear],
                           center: UnitPoint(x: 0.3, y: 0.7), startRadius: 0, endRadius: 280)
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
    }
}
