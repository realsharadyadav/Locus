import SwiftUI
@preconcurrency import WebKit

/// Renders a mermaid diagram in a `WKWebView` using the same mermaid.js version the web app
/// bundles (vendored at `Resources/mermaid.min.js`, mermaid 11.16.0) — the only way to guarantee
/// the two clients draw a diagram identically (plan decision D4).
///
/// The page applies the web's legibility floor from AGENTS.md note 17: scale to
/// `min(1, max(available / natural, 0.7))` and let the canvas scroll from there, rather than
/// shrinking a wide flowchart into an unreadable smudge. The repair passes (auto-quoting labels,
/// subgraph-cycle renaming) are the same JavaScript as `src/lib/mermaid.js`, run inside the page.
struct MermaidWebView: UIViewRepresentable {
    let code: String
    let dark: Bool
    /// Fixed height when zoomable (lightbox); otherwise the view reports its content height back.
    var zoomable: Bool = false
    var onHeight: ((CGFloat) -> Void)?
    var onError: ((String) -> Void)?

    func makeCoordinator() -> Coordinator {
        Coordinator(onHeight: onHeight, onError: onError)
    }

    func makeUIView(context: Context) -> WKWebView {
        let controller = WKUserContentController()
        controller.add(context.coordinator, name: "locus")

        let configuration = WKWebViewConfiguration()
        configuration.userContentController = controller

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.backgroundColor = .clear
        webView.scrollView.showsHorizontalScrollIndicator = zoomable
        webView.scrollView.showsVerticalScrollIndicator = zoomable
        // In the card the diagram never scrolls vertically — the SwiftUI list owns that axis.
        webView.scrollView.bounces = zoomable
        webView.scrollView.isScrollEnabled = true
        context.coordinator.load(into: webView, code: code, dark: dark, zoomable: zoomable)
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        context.coordinator.load(into: webView, code: code, dark: dark, zoomable: zoomable)
    }

    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "locus")
    }

    final class Coordinator: NSObject, WKScriptMessageHandler {
        private let onHeight: ((CGFloat) -> Void)?
        private let onError: ((String) -> Void)?
        private var loadedKey: String?

        init(onHeight: ((CGFloat) -> Void)?, onError: ((String) -> Void)?) {
            self.onHeight = onHeight
            self.onError = onError
        }

        func load(into webView: WKWebView, code: String, dark: Bool, zoomable: Bool) {
            let key = "\(dark)-\(zoomable)-\(code.hashValue)"
            guard loadedKey != key else { return }
            loadedKey = key
            webView.loadHTMLString(
                MermaidPage.html(code: code, dark: dark, zoomable: zoomable),
                baseURL: MermaidPage.resourceDirectory
            )
        }

        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let payload = message.body as? [String: Any] else { return }
            if let height = payload["height"] as? Double {
                onHeight?(CGFloat(height))
            }
            if let error = payload["error"] as? String {
                onError?(error)
            }
        }
    }
}

enum MermaidPage {
    /// The bundle directory is the base URL so the page can `<script src="mermaid.min.js">`
    /// straight off disk — no network, so diagrams render offline.
    static var resourceDirectory: URL? {
        Bundle.main.url(forResource: "mermaid.min", withExtension: "js")?.deletingLastPathComponent()
    }

    static func html(code: String, dark: Bool, zoomable: Bool) -> String {
        let escaped = code
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "`", with: "\\`")
            .replacingOccurrences(of: "$", with: "\\$")
        let theme = dark ? "dark" : "neutral"
        let textColor = dark ? "#C9D1D9" : "#17263A"
        let viewport = zoomable
            ? "width=device-width, initial-scale=1, minimum-scale=0.2, maximum-scale=6, user-scalable=yes"
            : "width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no"

        return """
        <!doctype html>
        <html><head>
        <meta name="viewport" content="\(viewport)">
        <style>
          html, body { margin: 0; padding: 0; background: transparent; color: \(textColor);
                       font-family: -apple-system, system-ui, sans-serif; }
          #canvas { overflow-x: auto; overflow-y: hidden; -webkit-overflow-scrolling: touch;
                    display: flex; }
          #canvas.zoom { overflow: auto; height: 100vh; align-items: center; }
          svg { flex: none; margin-inline: auto; height: auto !important; }
          #error { font-size: 12px; padding: 10px; color: #F85149;
                   font-family: ui-monospace, monospace; white-space: pre-wrap; }
        </style>
        </head><body>
        <div id="canvas" class="\(zoomable ? "zoom" : "")"></div>
        <div id="error" hidden></div>
        <script src="mermaid.min.js"></script>
        <script>
        // Below ~70% of the size mermaid laid the diagram out at, node labels stop being
        // readable — see AGENTS.md note 17. Fit to width, but never past this floor.
        const MIN_LEGIBLE_SCALE = 0.7;
        const ZOOMABLE = \(zoomable ? "true" : "false");
        const SOURCE = `\(escaped)`;

        // Same mechanical repairs as src/lib/mermaid.js: a quoted label accepts arbitrary text,
        // so this can only turn an invalid diagram valid, never the reverse.
        function autoQuoteMermaidLabels(code) {
          return code.replace(/([A-Za-z_][\\w-]*)\\[([^\\[\\]]*)\\]/g, (match, id, content) => {
            const trimmed = content.trim();
            if (!trimmed || trimmed.startsWith('"')) return match;
            if (trimmed.startsWith('(') && trimmed.endsWith(')')) return match;
            if (!/[()/\\\\{}|#;]/.test(trimmed)) return match;
            return id + '["' + trimmed.replace(/"/g, "'") + '"]';
          });
        }

        // A narrow screen re-orients left-right flowcharts top-down. Only the drawing changes —
        // "view source" and copy still hand back the author's original diagram.
        function reflowTopDown(code) {
          let done = false;
          return (code || '').replace(/^(\\s*(?:flowchart|graph)[ \\t]+)(LR|RL)\\b/gim, (match, head) => {
            if (done) return match;
            done = true;
            return head + 'TD';
          });
        }

        function post(payload) {
          window.webkit?.messageHandlers?.locus?.postMessage(payload);
        }

        function fit(svg) {
          const viewBox = (svg.getAttribute('viewBox') || '').trim().split(/\\s+/);
          const natural = Number(viewBox[2]);
          if (!Number.isFinite(natural) || natural <= 0) return;
          const available = document.getElementById('canvas').clientWidth;
          const scale = ZOOMABLE ? 1 : Math.min(1, Math.max(available / natural, MIN_LEGIBLE_SCALE));
          svg.style.width = (natural * scale) + 'px';
          svg.removeAttribute('height');
        }

        async function draw() {
          const narrow = window.innerWidth <= 640;
          const code = narrow && !ZOOMABLE ? reflowTopDown(SOURCE) : SOURCE;
          mermaid.initialize({
            startOnLoad: false,
            theme: '\(theme)',
            // 'antiscript' renders <br/> in labels while still stripping <script> — diagram
            // source can come from an LLM answer, so 'loose' is not acceptable here.
            securityLevel: 'antiscript',
            flowchart: { htmlLabels: true },
            fontFamily: 'inherit',
            suppressErrorRendering: true,
          });
          let rendered;
          try {
            rendered = await mermaid.render('locus-diagram', code);
          } catch (first) {
            const repaired = autoQuoteMermaidLabels(code);
            if (repaired === code) {
              return fail(first?.message || 'Invalid diagram syntax');
            }
            try {
              rendered = await mermaid.render('locus-diagram-repaired', repaired);
            } catch {
              return fail(first?.message || 'Invalid diagram syntax');
            }
          }
          const canvas = document.getElementById('canvas');
          canvas.innerHTML = rendered.svg;
          const svg = canvas.querySelector('svg');
          if (svg) fit(svg);
          requestAnimationFrame(() => {
            post({ height: ZOOMABLE ? window.innerHeight : (svg ? svg.getBoundingClientRect().height : 0) });
          });
        }

        function fail(message) {
          const box = document.getElementById('error');
          box.hidden = false;
          box.textContent = message;
          post({ error: message, height: box.getBoundingClientRect().height + 20 });
        }

        draw();
        </script>
        </body></html>
        """
    }
}

/// A diagram inside an answer: rendered card, copy, view-source and a tap target for the lightbox.
struct MermaidBlockView: View {
    @Environment(\.locusPalette) private var palette
    let code: String
    @State private var height: CGFloat = 120
    @State private var failed: String?
    @State private var showsSource = false
    @State private var showsLightbox = false
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Text("diagram")
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(palette.subtle)
                Spacer()
                Button {
                    LocusHaptics.light()
                    showsSource.toggle()
                } label: {
                    Image(systemName: showsSource ? "chevron.left.forwardslash.chevron.right" : "chevron.left.slash.chevron.right")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(palette.muted)
                }
                .buttonStyle(.plain)
                Button {
                    // Copy hands back exactly what the answer contained, never a reflowed
                    // phone-shaped rewrite of it.
                    UIPasteboard.general.string = code
                    LocusHaptics.light()
                    copied = true
                    Task {
                        try? await Task.sleep(for: .seconds(1.6))
                        copied = false
                    }
                } label: {
                    Image(systemName: copied ? "checkmark" : "doc.on.doc")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(copied ? palette.success : palette.muted)
                }
                .buttonStyle(.plain)
                if failed == nil {
                    Button {
                        LocusHaptics.light()
                        showsLightbox = true
                    } label: {
                        Image(systemName: "arrow.up.left.and.arrow.down.right")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(palette.accent)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)

            Divider().overlay(palette.glassEdgeSoft)

            if showsSource {
                ScrollView(.horizontal, showsIndicators: false) {
                    Text(code)
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(palette.text)
                        .textSelection(.enabled)
                        .padding(12)
                }
            } else {
                MermaidWebView(
                    code: code,
                    dark: palette.scheme == .dark,
                    onHeight: { measured in
                        // Clamp so a broken measurement can't collapse or balloon the card.
                        height = min(max(measured, 80), 900)
                    },
                    onError: { failed = $0 }
                )
                .frame(height: height)
                .padding(.vertical, 8)
                .onTapGesture {
                    guard failed == nil else { return }
                    LocusHaptics.light()
                    showsLightbox = true
                }
            }
        }
        .background(palette.glassFillSoft)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(palette.glassEdgeSoft, lineWidth: 1)
        )
        .fullScreenCover(isPresented: $showsLightbox) {
            DiagramLightbox(code: code)
        }
    }
}

/// Full-screen diagram: pinch to zoom and pan, handed to the web view's own scroll view so the
/// gestures keep native momentum (the web port of AGENTS.md note 18).
struct DiagramLightbox: View {
    @Environment(\.locusPalette) private var palette
    @Environment(\.dismiss) private var dismiss
    let code: String

    var body: some View {
        ZStack(alignment: .topTrailing) {
            palette.canvasMid.ignoresSafeArea()
            MermaidWebView(code: code, dark: palette.scheme == .dark, zoomable: true)
                .ignoresSafeArea(edges: .bottom)

            Button {
                LocusHaptics.light()
                dismiss()
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(palette.text)
                    .frame(width: 40, height: 40)
                    .background(palette.glassFillStrong)
                    .clipShape(Circle())
                    .overlay(Circle().strokeBorder(palette.glassEdge, lineWidth: 1))
            }
            .buttonStyle(.plain)
            .padding(.trailing, 16)
            .padding(.top, 12)
        }
    }
}
