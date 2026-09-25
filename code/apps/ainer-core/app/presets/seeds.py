"""预设种子数据。

每条 = key（同一 kind 下唯一、稳定）＋名字＋分类＋payload。启动后第一次查询时补齐缺的，
已有的按种子刷新 payload（官方预设以代码为准），用户的收藏、使用次数不动。
提示词片段一律英文（图像/视频模型不认中文），界面显示中文名。
"""
from __future__ import annotations

from typing import Any

# ── 风格广场 ──────────────────────────────────────────────
# render：交给工作台的基础画风（photoreal / anime / cinematic / auto）；prompt：追加在画面提示词末尾
STYLE_CATEGORIES = ["摄影写真", "电商营销", "动漫游戏", "风格插画", "平面设计", "建筑及室内设计", "创意玩法", "文创周边", "小说推文"]

_S = [
    # 摄影写真
    ("film_portrait", "胶片人像", "摄影写真", "photoreal", "35mm film photography, Kodak Portra 400 color palette, soft natural light, gentle film grain, shallow depth of field", "a young woman by a window"),
    ("street_snap", "街头纪实", "摄影写真", "photoreal", "candid street photography, documentary style, available light, 28mm lens, slight motion, authentic moment", "a busy night market street"),
    ("studio_fashion", "棚拍时尚", "摄影写真", "photoreal", "high-end fashion editorial, studio strobe lighting, seamless backdrop, crisp detail, magazine cover quality", "a model in a tailored coat"),
    ("garage_goddess", "车库女神", "摄影写真", "photoreal", "moody underground parking garage, fluorescent top light, glossy car reflections, fashion portrait", "a woman leaning on a red sports car"),
    ("golden_hour", "黄金时刻", "摄影写真", "photoreal", "golden hour backlight, warm rim light, lens flare, dreamy haze, outdoor portrait", "a couple walking in a wheat field"),
    ("hyperreal_portrait", "超写实质感人像", "摄影写真", "photoreal", "hyper-realistic portrait, detailed skin texture and pores, cinematic key light, 85mm, ultra sharp eyes", "an ancient Chinese swordsman close-up"),
    # 电商营销
    ("product_hero", "产品主图", "电商营销", "photoreal", "clean e-commerce product shot, soft gradient backdrop, studio lighting, subtle reflection, centered composition", "a pair of wireless earbuds"),
    ("cosmetics_splash", "美妆水花", "电商营销", "photoreal", "cosmetics advertising, liquid splash frozen in time, glossy highlights, pastel background", "a perfume bottle"),
    ("food_menu", "美食菜单", "电商营销", "photoreal", "appetizing food photography, top-down flat lay, warm light, fresh ingredients, steam", "a bowl of beef noodles"),
    ("poster_sale", "大促海报", "电商营销", "auto", "bold promotional poster design, vibrant colors, dynamic composition, confetti, high contrast", "a shopping festival banner"),
    # 动漫游戏
    ("anime_cel", "日系动画", "动漫游戏", "anime", "Japanese anime key visual, clean cel shading, vivid colors, detailed background art", "a high school girl on a rooftop"),
    ("ghibli_like", "手绘温暖动画", "动漫游戏", "anime", "hand-painted warm animation style, soft watercolor backgrounds, gentle light, whimsical countryside", "a boy riding a bicycle through fields"),
    ("guofeng_anime", "国风动漫", "动漫游戏", "anime", "Chinese guofeng anime style, flowing hanfu, ink wash accents, elegant line art, jade and vermilion palette", "a fairy standing on a pavilion roof"),
    ("game_cg", "游戏 CG", "动漫游戏", "cinematic", "AAA game cinematic CG, dramatic lighting, volumetric fog, highly detailed armor and environment", "a knight facing a dragon"),
    ("chibi", "Q版萌系", "动漫游戏", "anime", "cute chibi style, big head small body, pastel colors, soft outlines, sticker-like", "a cat girl eating ice cream"),
    ("cyberpunk", "赛博朋克", "动漫游戏", "cinematic", "cyberpunk city, neon signs, rain-soaked streets, magenta and cyan lighting, holograms", "a hacker in a neon alley"),
    # 风格插画
    ("ink_wash", "水墨", "风格插画", "auto", "traditional Chinese ink wash painting, xuan paper texture, expressive brush strokes, generous negative space", "misty mountains and a lone boat"),
    ("gongbi", "工笔重彩", "风格插画", "auto", "Chinese gongbi meticulous painting, fine outlines, rich mineral colors, silk texture", "a court lady with peonies"),
    ("watercolor", "水彩", "风格插画", "auto", "loose watercolor illustration, soft bleeding edges, paper grain, fresh light palette", "a canal town in spring"),
    ("oil_painting", "古典油画", "风格插画", "auto", "classical oil painting, chiaroscuro, visible brushwork, Rembrandt lighting, rich warm tones", "an old scholar reading by candlelight"),
    ("flat_vector", "扁平插画", "风格插画", "auto", "flat vector illustration, geometric shapes, limited palette, clean shapes, no gradients", "a city skyline"),
    ("picture_book", "绘本", "风格插画", "auto", "children's picture book illustration, crayon and gouache texture, friendly shapes, warm colors", "a bear in a forest"),
    ("xuanguang", "破界·玄光", "风格插画", "cinematic", "ethereal xianxia fantasy art, glowing spiritual energy, flowing white robes, luminous particles, ice-blue palette", "a female immortal holding a glowing orb"),
    # 平面设计
    ("swiss_poster", "瑞士海报", "平面设计", "auto", "Swiss international style poster, grid layout, bold sans-serif typography, strong contrast", "a jazz festival poster"),
    ("brand_kv", "品牌主视觉", "平面设计", "auto", "brand key visual, minimal layout, premium feel, soft shadows, generous whitespace", "a tea brand key visual"),
    ("isometric", "等距 3D", "平面设计", "auto", "isometric 3D illustration, soft clay render, pastel colors, cute miniature world", "a tiny coffee shop"),
    ("papercut", "剪纸", "平面设计", "auto", "layered paper cut art, depth shadows between layers, festive red, Chinese papercut motifs", "a lunar new year scene"),
    # 建筑及室内设计
    ("arch_render", "建筑效果图", "建筑及室内设计", "photoreal", "architectural visualization, photoreal render, golden hour, landscaped foreground, wide angle", "a modern museum by a lake"),
    ("interior_warm", "温馨室内", "建筑及室内设计", "photoreal", "interior design photography, warm natural light, wood and linen, cozy minimalism", "a living room with a reading nook"),
    ("song_courtyard", "宋式庭院", "建筑及室内设计", "photoreal", "Song dynasty courtyard, grey tiles, moon gate, bamboo, misty morning, serene", "a courtyard with a koi pond"),
    # 创意玩法
    ("miniature", "微缩景观", "创意玩法", "photoreal", "tilt-shift miniature photography, toy-like scale, shallow focus, saturated colors", "a busy train station"),
    ("claymation", "黏土动画", "创意玩法", "auto", "claymation stop-motion look, plasticine textures, fingerprints, handmade props", "a chef cooking dumplings"),
    ("double_exposure", "双重曝光", "创意玩法", "auto", "double exposure art, silhouette filled with landscape, monochrome with a color accent", "a wolf and a pine forest"),
    ("pixel_art", "像素风", "创意玩法", "auto", "16-bit pixel art, limited palette, crisp pixels, retro game scene", "a hero in a dungeon"),
    # 文创周边
    ("sticker", "贴纸", "文创周边", "anime", "die-cut sticker design, thick white border, bold outlines, cute and simple", "a panda holding bamboo"),
    ("blind_box", "盲盒手办", "文创周边", "auto", "designer toy blind box figure, glossy vinyl, soft studio light, pastel backdrop", "a little astronaut"),
    ("postcard", "城市明信片", "文创周边", "auto", "vintage travel postcard illustration, retro print texture, bold landmark, title lettering", "West Lake Hangzhou"),
    # 小说推文
    ("novel_cover_ancient", "古风女生手绘小说封面", "小说推文", "anime", "hand-drawn Chinese romance novel cover, delicate girl in hanfu, flowers and petals, soft pastel light", "a heroine under plum blossoms"),
    ("novel_xianxia", "仙侠封面", "小说推文", "cinematic", "epic xianxia novel cover, swordsman on a cliff, sea of clouds, dramatic sky, glowing sword", "a swordsman above the clouds"),
    ("novel_urban", "都市爽文", "小说推文", "photoreal", "urban webnovel thumbnail, confident young man in a suit, city night bokeh, bold dramatic lighting", "a CEO in a skyscraper office"),
    ("novel_suspense", "悬疑怪谈", "小说推文", "cinematic", "eerie suspense atmosphere, dim corridor, cold green light, film noir shadows, unsettling stillness", "an empty hospital hallway at night"),
    ("novel_apocalypse", "末世废土", "小说推文", "cinematic", "post-apocalyptic wasteland, ruined city, dust storm, orange sky, survivor silhouette", "a survivor on a broken highway"),
    ("ink_anime_qwen", "水墨古风动画", "小说推文", "anime", "ink-wash animation style, bold brush outlines, muted earth tones, candlelight, ancient scholar", "a scholar writing by candlelight"),
]


def style_seeds() -> list[dict[str, Any]]:
    return [{"key": k, "name": n, "category": c, "sort": i,
             "payload": {"render": r, "prompt": p, "cover": cov,
                         "negative": "blurry, lowres, watermark, text artifacts, extra fingers"}}
            for i, (k, n, c, r, p, cov) in enumerate(_S)]


# ── 爆款题材（剧本设定器）───────────────────────────────────
GENRE_FIELDS = ["题材", "目标受众", "角色设定", "时代背景", "核心看点", "画风", "剧本结构"]

_G = [
    ("xianxia_rise", "玄幻修仙逆袭", {"题材": "玄幻修仙", "目标受众": "男频 18–35", "角色设定": "被宗门逐出的废柴少年，意外得到上古传承",
     "时代背景": "架空修仙大陆", "核心看点": "逆袭打脸、境界突破、宗门大比", "画风": "仙侠电影感", "剧本结构": "20 集"}),
    ("workplace", "现实职场成长", {"题材": "都市现实", "目标受众": "女频 22–40", "角色设定": "普通家庭出身的新人，在大厂一路成长",
     "时代背景": "当代一线城市", "核心看点": "职场博弈、成长逆袭、情感线", "画风": "写实电影感", "剧本结构": "20 集"}),
    ("apocalypse_base", "末世生存基建", {"题材": "末世", "目标受众": "男频 18–35", "角色设定": "重生回末日前三天、囤满物资的主角",
     "时代背景": "近未来末日", "核心看点": "基建经营、生存危机、势力对抗", "画风": "废土写实", "剧本结构": "24 集"}),
    ("heritage_guochao", "非遗国潮视觉", {"题材": "文旅非遗", "目标受众": "全年龄", "角色设定": "传承老手艺的年轻人",
     "时代背景": "当代小城", "核心看点": "手艺之美、代际和解、国潮视觉", "画风": "国风写实", "剧本结构": "12 集"}),
    ("ancient_sweet", "古代女频甜宠", {"题材": "古装言情", "目标受众": "女频 18–30", "角色设定": "将军府庶女与冷面王爷",
     "时代背景": "架空古代王朝", "核心看点": "甜宠、先婚后爱、宅斗", "画风": "古风唯美", "剧本结构": "30 集"}),
    ("rule_horror", "规则怪谈悬疑", {"题材": "悬疑怪谈", "目标受众": "18–35", "角色设定": "误入诡异公寓的普通上班族",
     "时代背景": "当代都市", "核心看点": "规则解谜、反转、心理恐怖", "画风": "冷色悬疑", "剧本结构": "16 集"}),
    ("rebirth_revenge", "重生复仇爽剧", {"题材": "都市重生", "目标受众": "女频 20–40", "角色设定": "被害死后重生回十八岁的千金",
     "时代背景": "当代都市", "核心看点": "复仇打脸、步步为营、爽点密集", "画风": "都市精致", "剧本结构": "30 集"}),
    ("sect_pet", "仙门团宠日常", {"题材": "仙侠日常", "目标受众": "女频 16–30", "角色设定": "被整个仙门宠着的小师妹",
     "时代背景": "架空仙门", "核心看点": "团宠、轻喜剧、治愈", "画风": "仙侠唯美", "剧本结构": "20 集"}),
]


def genre_seeds() -> list[dict[str, Any]]:
    return [{"key": k, "name": n, "category": "爆款预设", "sort": i,
             "payload": {"fields": f, "prefill": f"我想创作一部「{n}」题材的短剧：" + "；".join(f"{a}：{b}" for a, b in f.items())}}
            for i, (k, n, f) in enumerate(_G)]


# ── 运镜广场（视频节点用的运镜提示词）─────────────────────────
_M = [
    ("static", "固定镜头", "基础", "Static locked-off camera, no camera movement."),
    ("push_in", "镜头前推", "推拉", "The camera slowly pushes in toward the subject."),
    ("pull_out", "镜头后移", "推拉", "The camera slowly pulls back, revealing more of the surroundings."),
    ("zoom_in", "变焦推进", "推拉", "The camera zooms in smoothly without moving."),
    ("zoom_out", "变焦拉远", "推拉", "The camera zooms out smoothly without moving."),
    ("dolly_zoom", "柯克变焦", "推拉", "Dolly zoom (vertigo effect): the subject stays the same size while the background stretches away."),
    ("pan_left", "镜头左摇", "摇", "The camera pans left from a fixed position."),
    ("pan_right", "镜头右摇", "摇", "The camera pans right from a fixed position."),
    ("tilt_up", "镜头上摇", "摇", "The camera tilts up from a fixed position."),
    ("tilt_down", "镜头下摇", "摇", "The camera tilts down from a fixed position."),
    ("truck_left", "镜头左移", "移", "The camera trucks left on a dolly, keeping the same distance."),
    ("truck_right", "镜头右移", "移", "The camera trucks right on a dolly, keeping the same distance."),
    ("pedestal_up", "镜头上升", "移", "The camera rises straight up."),
    ("pedestal_down", "镜头下降", "移", "The camera lowers straight down."),
    ("follow", "跟随拍摄", "跟拍", "The camera follows the subject from behind at a steady distance."),
    ("orbit", "环绕拍摄", "环绕", "The camera orbits around the subject in a smooth arc."),
    ("spiral_up", "盘旋抬升", "环绕", "The camera spirals upward around the subject, rising and pulling away."),
    ("spiral_down", "盘旋下降", "环绕", "The camera spirals downward around the subject, descending and moving closer."),
    ("roll", "滚筒旋转", "特殊", "The camera rolls a full 360 degrees around the lens axis."),
    ("first_person", "第一视角", "特殊", "First-person POV shot from the character's eyes, handheld feel."),
    ("drone", "无人机", "航拍", "FPV drone shot flying fast through the scene, sweeping past the subject."),
    ("aerial_high", "高空航拍", "航拍", "High-altitude aerial shot looking straight down, slowly rising."),
    ("handheld", "手持拍摄", "特殊", "Handheld camera with subtle natural shake."),
]


def camera_seeds() -> list[dict[str, Any]]:
    return [{"key": k, "name": n, "category": c, "sort": i, "payload": {"prompt": p, "preset": k}}
            for i, (k, n, c, p) in enumerate(_M)]


# ── 特效广场（视频提示词模板）───────────────────────────────────
_E = [
    ("bee_fpv", "小蜜蜂运镜", "An FPV micro-drone flies like a bee through the room, weaving between objects at high speed, extreme close passes."),
    ("through_clouds", "穿云而入", "The camera dives down through thick clouds and emerges above a city, continuous motion."),
    ("over_horizon", "飞跃地平线", "The camera skims low over the surface and rises over the horizon at sunrise."),
    ("reverse_gravity", "逆转引力", "Gravity reverses: people and objects slowly float upward while the camera rotates 180 degrees."),
    ("earth_zoom", "地球缩放", "A continuous zoom out from street level through the city and atmosphere to a view of Earth from space."),
    ("world_zoom", "环球缩放", "A continuous zoom from space down through the clouds to the subject on the street."),
    ("eye_zoom", "瞳孔推镜", "Extreme macro push into the subject's eye; the iris opens into a new scene."),
    ("dive_earth", "俯冲地球", "The camera dives from the sky straight down toward the subject at high speed."),
    ("product_sweep", "产品扫光", "A glossy light sweep glides across the product surface, slow rotation, black background."),
    ("outfit_swap", "换装", "Rapid outfit changes on beat, each cut the same pose in a new outfit, fashion editorial."),
    ("multi_angle", "多角度定点", "The same frozen moment shown from multiple angles in quick succession, bullet-time feel."),
    ("underwater_slowmo", "水下慢镜头", "Underwater slow motion, bubbles rising, light rays through the water surface."),
]


def effect_seeds() -> list[dict[str, Any]]:
    return [{"key": k, "name": n, "category": "推荐", "sort": i, "payload": {"prompt": p}} for i, (k, n, p) in enumerate(_E)]


# ── 造型室：发型、服装、表情 ─────────────────────────────────────
HAIR_ERAS = ["现代", "古风", "民国", "仙侠", "科幻", "民族", "儿童"]
_H = [
    ("现代", "long_straight", "长直发", "long straight black hair"), ("现代", "wavy", "大波浪", "long wavy curls"),
    ("现代", "bob", "齐耳短发", "chin-length bob haircut"), ("现代", "ponytail", "高马尾", "high ponytail"),
    ("现代", "bun", "丸子头", "messy top bun"), ("现代", "crew", "寸头", "short crew cut"),
    ("现代", "slick", "背头", "slicked-back hair"), ("现代", "wolf", "狼尾", "wolf cut mullet"),
    ("古风", "chuifa", "垂发", "long loose hair draped down the back, ancient Chinese style"),
    ("古风", "gaoji", "高髻", "tall ancient Chinese high bun with a hairpin"),
    ("古风", "shuanghuan", "双环髻", "double-loop ancient Chinese buns on both sides"),
    ("古风", "feixian", "飞仙髻", "flying-immortal updo with upswept loops"),
    ("古风", "lingshe", "灵蛇髻", "coiled serpent-shaped ancient updo"),
    ("古风", "nvguan", "女冠道髻", "Taoist nun topknot with a small crown"),
    ("古风", "banshu", "半束", "half-up half-down with a ribbon, ancient style"),
    ("古风", "huaguan", "花冠", "hair adorned with a flower crown and ornaments"),
    ("古风", "duoma", "堕马髻", "side-tilted falling-horse bun"),
    ("民国", "finger_wave", "手推波", "1920s finger waves"), ("民国", "short_bob", "学生短发", "1930s student bob with bangs"),
    ("民国", "pomade", "油头", "neatly parted pomade hair"),
    ("仙侠", "jade_crown", "玉冠束发", "hair tied up with a jade crown, long strands flowing"),
    ("仙侠", "silver_long", "银发长发", "long flowing silver-white hair"),
    ("科幻", "silver_buzz", "银色短发", "silver buzz cut"), ("科幻", "neon_streak", "霓虹挑染", "black hair with neon cyan streaks"),
    ("民族", "miao_silver", "苗银发饰", "Miao silver headdress with hanging ornaments"),
    ("民族", "tibetan_braids", "藏式编发", "many thin Tibetan braids with turquoise beads"),
    ("儿童", "pigtails", "羊角辫", "two short pigtails"), ("儿童", "bowl", "西瓜头", "bowl cut"),
]


def hairstyle_seeds() -> list[dict[str, Any]]:
    return [{"key": k, "name": n, "category": era, "sort": i, "payload": {"prompt": p}} for i, (era, k, n, p) in enumerate(_H)]


_O = [
    ("现代", "casual", "休闲卫衣", "oversized light blue sweatshirt and white wide-leg pants, white sneakers"),
    ("现代", "suit", "西装", "tailored charcoal suit with a white shirt"),
    ("现代", "uniform", "校服", "school uniform with a blazer and pleated skirt"),
    ("现代", "sport", "运动装", "athletic tracksuit"),
    ("古风", "ruqun", "齐胸襦裙", "Tang-style high-waisted ruqun dress in pastel silk"),
    ("古风", "jiaoling", "交领汉服", "cross-collar hanfu robe with wide sleeves"),
    ("古风", "wuxia", "武侠劲装", "martial arts outfit with bracers and a sash"),
    ("仙侠", "white_robe", "仙侠白衣", "flowing white immortal robes with silver embroidery"),
    ("民国", "qipao", "旗袍", "fitted 1930s qipao with a floral pattern"),
    ("民国", "changshan", "长衫", "long scholar's changshan robe"),
    ("科幻", "cyber_jacket", "赛博夹克", "techwear jacket with glowing trims"),
    ("民族", "miao_dress", "苗族盛装", "embroidered Miao festival dress with silver"),
]


def outfit_seeds() -> list[dict[str, Any]]:
    return [{"key": k, "name": n, "category": era, "sort": i, "payload": {"prompt": p}} for i, (era, k, n, p) in enumerate(_O)]


EXPRESSIONS = [
    ("neutral", "平静", "calm neutral expression"), ("smile", "微笑", "gentle smile"), ("laugh", "大笑", "laughing with open mouth"),
    ("angry", "生气", "angry frowning expression"), ("sad", "悲伤", "sad teary eyes"), ("surprised", "惊讶", "surprised wide eyes, open mouth"),
    ("fear", "害怕", "frightened expression"), ("disgust", "嫌弃", "disgusted expression"), ("determined", "坚定", "determined steely gaze"),
]


def expression_seeds() -> list[dict[str, Any]]:
    return [{"key": k, "name": n, "category": "表情", "sort": i, "payload": {"prompt": p}} for i, (k, n, p) in enumerate(EXPRESSIONS)]


# ── 官方角色库 ────────────────────────────────────────────────
_C = [
    ("sweet_girl", "甜妹/清新少女", {"gender": "女", "age": "青年", "culture": "东亚", "era": "现代"},
     "a sweet young East Asian woman, long black hair, bright smile, oversized light blue sweatshirt, white wide-leg pants, white sneakers"),
    ("ceo", "霸道总裁", {"gender": "男", "age": "青年", "culture": "东亚", "era": "现代"},
     "a handsome confident East Asian man, short black hair, sharp features, tailored charcoal suit, wristwatch"),
    ("young_swordsman", "少年侠客", {"gender": "男", "age": "少年", "culture": "东亚", "era": "古风"},
     "a spirited teenage swordsman, high ponytail, black and red martial arts outfit, sword on his back"),
    ("immortal_master", "仙门师尊", {"gender": "男", "age": "青年", "culture": "东亚", "era": "仙侠"},
     "a serene immortal master, long silver-white hair with a jade crown, flowing white robes with silver embroidery"),
    ("office_elite", "职场精英", {"gender": "女", "age": "青年", "culture": "东亚", "era": "现代"},
     "a sharp professional woman, shoulder-length bob, cream blazer and trousers, holding a tablet"),
    ("grandma", "慈祥奶奶", {"gender": "女", "age": "老年", "culture": "东亚", "era": "现代"},
     "a kind elderly grandmother, grey hair in a bun, knitted cardigan, warm smile"),
    ("little_boy", "小男孩", {"gender": "男", "age": "儿童", "culture": "东亚", "era": "现代"},
     "a cheerful little boy, bowl cut, yellow raincoat, red rain boots"),
    ("villain_boss", "反派枭雄", {"gender": "男", "age": "中年", "culture": "东亚", "era": "现代"},
     "a menacing middle-aged crime boss, slicked-back hair, scar on the cheek, black overcoat"),
    ("republic_girl", "民国少女", {"gender": "女", "age": "青年", "culture": "东亚", "era": "民国"},
     "a 1930s Shanghai young lady, finger-wave hairstyle, floral qipao, pearl earrings"),
    ("cyber_runner", "赛博猎手", {"gender": "女", "age": "青年", "culture": "混合", "era": "科幻"},
     "a cyberpunk bounty hunter, silver buzz cut, techwear jacket with glowing trims, cybernetic arm"),
    ("scholar", "古风书生", {"gender": "男", "age": "青年", "culture": "东亚", "era": "古风"},
     "a gentle ancient scholar, hair tied with a ribbon, pale blue scholar's robe, holding a folding fan"),
    ("swordswoman", "江湖女侠", {"gender": "女", "age": "青年", "culture": "东亚", "era": "古风"},
     "a fierce wandering swordswoman, high bun with a silver pin, dark red martial arts outfit, cloak"),
    ("western_knight", "西方骑士", {"gender": "男", "age": "青年", "culture": "欧美", "era": "中世纪"},
     "a young European knight, short blond hair, polished steel plate armor, blue cape"),
]


def character_seeds() -> list[dict[str, Any]]:
    return [{"key": k, "name": n, "category": tags["era"], "sort": i, "tags": list(tags.values()),
             "payload": {"tags": tags, "look": look, "views": {}}}
            for i, (k, n, tags, look) in enumerate(_C)]


SEEDS = {
    "style": style_seeds, "genre": genre_seeds, "camera_move": camera_seeds, "effect": effect_seeds,
    "hairstyle": hairstyle_seeds, "outfit": outfit_seeds, "expression": expression_seeds, "character": character_seeds,
}
