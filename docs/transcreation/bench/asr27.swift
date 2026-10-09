// macOS 27 转写：视频文件直接喂给 SpeechAnalyzer（AssetInputSequenceProvider），带逐词置信度
import AVFoundation
import Foundation
import Speech

@main struct ASR27 {
    static func main() async throws {
        let url = URL(fileURLWithPath: CommandLine.arguments[1])
        let locale = Locale(identifier: CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : "zh-CN")
        let t0 = Date()
        let transcriber = SpeechTranscriber(locale: locale, transcriptionOptions: [], reportingOptions: [],
                                            attributeOptions: [.audioTimeRange, .transcriptionConfidence])
        let asset = AVURLAsset(url: url)
        let provider = try await AssetInputSequenceProvider.provider(from: asset, compatibleWith: [transcriber])
        let analyzer = SpeechAnalyzer(modules: [transcriber],
                                      options: .init(priority: .userInitiated, modelRetention: .processLifetime))
        let collect = Task { () -> [String] in
            var out: [String] = []
            for try await r in transcriber.results {
                var low: [String] = []
                for run in r.text.runs {
                    if let c = run.transcriptionConfidence, c < 0.5 {
                        low.append("\(String(r.text[run.range].characters))(\(String(format: "%.2f", c)))")
                    }
                }
                out.append(String(format: "[%6.2f→%6.2f] ", r.range.start.seconds, r.range.end.seconds)
                           + String(r.text.characters) + (low.isEmpty ? "" : "   低置信: " + low.joined(separator: " ")))
            }
            return out
        }
        let t1 = Date()
        if let last = try await analyzer.analyzeSequence(provider.analyzerInputs) {
            try await analyzer.finalizeAndFinish(through: last)
        } else {
            await analyzer.cancelAndFinishNow()
        }
        let segs = try await collect.value
        let t2 = Date()
        segs.forEach { print($0) }
        let dur = try await asset.load(.duration).seconds
        print(String(format: "视频 %.1f 秒｜准备 %.2f 秒｜转写 %.2f 秒（%.0f 倍速）｜%d 段",
                     dur, t1.timeIntervalSince(t0), t2.timeIntervalSince(t1), dur / t2.timeIntervalSince(t1), segs.count))
    }
}
