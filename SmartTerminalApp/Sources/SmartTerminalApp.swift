import SwiftUI
import WebKit
import KeyboardShortcuts
import LaunchAtLogin
import Foundation
import AppKit

@main
struct SmartTerminalApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    
    var body: some Scene {
        WindowGroup {
            ContentView()
                .frame(minWidth: 1200, minHeight: 800)
        }
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New Chat Session") {
                    NSApp.sendAction(Selector(("newChatSession:")), to: nil, from: nil)
                }
                .keyboardShortcut("n", modifiers: [.command, .shift])
            }
            
            CommandGroup(replacing: .appInfo) {
                Button("Check for Updates") {
                    // TODO: Implement update checking
                }
                .keyboardShortcut("u", modifiers: [.command, .shift])
            }
        }
    }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    var statusItem: NSStatusItem?
    var webServerProcess: Process?
    var setupComplete = false
    
    func applicationDidFinishLaunching(_ notification: Notification) {
        setupStatusBar()
        setupLocalDomain()
        startWebServer()
        setupLaunchAtLogin()
    }
    
    func applicationWillTerminate(_ notification: Notification) {
        stopWebServer()
    }
    
    func setupStatusBar() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        
        if let button = statusItem?.button {
            button.image = NSImage(systemSymbolName: "terminal.fill", accessibilityDescription: "Smart Terminal")
            button.action = #selector(statusBarClicked)
            button.target = self
        }
        
        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Open Smart Terminal", action: #selector(openMainWindow), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "Stop Server", action: #selector(stopServer), keyEquivalent: ""))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Launch at Login", action: #selector(toggleLaunchAtLogin), keyEquivalent: ""))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        
        statusItem?.menu = menu
    }
    
    @objc func statusBarClicked() {
        openMainWindow()
    }
    
    @objc func openMainWindow() {
        NSApp.activate(ignoringOtherApps: true)
        for window in NSApp.windows {
            window.makeKeyAndOrderFront(nil)
        }
    }
    
    @objc func stopServer() {
        stopWebServer()
    }
    
    @objc func toggleLaunchAtLogin() {
        LaunchAtLogin.isEnabled.toggle()
    }
    
    func setupLocalDomain() {
        let hostsPath = "/etc/hosts"
        let domainMapping = "127.0.0.1\tsmartterminal"
        
        do {
            let hosts = try String(contentsOfFile: hostsPath)
            if !hosts.contains(domainMapping) {
                let newContent = hosts + "\n# Smart Terminal Local Domain\n" + domainMapping + "\n"
                try newContent.write(toFile: hostsPath, atomically: false, encoding: .utf8)
                print("Added smartterminal domain to /etc/hosts")
            }
        } catch {
            print("Failed to setup local domain: \(error)")
            // Try with sudo
            let script = """
            echo '\n# Smart Terminal Local Domain\n127.0.0.1\tsmartterminal' | sudo tee -a /etc/hosts
            """
            executeShellCommand(script)
        }
    }
    
func startWebServer() {
        // Check if we're running from a bundle or in development
        let webResourcesPath: String
        if let resourcePath = Bundle.main.path(forResource: "web", ofType: nil) {
            // Running from app bundle
            webResourcesPath = resourcePath
        } else {
            // Running in development
            webResourcesPath = FileManager.default.currentDirectoryPath + "/.."
        }
        
        let webAppScript = "\(webResourcesPath)/web_app_macos.py"
        
        // Check if the modified web server exists, otherwise use the original
        let scriptPath = FileManager.default.fileExists(atPath: webAppScript) ? webAppScript : "\(webResourcesPath)/web_app.py"
        
        webServerProcess = Process()
        webServerProcess?.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        webServerProcess?.arguments = [scriptPath]
        webServerProcess?.currentDirectoryURL = URL(fileURLWithPath: webResourcesPath)
        
        // Set environment variables
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = webResourcesPath
        webServerProcess?.environment = env
        
        let pipe = Pipe()
        webServerProcess?.standardOutput = pipe
        webServerProcess?.standardError = pipe
        
        do {
            try webServerProcess?.run()
            print("Web server started successfully from: \(scriptPath)")
            
            // Monitor server output
            DispatchQueue.global().async {
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                if let output = String(data: data, encoding: .utf8) {
                    print("Server output: \(output)")
                }
            }
            
        } catch {
            print("Failed to start web server: \(error)")
            // Fallback: Try to run the original script
            let fallbackScript = "\(webResourcesPath)/start_web_ui.sh"
            if FileManager.default.fileExists(atPath: fallbackScript) {
                webServerProcess?.executableURL = URL(fileURLWithPath: "/bin/bash")
                webServerProcess?.arguments = [fallbackScript]
                webServerProcess?.currentDirectoryURL = URL(fileURLWithPath: webResourcesPath)
                try? webServerProcess?.run()
                print("Fallback server started")
            }
        }
    }
    
    func stopWebServer() {
        webServerProcess?.terminate()
        webServerProcess = nil
        print("Web server stopped")
    }
    
    func setupLaunchAtLogin() {
        // Enabled by default for better UX
        LaunchAtLogin.isEnabled = true
    }
    
    func executeShellCommand(_ command: String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = ["-c", command]
        
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            print("Failed to execute shell command: \(error)")
        }
    }
}

struct ContentView: View {
    @State private var isLoading = true
    @State private var serverReady = false
    
    var body: some View {
        VStack {
            if isLoading {
                VStack(spacing: 20) {
                    ProgressView()
                        .scaleEffect(1.5)
                    Text("Starting Smart Terminal...")
                        .font(.title2)
                        .foregroundColor(.secondary)
                    Text("Initializing web service...")
                        .font(.caption)
                        .foregroundColor(.tertiary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                WebViewWrapper(url: URL(string: "http://smartterminal:5001")!)
                    .onAppear {
                        checkServer()
                    }
            }
        }
        .onAppear {
            // Simulate startup time
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                isLoading = false
                serverReady = true
            }
        }
    }
    
    func checkServer() {
        // Verify server is responsive
        guard let url = URL(string: "http://127.0.0.1:5001/api/models") else { return }
        
        URLSession.shared.dataTask(with: url) { data, response, error in
            DispatchQueue.main.async {
                serverReady = error == nil
            }
        }.resume()
    }
}

struct WebViewWrapper: NSViewRepresentable {
    let url: URL
    
    func makeNSView(context: Context) -> WKWebView {
        let webConfig = WKWebViewConfiguration()
        webConfig.userContentController = WKUserContentController()
        
        // Enable developer extras
        webConfig.preferences.setValue(true, forKey: "developerExtrasEnabled")
        
        let webView = WKWebView(frame: .zero, configuration: webConfig)
        webView.navigationDelegate = context.coordinator
        
        // Custom user agent
        webView.customUserAgent = "SmartTerminal-macOS/1.0"
        
        return webView
    }
    
    func updateNSView(_ nsView: WKWebView, context: Context) {
        let request = URLRequest(url: url)
        nsView.load(request)
    }
    
    func makeCoordinator() -> Coordinator {
        Coordinator()
    }
    
    class Coordinator: NSObject, WKNavigationDelegate {
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            print("WebView navigation failed: \(error)")
        }
        
        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            print("WebView loaded successfully")
        }
    }
}