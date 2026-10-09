import Foundation
import Speech
import Vision
import Translation
import FoundationModels

// 本机 Apple 原生框架能力探测：语音转写、文字识别、翻译、系统大模型各支持哪些语言
@main
struct Probe {
    static func main() async {
        // 1) SpeechAnalyzer / SpeechTranscriber（macOS 26 新的长音频转写）
        let st = await SpeechTranscriber.supportedLocales.map { $0.identifier(.bcp47) }.sorted()
        let installed = await SpeechTranscriber.installedLocales.map { $0.identifier(.bcp47) }.sorted()
        print("SpeechTranscriber supported (\(st.count)):", st.joined(separator: " "))
        print("SpeechTranscriber installed:", installed.joined(separator: " "))
        let dt = await DictationTranscriber.supportedLocales.map { $0.identifier(.bcp47) }.sorted()
        print("DictationTranscriber supported (\(dt.count)) has zh:", dt.filter { $0.hasPrefix("zh") || $0.hasPrefix("yue") }.joined(separator: " "))

        // 2) Vision 文字识别
        let req = RecognizeTextRequest()
        print("Vision OCR languages:", req.supportedRecognitionLanguages.map { $0.maximalIdentifier }.joined(separator: " "))

        // 3) Translation 框架：中文 → 各目标语言
        let avail = LanguageAvailability()
        let zh = Locale.Language(identifier: "zh-Hans")
        var pairs: [String] = []
        for t in ["en", "es", "pt", "fr", "de", "ja", "ko", "id", "th", "vi", "ar", "ru", "tr", "hi", "it"] {
            let s = await avail.status(from: zh, to: Locale.Language(identifier: t))
            let tag: String
            switch s {
            case .installed: tag = "installed"
            case .supported: tag = "supported"
            case .unsupported: tag = "no"
            @unknown default: tag = "?"
            }
            pairs.append("\(t):\(tag)")
        }
        print("Translation zh-Hans → ", pairs.joined(separator: " "))

        // 4) Foundation Models（系统内置约 3B 模型）
        let m = SystemLanguageModel.default
        print("FoundationModels availability:", m.availability)
        print("FoundationModels languages:", m.supportedLanguages.map { $0.maximalIdentifier }.sorted().joined(separator: " "))
    }
}
