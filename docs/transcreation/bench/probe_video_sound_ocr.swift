import AppKit
import CoreGraphics
import Foundation
import SoundAnalysis
import Vision
import VideoToolbox

// 本机 Apple 原生能力探测（二）：AI 超分／插帧可用性、内置声音分类、中文 OCR 速度
@main
struct Probe2 {
    static func main() async throws {
        // 1) VideoToolbox 帧处理（macOS 26）
        print("SuperResolution supported:", VTSuperResolutionScalerConfiguration.isSupported)
        if VTSuperResolutionScalerConfiguration.isSupported {
            print("  input max:", VTSuperResolutionScalerConfiguration.maximumDimensions,
                  "scale factors:", VTSuperResolutionScalerConfiguration.supportedScaleFactors)
            if let cfg = VTSuperResolutionScalerConfiguration(frameWidth: 854, frameHeight: 480, scaleFactor: 2,
                                                              inputType: .video, usePrecomputedFlow: false,
                                                              qualityPrioritization: .normal, revision: .revision1) {
                print("  480p×2 config ok, model status:", cfg.configurationModelStatus.rawValue)
            }
        }
        print("FrameRateConversion supported:", VTFrameRateConversionConfiguration.isSupported)
        print("LowLatencyFrameInterpolation supported:", VTLowLatencyFrameInterpolationConfiguration.isSupported)
        print("OpticalFlow supported:", VTOpticalFlowConfiguration.isSupported)

        // 2) SoundAnalysis 内置分类器
        let req = try SNClassifySoundRequest(classifierIdentifier: .version1)
        let labels = req.knownClassifications
        let pick = labels.filter { ["speech", "music", "singing", "laughter", "crying_sobbing", "shout", "gunshot_gunfire",
                                    "explosion", "applause", "whispering", "screaming"].contains($0) }
        print("SoundAnalysis labels:", labels.count, "e.g.", pick.joined(separator: " "))

        // 3) Vision 中文 OCR 速度：画一张 854×480 的「带字幕」画面，识别 20 次取平均
        let w = 854, h = 480
        let img = NSImage(size: NSSize(width: w, height: h))
        img.lockFocus()
        NSColor(calibratedRed: 0.15, green: 0.2, blue: 0.3, alpha: 1).setFill()
        NSRect(x: 0, y: 0, width: w, height: h).fill()
        let sub = "你竟敢囚禁我玄天仙帝！今天就让你见识一下。" as NSString
        let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 30, weight: .bold),
                                                    .foregroundColor: NSColor.white]
        sub.draw(at: NSPoint(x: 90, y: 40), withAttributes: attrs)
        ("江北第一人民医院" as NSString).draw(at: NSPoint(x: 560, y: 400),
                                       withAttributes: [.font: NSFont.systemFont(ofSize: 22), .foregroundColor: NSColor.yellow])
        img.unlockFocus()
        guard let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return }
        var ocr = RecognizeTextRequest()
        ocr.recognitionLanguages = [Locale.Language(identifier: "zh-Hans"), Locale.Language(identifier: "en-US")]
        ocr.recognitionLevel = .accurate
        var lines: [String] = []
        let t0 = Date()
        for i in 0..<20 {
            let obs = try await ocr.perform(on: cg)
            if i == 0 { lines = obs.compactMap { $0.topCandidates(1).first?.string } }
        }
        let per = Date().timeIntervalSince(t0) / 20
        print(String(format: "Vision OCR accurate: %.1f ms/frame →", per * 1000), lines)
        ocr.recognitionLevel = .fast
        let t1 = Date()
        for _ in 0..<20 { _ = try await ocr.perform(on: cg) }
        print(String(format: "Vision OCR fast: %.1f ms/frame", Date().timeIntervalSince(t1) / 20 * 1000))
    }
}
