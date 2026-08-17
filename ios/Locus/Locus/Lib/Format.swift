import Foundation

/// Display formatting ported 1:1 from the web app (`src/lib/format.js`, `src/utils.js`) so
/// the same file or timestamp reads identically on both clients.
enum LocusFormat {
    static func greeting(forHour hour: Int) -> String {
        switch hour {
        case ..<5: return "Still up?"
        case ..<12: return "Good morning"
        case ..<17: return "Good afternoon"
        case ..<21: return "Good evening"
        default: return "Good night"
        }
    }

    static func fileSize(_ bytes: Int) -> String {
        let size = Double(max(0, bytes))
        if size >= 1024 * 1024 {
            let mb = size / (1024 * 1024)
            return size >= 10 * 1024 * 1024 ? "\(Int(mb.rounded())) MB" : String(format: "%.1f MB", mb)
        }
        if size >= 1024 {
            let kb = size / 1024
            return size >= 10 * 1024 ? "\(Int(kb.rounded())) KB" : String(format: "%.1f KB", kb)
        }
        return "\(Int(size)) B"
    }

    static func fileMetaLine(_ file: StoredFileRead) -> String {
        let chunks = file.embeddingChunks
        let chunkLabel = chunks == 1 ? "1 chunk" : "\(chunks) chunks"
        return "\(fileSize(file.size)) · \(chunkLabel)"
    }

    static func displayTime(_ date: Date, now: Date = Date()) -> String {
        let seconds = max(0, now.timeIntervalSince(date))
        if seconds < 60 { return "Just now" }
        if seconds < 3600 { return "\(Int(seconds / 60)) min ago" }
        if seconds < 86_400 { return "\(Int(seconds / 3600)) hr ago" }
        if seconds < 172_800 { return "Yesterday" }
        return date.formatted(.dateTime.month(.abbreviated).day())
    }

    /// "1 file" / "3 files" — the pluralisation the capability strip and stats rely on.
    static func plural(_ count: Int, _ singular: String, _ plural: String? = nil) -> String {
        count == 1 ? "\(count) \(singular)" : "\(count) \(plural ?? singular + "s")"
    }
}
