// macOS 27 能力探测：转译流水线相关的系统框架，本机实际可用性
import Foundation
import FoundationModels
import Speech
import Translation
import VideoToolbox

@main struct Probe27 {
    static func main() async {
        print("== FoundationModels")
        let sm = SystemLanguageModel.default
        print("端侧模型:", sm.availability, " contextSize:", sm.contextSize)
        let pcc = PrivateCloudComputeLanguageModel()
        print("PCC 云端模型:", pcc.availability)
        print("PCC 配额:", pcc.quotaUsage)
        if pcc.isAvailable {
            do {
                print("PCC contextSize:", try await pcc.contextSize)
                let langs = try await pcc.supportedLanguages
                print("PCC 语言:", langs.map { $0.maximalIdentifier }.sorted().joined(separator: " "))
            } catch { print("PCC 查询失败:", error) }
        }

        print("\n== Translation（zh-Hans → X）")
        let src = Locale.Language(identifier: "zh-Hans")
        let targets = ["en", "es", "pt", "fr", "de", "it", "ja", "ko", "id", "th", "vi", "ar", "tr", "ru", "hi", "pl", "nl", "ms", "fil"]
        for (name, strat) in [("lowLatency", TranslationSession.Strategy.lowLatency), ("highFidelity", .highFidelity)] {
            let la = LanguageAvailability(preferredStrategy: strat)
            var row: [String] = []
            for t in targets {
                let s = await la.status(from: src, to: Locale.Language(identifier: t))
                let tag: String
                switch s {
                case .installed: tag = "已装"
                case .supported: tag = "可下"
                case .unsupported: tag = "×"
                @unknown default: tag = "?"
                }
                row.append("\(t)=\(tag)")
            }
            print(name + ":", row.joined(separator: " "))
        }

        print("\n== Speech")
        let installed = await SpeechTranscriber.installedLocales.map { $0.identifier }.sorted()
        print("SpeechTranscriber 已装:", installed.joined(separator: " "))
        let supported = await SpeechTranscriber.supportedLocales.map { $0.identifier }
        print("SpeechTranscriber 支持数:", supported.count)

        print("\n== VideoToolbox 超分")
        print("SuperResolution supported:", VTSuperResolutionScalerConfiguration.isSupported)
        print("LowLatency SR supported:", VTLowLatencySuperResolutionScalerConfiguration.isSupported,
              " 倍数:", VTLowLatencySuperResolutionScalerConfiguration.supportedScaleFactors)
        print("LowLatency 854x480 可用倍数:",
              VTLowLatencySuperResolutionScalerConfiguration.supportedScaleFactors(frameWidth: 854, frameHeight: 480))
    }
}
