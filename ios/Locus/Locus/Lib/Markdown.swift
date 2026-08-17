import SwiftUI

/// A small block-level markdown parser for assistant answers. SwiftUI's `AttributedString`
/// handles inline styling (bold/italic/code/links) but has no concept of headings, fenced code,
/// lists or tables — so blocks are split here and rendered as real views, which is also what
/// lets code blocks carry a copy button.
enum MarkdownBlock: Identifiable {
    case heading(level: Int, text: String)
    case paragraph(String)
    case bullet([String])
    case numbered([String])
    case quote(String)
    case code(language: String, body: String)
    case table(header: [String], rows: [[String]])
    case rule

    var id: String {
        switch self {
        case .heading(let level, let text): return "h\(level)-\(text.hashValue)"
        case .paragraph(let text): return "p-\(text.hashValue)"
        case .bullet(let items): return "ul-\(items.joined().hashValue)"
        case .numbered(let items): return "ol-\(items.joined().hashValue)"
        case .quote(let text): return "q-\(text.hashValue)"
        case .code(let language, let body): return "code-\(language)-\(body.hashValue)"
        case .table(let header, let rows): return "t-\(header.joined().hashValue)-\(rows.count)"
        case .rule: return "hr-\(UUID().uuidString)"
        }
    }
}

enum MarkdownParser {
    static func parse(_ markdown: String) -> [MarkdownBlock] {
        var blocks: [MarkdownBlock] = []
        let lines = markdown.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n")
        var index = 0

        func flushParagraph(_ buffer: inout [String]) {
            guard !buffer.isEmpty else { return }
            blocks.append(.paragraph(buffer.joined(separator: "\n")))
            buffer.removeAll()
        }

        var paragraph: [String] = []
        while index < lines.count {
            let line = lines[index]
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            // Fenced code — everything until the closing fence is verbatim.
            if trimmed.hasPrefix("```") {
                flushParagraph(&paragraph)
                let language = String(trimmed.dropFirst(3)).trimmingCharacters(in: .whitespaces)
                var body: [String] = []
                index += 1
                while index < lines.count,
                      !lines[index].trimmingCharacters(in: .whitespaces).hasPrefix("```") {
                    body.append(lines[index])
                    index += 1
                }
                index += 1 // closing fence
                blocks.append(.code(language: language, body: body.joined(separator: "\n")))
                continue
            }

            if trimmed.isEmpty {
                flushParagraph(&paragraph)
                index += 1
                continue
            }

            if trimmed.range(of: "^(-{3,}|\\*{3,}|_{3,})$", options: .regularExpression) != nil {
                flushParagraph(&paragraph)
                blocks.append(.rule)
                index += 1
                continue
            }

            if let match = trimmed.range(of: "^#{1,6} ", options: .regularExpression) {
                flushParagraph(&paragraph)
                let hashes = trimmed.distance(from: trimmed.startIndex, to: match.upperBound) - 1
                blocks.append(.heading(level: hashes, text: String(trimmed[match.upperBound...])))
                index += 1
                continue
            }

            if trimmed.hasPrefix("> ") {
                flushParagraph(&paragraph)
                var quoted: [String] = []
                while index < lines.count {
                    let candidate = lines[index].trimmingCharacters(in: .whitespaces)
                    guard candidate.hasPrefix(">") else { break }
                    quoted.append(String(candidate.dropFirst()).trimmingCharacters(in: .whitespaces))
                    index += 1
                }
                blocks.append(.quote(quoted.joined(separator: "\n")))
                continue
            }

            // Table: a header row followed by a |---|---| separator.
            if trimmed.hasPrefix("|"), index + 1 < lines.count,
               lines[index + 1].trimmingCharacters(in: .whitespaces)
                .range(of: "^\\|?[\\s:|-]+\\|[\\s:|-]*$", options: .regularExpression) != nil {
                flushParagraph(&paragraph)
                let header = cells(trimmed)
                index += 2
                var rows: [[String]] = []
                while index < lines.count {
                    let candidate = lines[index].trimmingCharacters(in: .whitespaces)
                    guard candidate.hasPrefix("|") else { break }
                    rows.append(cells(candidate))
                    index += 1
                }
                blocks.append(.table(header: header, rows: rows))
                continue
            }

            if trimmed.range(of: "^[-*+] ", options: .regularExpression) != nil {
                flushParagraph(&paragraph)
                var items: [String] = []
                while index < lines.count {
                    let candidate = lines[index].trimmingCharacters(in: .whitespaces)
                    guard let bullet = candidate.range(of: "^[-*+] ", options: .regularExpression) else { break }
                    items.append(String(candidate[bullet.upperBound...]))
                    index += 1
                }
                blocks.append(.bullet(items))
                continue
            }

            if trimmed.range(of: "^\\d+\\. ", options: .regularExpression) != nil {
                flushParagraph(&paragraph)
                var items: [String] = []
                while index < lines.count {
                    let candidate = lines[index].trimmingCharacters(in: .whitespaces)
                    guard let number = candidate.range(of: "^\\d+\\. ", options: .regularExpression) else { break }
                    items.append(String(candidate[number.upperBound...]))
                    index += 1
                }
                blocks.append(.numbered(items))
                continue
            }

            paragraph.append(trimmed)
            index += 1
        }
        flushParagraph(&paragraph)
        return blocks
    }

    private static func cells(_ row: String) -> [String] {
        var trimmed = row
        if trimmed.hasPrefix("|") { trimmed.removeFirst() }
        if trimmed.hasSuffix("|") { trimmed.removeLast() }
        return trimmed.components(separatedBy: "|").map { $0.trimmingCharacters(in: .whitespaces) }
    }

    /// Inline markdown → AttributedString, falling back to plain text if it can't be parsed.
    static func inline(_ text: String) -> AttributedString {
        (try? AttributedString(
            markdown: text,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        )) ?? AttributedString(text)
    }
}

/// Renders parsed markdown with Locus styling.
struct MarkdownText: View {
    @Environment(\.locusPalette) private var palette
    let markdown: String
    /// While tokens are still arriving a ```mermaid fence stays a code block — the diagram is
    /// only handed to mermaid once the whole message has landed.
    var streaming: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(MarkdownParser.parse(markdown)) { block in
                switch block {
                case .heading(let level, let text):
                    Text(MarkdownParser.inline(text))
                        .font(.system(size: level <= 1 ? 20 : level == 2 ? 17 : 15, weight: .bold))
                        .foregroundStyle(palette.heading)
                        .padding(.top, 2)

                case .paragraph(let text):
                    Text(MarkdownParser.inline(text))
                        .font(.system(size: 15))
                        .foregroundStyle(palette.text)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)

                case .bullet(let items):
                    VStack(alignment: .leading, spacing: 5) {
                        ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                            HStack(alignment: .top, spacing: 8) {
                                Circle()
                                    .fill(palette.accent)
                                    .frame(width: 5, height: 5)
                                    .padding(.top, 7)
                                Text(MarkdownParser.inline(item))
                                    .font(.system(size: 15))
                                    .foregroundStyle(palette.text)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }

                case .numbered(let items):
                    VStack(alignment: .leading, spacing: 5) {
                        ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                            HStack(alignment: .top, spacing: 8) {
                                Text("\(index + 1).")
                                    .font(.system(size: 14, weight: .bold))
                                    .foregroundStyle(palette.accent)
                                Text(MarkdownParser.inline(item))
                                    .font(.system(size: 15))
                                    .foregroundStyle(palette.text)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }

                case .quote(let text):
                    HStack(alignment: .top, spacing: 10) {
                        Rectangle()
                            .fill(palette.accent.opacity(0.6))
                            .frame(width: 3)
                        Text(MarkdownParser.inline(text))
                            .font(.system(size: 15))
                            .foregroundStyle(palette.muted)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                case .code(let language, let body):
                    // A ```mermaid fence is a diagram, not code — but only once the message has
                    // finished streaming, since a half-arrived diagram cannot parse.
                    if language.lowercased() == "mermaid" && !streaming {
                        MermaidBlockView(code: body)
                    } else {
                        CodeBlockView(language: language, code: body)
                    }

                case .table(let header, let rows):
                    MarkdownTableView(header: header, rows: rows)

                case .rule:
                    Rectangle()
                        .fill(palette.glassEdgeSoft)
                        .frame(height: 1)
                }
            }
        }
    }
}

struct CodeBlockView: View {
    @Environment(\.locusPalette) private var palette
    let language: String
    let code: String
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(language.isEmpty ? "code" : language)
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(palette.subtle)
                Spacer()
                Button {
                    UIPasteboard.general.string = code
                    LocusHaptics.light()
                    copied = true
                    Task {
                        try? await Task.sleep(for: .seconds(1.6))
                        copied = false
                    }
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: copied ? "checkmark" : "doc.on.doc")
                        Text(copied ? "Copied" : "Copy")
                    }
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(copied ? palette.success : palette.muted)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)

            Divider().overlay(palette.glassEdgeSoft)

            ScrollView(.horizontal, showsIndicators: false) {
                Text(code)
                    .font(.system(size: 12.5, design: .monospaced))
                    .foregroundStyle(palette.text)
                    .textSelection(.enabled)
                    .padding(12)
            }
        }
        .background(palette.glassFillSoft)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(palette.glassEdgeSoft, lineWidth: 1)
        )
    }
}

struct MarkdownTableView: View {
    @Environment(\.locusPalette) private var palette
    let header: [String]
    let rows: [[String]]

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top, spacing: 0) {
                    ForEach(Array(header.enumerated()), id: \.offset) { _, cell in
                        Text(MarkdownParser.inline(cell))
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(palette.heading)
                            .frame(width: 150, alignment: .leading)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 8)
                    }
                }
                .background(palette.accentSoft)

                ForEach(Array(rows.enumerated()), id: \.offset) { rowIndex, row in
                    HStack(alignment: .top, spacing: 0) {
                        ForEach(Array(row.enumerated()), id: \.offset) { _, cell in
                            Text(MarkdownParser.inline(cell))
                                .font(.system(size: 12))
                                .foregroundStyle(palette.text)
                                .frame(width: 150, alignment: .leading)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 8)
                        }
                    }
                    .background(rowIndex.isMultiple(of: 2) ? Color.clear : palette.glassFillSoft)
                }
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(palette.glassEdgeSoft, lineWidth: 1)
        )
    }
}
