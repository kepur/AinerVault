// 台词再创作实测：端侧模型 vs PCC 云端模型 vs 系统高保真翻译
// 测试句是题材套话（自拟），不含用户素材
import Foundation
import FoundationModels
import Translation

let lines: [(id: String, zh: String, sec: Double)] = [
    ("L1", "三年之期已到，恭迎龙王归来！", 2.4),
    ("L2", "女人，你成功引起了我的注意。", 2.2),
    ("L3", "你一个上门女婿，也配坐主桌？", 2.0),
    ("L4", "他不过是炼气一层的废物，凭什么进内门？", 2.8),
    ("L5", "本宫倒要看看，这后宫到底谁说了算。", 2.6),
]

@Generable struct AdaptedLine {
    @Guide(description: "台词编号，原样返回") var id: String
    @Guide(description: "目标地区观众听起来自然的再创作台词，不是直译") var line: String
    @Guide(description: "这句台词的英文音节数估计") var syllables: Int
    @Guide(description: "做了哪些文化替换，一句话") var note: String
}

@Generable struct AdaptedBatch {
    var lines: [AdaptedLine]
}

func prompt(region: String) -> String {
    var s = "把下面的中文短剧台词再创作成\(region)观众的版本。要求：保留情绪和人物关系；套话换成当地观众熟悉的同类表达；"
    s += "每句配音必须在给定秒数内说完（英语约每秒 4 个音节、西语约每秒 5 个音节），宁短勿长。\n"
    for l in lines { s += "\(l.id)（\(l.sec) 秒）：\(l.zh)\n" }
    return s
}

func run(_ name: String, _ model: some LanguageModel, region: String) async {
    let session = LanguageModelSession(model: model, instructions: "你是资深的短剧本地化编剧。")
    let t0 = Date()
    do {
        let r = try await session.respond(to: prompt(region: region), generating: AdaptedBatch.self)
        let dt = Date().timeIntervalSince(t0)
        print(String(format: "--- %@ → %@  %.1f 秒", name, region, dt))
        for l in r.content.lines { print("  \(l.id) [\(l.syllables)音节] \(l.line)  ｜\(l.note)") }
    } catch {
        print("--- \(name) → \(region) 失败: \(error)")
    }
}

@main struct Adapt27 {
    static func main() async {
        for region in ["美国英语", "拉美西班牙语"] {
            await run("端侧 3B", SystemLanguageModel.default, region: region)
            await run("PCC 云端", PrivateCloudComputeLanguageModel(), region: region)
        }
        print("PCC 配额:", PrivateCloudComputeLanguageModel().quotaUsage)

        // 系统翻译高保真档：直译基线
        for target in ["en", "es"] {
            let session = TranslationSession(installedSource: Locale.Language(identifier: "zh-Hans"),
                                             target: Locale.Language(identifier: target),
                                             preferredStrategy: .highFidelity)
            let reqs = lines.map { TranslationSession.Request(sourceText: $0.zh, clientIdentifier: $0.id) }
            let t0 = Date()
            do {
                let res = try await session.translations(from: reqs)
                print(String(format: "--- 系统翻译 highFidelity → %@  %.2f 秒", target, Date().timeIntervalSince(t0)))
                for r in res { print("  \(r.clientIdentifier ?? "") \(r.targetText)") }
            } catch { print("--- 系统翻译 → \(target) 失败: \(error)") }
        }
    }
}
