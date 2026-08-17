import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

// Renders the Locus mark as a 1024×1024 app icon: the purple gradient of
// `palette.accentGradient` full-bleed (iOS masks the corners itself, and an app icon
// must be opaque), the white orbit ring and the offset dot from `LocusLogo`.
let side = 1024.0
let space = CGColorSpaceCreateDeviceRGB()
guard let context = CGContext(
    data: nil, width: Int(side), height: Int(side),
    bitsPerComponent: 8, bytesPerRow: 0, space: space,
    // noneSkipLast, not premultipliedLast: an app icon must ship without an alpha
    // channel — iOS masks the corners itself and an alpha icon renders wrong.
    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
) else { fatalError("could not create the bitmap context") }

context.setAllowsAntialiasing(true)
context.interpolationQuality = .high

// Background: #7C6CFF → #6D28D9, top-leading to bottom-trailing.
let top = CGColor(red: 124 / 255, green: 108 / 255, blue: 255 / 255, alpha: 1)
let bottom = CGColor(red: 109 / 255, green: 40 / 255, blue: 217 / 255, alpha: 1)
if let gradient = CGGradient(colorsSpace: space, colors: [top, bottom] as CFArray, locations: [0, 1]) {
    context.drawLinearGradient(
        gradient,
        start: CGPoint(x: 0, y: side),
        end: CGPoint(x: side, y: 0),
        options: []
    )
}

// A soft highlight so the flat square reads as a lens rather than a swatch.
if let glow = CGGradient(
    colorsSpace: space,
    colors: [CGColor(red: 1, green: 1, blue: 1, alpha: 0.22),
             CGColor(red: 1, green: 1, blue: 1, alpha: 0)] as CFArray,
    locations: [0, 1]
) {
    context.drawRadialGradient(
        glow,
        startCenter: CGPoint(x: side * 0.3, y: side * 0.78), startRadius: 0,
        endCenter: CGPoint(x: side * 0.3, y: side * 0.78), endRadius: side * 0.6,
        options: []
    )
}

let centre = CGPoint(x: side / 2, y: side / 2)

// Orbit ring — same 52% diameter as the in-app logo.
let ringDiameter = side * 0.52
let ringWidth = side * 0.062
context.setStrokeColor(CGColor(red: 1, green: 1, blue: 1, alpha: 0.92))
context.setLineWidth(ringWidth)
context.strokeEllipse(in: CGRect(
    x: centre.x - ringDiameter / 2,
    y: centre.y - ringDiameter / 2,
    width: ringDiameter,
    height: ringDiameter
))

// The dot that sits off the ring's top-trailing edge.
let dotDiameter = side * 0.15
context.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
context.fillEllipse(in: CGRect(
    x: centre.x + side * 0.26 - dotDiameter / 2,
    y: centre.y + side * 0.26 - dotDiameter / 2,
    width: dotDiameter,
    height: dotDiameter
))

guard let image = context.makeImage() else { fatalError("could not render the icon") }
let out = URL(fileURLWithPath: CommandLine.arguments[1])
guard let destination = CGImageDestinationCreateWithURL(out as CFURL, UTType.png.identifier as CFString, 1, nil) else {
    fatalError("could not create the png destination")
}
CGImageDestinationAddImage(destination, image, nil)
guard CGImageDestinationFinalize(destination) else { fatalError("could not write the png") }
print("wrote \(out.path)")
