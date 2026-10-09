import AVFoundation
import Foundation
import Speech

// Apple 原生长音频转写（macOS 26 SpeechAnalyzer + SpeechTranscriber）测速：
// 用法：asr <音频文件> <语言，如 zh-CN>；输出每段的起止时间和文字，最后一行是 JSON 摘要
@main
struct ASR {
    static func main() async throws {
        let args = CommandLine.arguments
        let url = URL(fileURLWithPath: args[1])
        let locale = Locale(identifier: args.count > 2 ? args[2] : "zh-CN")
        let t0 = Date()
        let transcriber = SpeechTranscriber(locale: locale, transcriptionOptions: [], reportingOptions: [],
                                            attributeOptions: [.audioTimeRange])
        // 语言包没装就先装（第一次会下载）
        if let req = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
            try await req.downloadAndInstall()
        }
        let file = try AVAudioFile(forReading: url)
        let seconds = Double(file.length) / file.processingFormat.sampleRate
        let analyzer = SpeechAnalyzer(modules: [transcriber])
        let collect = Task { () -> [(Double, Double, String)] in
            var out: [(Double, Double, String)] = []
            for try await r in transcriber.results {
                let text = String(r.text.characters)
                out.append((r.range.start.seconds, r.range.end.seconds, text))
            }
            return out
        }
        let t1 = Date()
        if let last = try await analyzer.analyzeSequence(from: file) {
            try await analyzer.finalizeAndFinish(through: last)
        } else {
            await analyzer.cancelAndFinishNow()
        }
        let segs = try await collect.value
        let t2 = Date()
        for (s, e, text) in segs {
            print(String(format: "[%7.2f → %7.2f] ", s, e) + text)
        }
        let all = segs.map { $0.2 }.joined()
        let summary: [String: Any] = [
            "audio_s": seconds, "setup_s": t1.timeIntervalSince(t0), "transcribe_s": t2.timeIntervalSince(t1),
            "rtf": t2.timeIntervalSince(t1) / seconds, "segments": segs.count, "chars": all.count,
        ]
        let data = try JSONSerialization.data(withJSONObject: summary)
        print(String(data: data, encoding: .utf8)!)
        try all.write(toFile: url.deletingPathExtension().path + ".apple.txt", atomically: true, encoding: .utf8)
    }
}
