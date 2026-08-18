import SwiftUI

// Lives with Ask, which is the only place effort is chosen. It sat in the Home model
// until Home was removed.

/// The three user-facing effort modes, mirroring `SLASH_COMMANDS` in `src/lib/ask.js`.
/// Titles, blurbs and accent colors are the web's, so both clients describe effort the same way.
enum EffortMode: String, CaseIterable {
    case light, thinking, deepSummary

    var friendlyLabel: String {
        switch self {
        case .light: return "Normal"
        case .thinking: return "High"
        case .deepSummary: return "Max"
        }
    }

    var friendlyDescription: String {
        switch self {
        case .light: return "Fast answer from the most relevant context"
        case .thinking: return "Inspects every selected file, or researches the web if none are selected"
        case .deepSummary: return "Covers every document section, or the widest web research if none are selected"
        }
    }

    var systemImage: String {
        switch self {
        case .light: return "dot.radiowaves.left.and.right"
        case .thinking: return "sparkles"
        case .deepSummary: return "book"
        }
    }

    var accent: Color {
        switch self {
        case .light: return Color(red: 124 / 255, green: 108 / 255, blue: 255 / 255)   // #7c6cff
        case .thinking: return Color(red: 167 / 255, green: 139 / 255, blue: 250 / 255) // #a78bfa
        case .deepSummary: return Color(red: 96 / 255, green: 165 / 255, blue: 250 / 255) // #60a5fa
        }
    }
}
