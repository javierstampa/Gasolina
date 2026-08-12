import SwiftUI
import WebKit

/* ---------------- Descarga de datos (MITECO + MIMIT) ---------------- */

enum DataStore {
    static func cacheDir() throws -> URL {
        let fm = FileManager.default
        let dir = try fm.url(for: .cachesDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
            .appendingPathComponent("gasall-data", isDirectory: true)
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }
}

enum DataFetcher {
    static let UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"

    static func fetchAll(to dir: URL, progress: @escaping (String) -> Void) async throws -> [String: Any] {
        progress("Descargando datos de España…")
        let es = try await fetch(URL(string: "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/")!)
        try es.write(to: dir.appendingPathComponent("datos.json"))

        var esCount = 0
        var fechaEs = "desconocida"
        if let json = try? JSONSerialization.jsonObject(with: es) as? [String: Any] {
            esCount = (json["ListaEESSPrecio"] as? [Any])?.count ?? 0
            fechaEs = json["Fecha"] as? String ?? "desconocida"
        }

        progress("Descargando datos de Italia…")
        async let a: Data = fetch(URL(string: "https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv")!)
        async let p: Data = fetch(URL(string: "https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv")!)
        let (ana, pre) = try await (a, p)
        try ana.write(to: dir.appendingPathComponent("anagrafica.csv"))
        try pre.write(to: dir.appendingPathComponent("prezzo.csv"))

        let itCount = String(decoding: ana, as: UTF8.self)
            .split(whereSeparator: \.isNewline)
            .filter { $0.contains("|") }.count

        return ["fecha": fechaEs, "estaciones": esCount, "italia": itCount]
    }

    private static func fetch(_ url: URL) async throws -> Data {
        var req = URLRequest(url: url)
        req.setValue(UA, forHTTPHeaderField: "User-Agent")
        req.timeoutInterval = 120
        let (data, resp) = try await URLSession.shared.data(for: req)
        if let http = resp as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw NSError(domain: "gasall", code: http.statusCode,
                          userInfo: [NSLocalizedDescriptionKey: "HTTP \(http.statusCode)"])
        }
        return data
    }
}

/* ---------------- Vista principal ---------------- */

enum FetchPhase {
    case idle
    case downloading(String)
    case ready
    case failed(String)
}

struct ContentView: View {
    @State private var phase: FetchPhase = .idle

    var body: some View {
        ZStack {
            if case .ready = phase {
                GasWebView()
                    .ignoresSafeArea()
            }
            switch phase {
            case .idle, .downloading(let msg):
                VStack(spacing: 16) {
                    ProgressView().scaleEffect(1.6)
                    Text(msg).font(.footnote).foregroundColor(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(.systemBackground))
            case .failed(let err):
                VStack(spacing: 16) {
                    Text("No se pudieron descargar los datos").font(.headline)
                    Text(err).font(.footnote).foregroundColor(.secondary)
                        .multilineTextAlignment(.center).padding(.horizontal)
                    Button("Reintentar") { start() }
                        .buttonStyle(.borderedProminent)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(.systemBackground))
            case .ready:
                EmptyView()
            }
        }
        .onAppear { start() }
    }

    func start() {
        phase = .downloading("Descargando datos…")
        Task {
            do {
                let dir = try DataStore.cacheDir()
                _ = try await DataFetcher.fetchAll(to: dir) { msg in
                    DispatchQueue.main.async { phase = .downloading(msg) }
                }
                DispatchQueue.main.async { phase = .ready }
            } catch {
                DispatchQueue.main.async { phase = .failed(error.localizedDescription) }
            }
        }
    }
}

/* ---------------- WebView con esquema gasall:// ---------------- */

struct GasWebView: UIViewRepresentable {
    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.defaultWebpagePreferences.allowsContentJavaScript = true
        config.setURLSchemeHandler(GasAllSchemeHandler(), forURLScheme: "gasall")
        config.userContentController.add(context.coordinator, name: "gasall")

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.uiDelegate = context.coordinator
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.load(URLRequest(url: URL(string: "gasall://app/")!))
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKUIDelegate, WKNavigationDelegate, WKScriptMessageHandler {
        func webView(_ webView: WKWebView, didReceive message: WKScriptMessage) {
            guard message.name == "gasall",
                  let body = message.body as? [String: Any],
                  body["type"] as? String == "refresh" else { return }
            Task {
                var result: [String: Any] = ["ok": true]
                do {
                    let dir = try DataStore.cacheDir()
                    result = try await DataFetcher.fetchAll(to: dir) { _ in }
                } catch {
                    result = ["error": error.localizedDescription]
                }
                await MainActor.run {
                    if let js = Self.refreshScript(result) {
                        webView.evaluateJavaScript(js) { _, _ in }
                    }
                }
            }
        }

        static func refreshScript(_ r: [String: Any]) -> String? {
            guard let data = try? JSONSerialization.data(withJSONObject: r),
                  let s = String(data: data, encoding: .utf8) else { return nil }
            return "window.__gasallRefreshDone(\(s))"
        }

        func webView(_ webView: WKWebView,
                     requestGeolocationPermissionFor origin: WKSecurityOrigin,
                     initiatedByFrame frame: WKFrameInfo,
                     decisionHandler: @escaping (WKPermissionDecision) -> Void) {
            decisionHandler(.prompt)
        }

        func webView(_ webView: WKWebView,
                     requestUserMediaPermissionFor origin: WKSecurityOrigin,
                     initiatedByFrame frame: WKFrameInfo,
                     type: WKMediaCaptureType,
                     decisionHandler: @escaping (WKPermissionDecision) -> Void) {
            decisionHandler(.prompt)
        }
    }
}

/* ---------------- Handler del esquema gasall:// ---------------- */

final class GasAllSchemeHandler: NSObject, WKURLSchemeHandler {
    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        guard let url = urlSchemeTask.request.url else {
            urlSchemeTask.didFailWithError(NSError(domain: "gasall", code: -1))
            return
        }
        var data: Data? = nil
        var mime = "text/html"

        if url.path == "/" || url.path == "/index.html" {
            data = bundleFile("static/index.html")
        } else if url.path.hasPrefix("/static/") {
            let rel = String(url.path.dropFirst("/static/".count))
            data = bundleFile("static/" + rel)
            mime = Self.mime(rel)
        } else if url.path.hasPrefix("/data/") {
            let rel = String(url.path.dropFirst("/data/".count))
            if let cached = try? Data(contentsOf: DataStore.cacheDir().appendingPathComponent(rel)) {
                data = cached
            } else {
                data = bundleFile("static/" + rel)
            }
            mime = Self.mime(rel)
        }

        guard let d = data else {
            urlSchemeTask.didFailWithError(NSError(domain: "gasall", code: 404,
                                                   userInfo: [NSLocalizedDescriptionKey: url.path]))
            return
        }
        let resp = URLResponse(url: url, mimeType: mime,
                               expectedContentLength: d.count, textEncodingName: nil)
        urlSchemeTask.didReceive(resp)
        urlSchemeTask.didReceive(d)
        urlSchemeTask.didFinish()
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {}

    private func bundleFile(_ rel: String) -> Data? {
        let parts = rel.split(separator: "/").map(String.init)
        guard let name = parts.last else { return nil }
        let sub = parts.dropLast().joined(separator: "/")
        guard let u = Bundle.main.url(forResource: name, withExtension: nil,
                                      subdirectory: sub.isEmpty ? nil : sub) else { return nil }
        return try? Data(contentsOf: u)
    }

    static func mime(_ rel: String) -> String {
        if rel.hasSuffix(".js") { return "application/javascript" }
        if rel.hasSuffix(".css") { return "text/css" }
        if rel.hasSuffix(".json") { return "application/json" }
        if rel.hasSuffix(".csv") { return "text/csv" }
        if rel.hasSuffix(".html") { return "text/html" }
        if rel.hasSuffix(".png") { return "image/png" }
        if rel.hasSuffix(".svg") { return "image/svg+xml" }
        if rel.hasSuffix(".jpg") || rel.hasSuffix(".jpeg") { return "image/jpeg" }
        if rel.hasSuffix(".woff2") { return "font/woff2" }
        if rel.hasSuffix(".woff") { return "font/woff" }
        if rel.hasSuffix(".ttf") { return "font/ttf" }
        return "application/octet-stream"
    }
}
