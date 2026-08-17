import XCTest

/// Smoke verification for the iOS app against the real backend on 127.0.0.1:8000.
///
/// Covers: the shell booting into Home, side-menu navigation to every destination, and the
/// full Library flow (create → empty detail → file upload → file row with indexing state →
/// delete). File upload goes through the same multipart endpoint the app uses; the test
/// process shares the simulator's network, so it can talk to the host's backend directly.
///
/// Screenshots are written to the simulator's /tmp and pulled to the host after the run —
/// see ios/STATUS.md for how.
final class LocusSmokeUITests: XCTestCase {

    private var app: XCUIApplication!
    private var createdStoreId: Int?

    override func setUpWithError() throws {
        continueAfterFailure = true
        app = XCUIApplication()
        app.launch()
    }

    override func tearDownWithError() throws {
        // Backstop: if the UI delete did not run, remove the test library via the API so
        // repeated runs never pile up "UI Check" libraries in the workspace.
        if let createdStoreId {
            _ = Self.apiRequest("DELETE", path: "/api/collections/\(createdStoreId)")
        }
    }

    // MARK: - Test

    func testShellDestinationsAndLibraryFlow() throws {
        // 1. Home
        XCTAssertTrue(app.staticTexts["Welcome to Locus"].waitForExistence(timeout: 20),
                      "Home should be the first screen")
        shot("01-home")

        // 2. Side menu lists every destination
        openMenu()
        // The Library row carries a live count badge, so its combined accessibility label is
        // "Library 3", not "Library" — match the prefix instead of the exact label.
        let libraryRow = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Library'")).firstMatch
        XCTAssertTrue(libraryRow.waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["Ask"].exists)
        XCTAssertTrue(app.buttons["Private"].exists)
        XCTAssertTrue(app.buttons["Secret Images"].exists)
        shot("02-menu")

        // 3. Library — Phase 6 flow
        libraryRow.tap()
        XCTAssertTrue(app.staticTexts["Library"].waitForExistence(timeout: 5))

        let name = "UI Check \(Int(Date().timeIntervalSince1970) % 100000)"
        let createButton = app.buttons["New library"]
        XCTAssertTrue(createButton.waitForExistence(timeout: 5))
        createButton.tap()

        let nameField = app.textFields["Product thinking"]
        XCTAssertTrue(nameField.waitForExistence(timeout: 5))
        nameField.tap()
        nameField.typeText(name)
        app.buttons["Create library"].tap()

        let card = app.staticTexts[name]
        XCTAssertTrue(card.waitForExistence(timeout: 6), "The new library card should appear")
        shot("03-library-created")

        // Empty detail
        card.tap()
        XCTAssertTrue(app.staticTexts["No files yet"].waitForExistence(timeout: 5),
                      "A fresh library should show the empty state")
        shot("04-library-empty")
        dismissSheet()

        // Upload through the same API the app posts to, then refresh and open the card.
        let storeId = try Self.storeId(named: name)
        createdStoreId = storeId
        try Self.uploadFile(storeId: storeId, fileName: "locus-ui-check.txt",
                            text: "Uploaded by the iOS UI test.")
        pullToRefresh()
        XCTAssertTrue(app.staticTexts["1 file"].waitForExistence(timeout: 8),
                      "The card should report one file after refresh")

        card.tap()
        XCTAssertTrue(app.staticTexts["locus-ui-check.txt"].waitForExistence(timeout: 6),
                      "The uploaded file row should be listed")
        shot("05-library-file")
        dismissSheet()

        // Delete through the context menu + confirmation dialog.
        card.press(forDuration: 1.2)
        let menuDelete = app.buttons["Delete library"].firstMatch
        XCTAssertTrue(menuDelete.waitForExistence(timeout: 5), "Context menu should offer delete")
        menuDelete.tap()
        XCTAssertTrue(app.staticTexts["Delete this library?"].waitForExistence(timeout: 4),
                      "The confirmation dialog should appear")
        app.buttons["Delete library"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts[name].waitForNonExistence(timeout: 6),
                      "The library should be gone after delete")
        createdStoreId = nil
        shot("06-library-deleted")

        // 4. Remaining destinations render
        go("Ask")
        XCTAssertTrue(app.staticTexts["What are you working on?"].waitForExistence(timeout: 6))
        shot("07-ask")

        go("Private")
        XCTAssertTrue(app.staticTexts["Private chats"].waitForExistence(timeout: 6))
        shot("08-private")

        go("Secret Images")
        XCTAssertTrue(app.staticTexts["Secret Images"].waitForExistence(timeout: 6))
        shot("09-secret")

        // 5. Settings sheet
        openMenu()
        app.buttons["Settings"].tap()
        XCTAssertTrue(app.staticTexts["Settings"].waitForExistence(timeout: 5))
        shot("10-settings")
    }

    // MARK: - UI helpers

    private func openMenu() {
        let button = app.buttons["Open menu"]
        XCTAssertTrue(button.waitForExistence(timeout: 10), "The floating menu button should exist")
        button.tap()
        // A synthetic tap right after a page settles can be swallowed; retry once before
        // giving up. "WORKSPACE" is the menu's first section label.
        if !app.staticTexts["WORKSPACE"].waitForExistence(timeout: 2) {
            button.tap()
        }
        XCTAssertTrue(app.staticTexts["WORKSPACE"].waitForExistence(timeout: 5),
                      "The side menu should open")
    }

    private func go(_ destination: String) {
        openMenu()
        let row = app.buttons[destination]
        XCTAssertTrue(row.waitForExistence(timeout: 5), "\(destination) should be in the menu")
        row.tap()
    }

    private func dismissSheet() {
        let sheet = app.sheets.firstMatch
        guard sheet.waitForExistence(timeout: 2) else { return }
        // Drag from the sheet's grabber zone to its bottom — a plain swipeDown lands on the
        // scroll content and rubber-bands instead of dismissing.
        let top = sheet.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.02))
        let bottom = sheet.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.95))
        top.press(forDuration: 0.1, thenDragTo: bottom)
        if !sheet.waitForNonExistence(timeout: 3) {
            sheet.swipeDown(velocity: .fast)
            _ = sheet.waitForNonExistence(timeout: 3)
        }
    }

    private func pullToRefresh() {
        let scrollView = app.scrollViews.firstMatch
        guard scrollView.waitForExistence(timeout: 3) else { return }
        let start = scrollView.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.2))
        let end = scrollView.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.85))
        start.press(forDuration: 0.1, thenDragTo: end)
        sleep(1)
    }

    private func shot(_ name: String) {
        let screenshot = app.windows.firstMatch.screenshot()
        let url = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("\(name).png")
        try? screenshot.pngRepresentation.write(to: url)
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    // MARK: - API helpers (same endpoints the app uses)

    private static let baseURL = "http://127.0.0.1:8000"

    /// Synchronous JSON request for the test process. Returns parsed JSON (or nil on 204).
    @discardableResult
    private static func apiRequest(_ method: String, path: String, body: Data? = nil,
                                   contentType: String? = nil) -> Any? {
        guard let url = URL(string: baseURL + path) else { return nil }
        var request = URLRequest(url: url, timeoutInterval: 30)
        request.httpMethod = method
        if let contentType { request.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        request.httpBody = body
        var result: Any?
        var requestError: Error?
        let semaphore = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: request) { data, _, error in
            requestError = error
            if let data, !data.isEmpty {
                result = try? JSONSerialization.jsonObject(with: data)
            }
            semaphore.signal()
        }.resume()
        _ = semaphore.wait(timeout: .now() + 35)
        if let requestError { XCTFail("API \(method) \(path) failed: \(requestError.localizedDescription)") }
        return result
    }

    private static func storeId(named name: String) throws -> Int {
        guard let stores = apiRequest("GET", path: "/api/collections") as? [[String: Any]] else {
            throw NSError(domain: "UITest", code: 1, userInfo: [NSLocalizedDescriptionKey: "Could not list collections"])
        }
        guard let match = stores.first(where: { $0["title"] as? String == name }),
              let id = match["id"] as? Int else {
            throw NSError(domain: "UITest", code: 2, userInfo: [NSLocalizedDescriptionKey: "Created library not found via API"])
        }
        return id
    }

    private static func uploadFile(storeId: Int, fileName: String, text: String) throws {
        let boundary = "UITestBoundary-\(UUID().uuidString)"
        var body = Data()
        body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"store_id\"\r\n\r\n\(storeId)\r\n".data(using: .utf8)!)
        body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(fileName)\"\r\nContent-Type: text/plain\r\n\r\n".data(using: .utf8)!)
        body.append(text.data(using: .utf8)!)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        guard let created = apiRequest("POST", path: "/api/files", body: body,
                                       contentType: "multipart/form-data; boundary=\(boundary)") as? [String: Any],
              created["id"] != nil else {
            throw NSError(domain: "UITest", code: 3, userInfo: [NSLocalizedDescriptionKey: "File upload failed"])
        }
    }
}

private extension XCUIElement {
    func waitForNonExistence(timeout: TimeInterval) -> Bool {
        let predicate = NSPredicate(format: "exists == false")
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: self)
        return XCTWaiter().wait(for: [expectation], timeout: timeout) == .completed
    }
}
