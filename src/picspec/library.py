"""A library of ready-made rules, grouped by what people ask of generated images.

The categories come from a survey of user complaints, tutorials and the dimensions
used in image-preference research. Each entry is an ordinary rule: copy it into a
spec and edit it freely.

``status`` says how far the yes/no question can be trusted when a vision model
answers it:

* ``verified``  the judge followed synthetic changes to this property in a live audit
* ``weak``      the judge failed such an audit
* ``untested``  nobody has measured it yet
"""

from __future__ import annotations

from dataclasses import dataclass

from .spec import Category, Ref, Rule, Spec

CATEGORIES: dict[str, tuple[str, str]] = {
    "realism": ("Realism and texture", "真实感与质感"),
    "expression": ("Expression and presence", "表情与神态"),
    "anatomy": ("Structure and physical defects", "结构与细节缺陷"),
    "text": ("Text in the image", "画面文字"),
    "camera": ("Light, composition and lens", "光线、构图与镜头"),
    "style": ("Style and tone", "风格与色调"),
    "consistency": ("Consistency with a reference image", "与参考图保持一致"),
}
STATUSES: dict[str, tuple[str, str]] = {
    "verified": ("judge verified", "判官已验证"),
    "weak": ("judge unreliable", "判官不可靠"),
    "untested": ("untested", "未测"),
}
SECTIONS: dict[str, tuple[str, str]] = {
    "texture": ("Image look", "画面质感"),
    "composition": ("Subject and composition", "主体与构图"),
    "forbid": ("Avoid", "禁忌"),
}

_PERSON = ("a person is in the image", "画面中有人物")
_FACE = ("a face is clearly visible", "能看清人物的脸")
_HANDS = ("hands are visible", "画面中能看到手")
_HAS_TEXT = ("the image contains text", "画面中有文字")
_NONE = ("", "")


@dataclass(frozen=True)
class Entry:
    id: str
    category: str
    kind: str
    text: tuple[str, str]
    check: tuple[str, str]
    expect: bool = True
    level: str = "must"
    when: tuple[str, str] = _NONE
    status: str = "untested"
    note: tuple[str, str] = _NONE
    ref: tuple[str, str, str] | None = None  # path, then the note in English and Chinese
    measure: str = ""

    def rule(self, lang: str = "en") -> Rule:
        i = 1 if lang == "zh" else 0
        refs = [Ref(self.ref[0], self.ref[1 + i])] if self.ref else []
        return Rule(id=self.id, text=self.text[i], kind=self.kind, check=self.check[i], expect=self.expect,
                    level=self.level, when=self.when[i], refs=refs, measure=self.measure)


def _e(id: str, category: str, kind: str, text: tuple[str, str], check: tuple[str, str], **kw) -> Entry:
    return Entry(id, category, kind, text, check, expect=kind != "forbid", **kw)


ENTRIES: tuple[Entry, ...] = (
    # --- realism -------------------------------------------------------------------------
    _e("film-grain", "realism", "texture",
       ("Light film grain across the whole frame, no digital smoothness", "全画面带轻微的胶片颗粒，没有数码的平滑感"),
       ("Is fine, even grain visible in the image?", "画面里是否能看到均匀的细颗粒？"),
       status="verified",
       note=("The judge notices grain weaker than a person sees at normal size.",
             "判官能察觉的颗粒比人在正常大小下看得出的更弱。")),
    _e("skin-texture", "realism", "texture",
       ("Skin keeps its natural texture: visible pores and small imperfections", "皮肤保留自然纹理，能看到毛孔和细小瑕疵"),
       ("Can you see pores or fine texture on the skin?", "皮肤上是否能看到毛孔或细微纹理？"), when=_FACE,
       status="weak",
       note=("On whole 1024x1536 images the judge answered no every time, smoothed or not: the face is too small "
             "for it to see pores.",
             "对 1024x1536 的整图，不管有没有磨皮判官都答“否”：脸在图里太小，它看不到毛孔。")),
    _e("loose-hair", "realism", "texture",
       ("Hair has loose strands and flyaways, not a perfectly neat outline", "头发有散落的碎发，轮廓不是一丝不乱"),
       ("Are loose strands or flyaway hairs visible?", "是否能看到散落的碎发？"), level="should", when=_PERSON),
    _e("lived-in", "realism", "texture",
       ("The scene looks lived-in: small wear, clutter or dust, not spotless", "场景有生活痕迹：轻微磨损、杂物或灰尘，不是一尘不染"),
       ("Does the scene show everyday wear or clutter rather than looking spotless?", "场景是否有日常的磨损或杂物，而不是一尘不染？"),
       level="should"),
    _e("plastic-skin", "realism", "forbid",
       ("Over-retouched, plastic-looking skin", "过度磨皮、塑料感的皮肤"),
       ("Does the skin look over-retouched or plastic?", "皮肤是否显得过度磨皮或有塑料感？"), when=_PERSON,
       status="weak",
       note=("In the audit the judge missed 7 of 14 smoothed images, though that probe also blurred the whole frame.",
             "审计里 14 张被抹平的图判官漏了 7 张，不过那个探针同时把整张图抹糊了。")),
    _e("oversaturated", "realism", "forbid",
       ("Oversaturated, unnaturally vivid colours", "过度饱和、鲜艳得不自然的颜色"),
       ("Do the colours look oversaturated or unnaturally vivid?", "颜色是否过度饱和或鲜艳得不自然？")),
    _e("hdr-halo", "realism", "forbid",
       ("An over-sharpened or HDR look with halos along edges", "过度锐化或 HDR 感，边缘有光晕"),
       ("Does the image look over-sharpened, with halos along edges?", "画面是否显得过度锐化、边缘有光晕？")),
    # --- expression ----------------------------------------------------------------------
    _e("natural-expression", "expression", "composition",
       ("A relaxed, natural expression, as if caught between poses", "表情放松自然，像是抓拍到的瞬间"),
       ("Does the person's expression look relaxed and unposed?", "人物的表情是否放松、不像摆拍？"), when=_FACE),
    _e("eye-catchlight", "expression", "texture",
       ("Eyes look alive, with a small highlight in each", "眼睛有神，眼中有一点高光"),
       ("Is there a visible highlight in the person's eyes?", "人物的眼睛里是否能看到高光？"), when=_FACE),
    _e("looks-away", "expression", "composition",
       ("The person looks away from the camera", "人物的视线不看镜头"),
       ("Is the person looking away from the camera?", "人物的视线是否没有看向镜头？"), level="should", when=_FACE),
    _e("neutral-expression", "expression", "composition",
       ("A neutral expression, mouth closed", "表情中性，嘴巴闭合"),
       ("Is the person's expression neutral, with the mouth closed?", "人物的表情是否中性、嘴巴闭合？"),
       level="should", when=_FACE),
    _e("staged-smile", "expression", "forbid",
       ("A stiff, posed smile", "僵硬的摆拍式笑容"),
       ("Is the person giving a stiff, posed smile?", "人物是否露出僵硬的摆拍式笑容？"), when=_FACE),
    _e("beautified-face", "expression", "forbid",
       ("Beautified face proportions: enlarged eyes, a narrowed chin", "被美化的五官比例：放大的眼睛、过尖的下巴"),
       ("Do the face proportions look altered, with oversized eyes or a very narrow chin?",
        "五官比例是否像被修改过，比如眼睛过大或下巴过尖？"), when=_FACE),
    # --- anatomy and physical defects ----------------------------------------------------
    _e("bad-hands", "anatomy", "forbid",
       ("Malformed hands: a wrong number of fingers, fused or bent fingers", "畸形的手：手指数量不对、粘连或弯折"),
       ("Does any visible hand have the wrong number of fingers, or fused or oddly bent fingers?",
        "画面中是否有手的手指数量不对、粘连或弯折异常？"), when=_HANDS),
    _e("bad-limbs", "anatomy", "forbid",
       ("Extra, missing or merged limbs", "多出、缺少或融合在一起的肢体"),
       ("Does any person have extra, missing or merged limbs?", "是否有人物的肢体多出、缺少或融合在一起？"), when=_PERSON),
    _e("warped-objects", "anatomy", "forbid",
       ("Warped or melted objects, or objects merged into each other", "变形、融化或互相粘连的物体"),
       ("Is any object visibly warped, melted or merged into another?", "是否有物体明显变形、融化或与别的物体粘连？")),
    _e("cutout-subject", "anatomy", "forbid",
       ("A subject that looks pasted on: light that does not match the background, a hard cut-out edge",
        "主体像贴上去的：光线和背景不一致，边缘像抠图"),
       ("Does the subject look pasted onto the background?", "主体是否像是贴在背景上的？")),
    _e("consistent-shadows", "anatomy", "texture",
       ("All shadows fall in one direction, matching the light", "所有阴影方向一致，和光源相符"),
       ("Do the shadows in the image fall in a consistent direction?", "画面中的阴影方向是否一致？")),
    # --- text ----------------------------------------------------------------------------
    _e("text", "text", "forbid",
       ("Text, watermarks or logos", "文字、水印或标志"),
       ("Does the image contain any text, watermark or logo?", "画面中是否出现了文字、水印或标志？"),
       status="verified"),
    _e("overlay-text", "text", "forbid",
       ("Captions, watermarks or other text laid over the image", "叠加在画面上的说明文字、水印等"),
       ("Is there a caption, watermark or other text laid over the image? Ignore text printed on objects in the scene.",
        "画面上是否叠加了说明文字、水印等？场景中物体上自带的文字不算。")),
    _e("legible-text", "text", "composition",
       ("Any text is spelled correctly and easy to read", "画面中的文字拼写正确、清晰可读"),
       ("Is all the text in the image correctly spelled and readable?", "画面中的文字是否都拼写正确、清晰可读？"),
       when=_HAS_TEXT),
    # --- light, composition and lens -----------------------------------------------------
    _e("sharp-face", "camera", "texture",
       ("The face is sharp and the eyes are in focus", "人物面部清晰，眼睛对焦准确"),
       ("Are the person's eyes and face sharp, with no blur?", "人物的眼睛和面部是否清晰锐利、没有发糊？"), when=_PERSON,
       status="verified"),
    _e("sharp-subject", "camera", "texture",
       ("The main subject is in sharp focus from edge to edge", "主体从头到尾都清晰对焦"),
       ("Is the whole main subject in sharp focus?", "主体是否整体清晰对焦？")),
    _e("side-back-light", "camera", "texture",
       ("Soft light from behind and to the side, with detail kept in the shadows", "柔和的侧逆光，暗部保留细节"),
       ("Does the main light come from behind and to the side of the subject, with detail left in the shadows?",
        "主光是否来自主体侧后方，并且暗部没有死黑？"), level="should",
       note=("Answers about light direction changed when the image was only blurred.",
             "只对图片做模糊时，光向的回答也变了。")),
    _e("soft-studio-light", "camera", "texture",
       ("Soft, even studio light with a gentle shadow under the subject", "柔和均匀的棚拍光，主体下方有淡淡的阴影"),
       ("Is the subject lit softly and evenly, without harsh shadows?", "主体的光线是否柔和均匀、没有生硬的阴影？")),
    _e("shallow-depth", "camera", "texture",
       ("Shallow depth of field: the subject is sharp and the background softly blurred", "浅景深：主体清晰，背景柔和虚化"),
       ("Is the background clearly more blurred than the subject?", "背景是否明显比主体更模糊？"), level="should"),
    _e("faces-left", "camera", "composition",
       ("The person faces or walks toward the left of the frame, with room ahead of them",
        "人物面向或走向画面左侧，视线前方留出空间"),
       ("Is the person facing or walking toward the left of the frame?", "人物是否面向或走向画面左侧？"), when=_PERSON,
       status="verified"),
    _e("waist-up", "camera", "composition",
       ("Medium shot: the person is framed from the waist up", "中景，人物腰部以上入画"),
       ("Is this a medium shot framed from the waist up?", "画面是否是腰部以上的中景？"), when=_PERSON,
       status="verified",
       note=("gpt-image-2 ignored this in 7 of 7 test images; cropping the result worked.",
             "gpt-image-2 在 7 张测试图里全部没有遵守；对结果裁切是有效的。")),
    _e("off-centre", "camera", "composition",
       ("The subject sits off-centre, near a third of the frame", "主体不居中，位于画面三分线附近"),
       ("Is the main subject placed clearly off-centre?", "主体是否明显偏离画面中心？"), level="should"),
    _e("empty-side", "camera", "composition",
       ("One side of the frame is left clear for copy", "画面一侧留出干净的空白，用来放文案"),
       ("Is there a large uncluttered area on one side of the image?", "画面一侧是否有大片干净的空白区域？"),
       level="should"),
    _e("whole-product", "camera", "composition",
       ("The product is centred and fully inside the frame", "产品居中，完整入画，没有被裁掉"),
       ("Is the whole product inside the frame and roughly centred?", "产品是否完整入画并且大致居中？")),
    _e("plain-background", "camera", "composition",
       ("A plain background with no props or other objects", "纯净的背景，没有道具或其他物体"),
       ("Is the background plain and free of other objects?", "背景是否干净、没有其他物体？")),
    _e("colour-cast", "camera", "forbid",
       ("A colour cast over the whole image, such as a yellow or blue tint", "整张图偏色，比如偏黄或偏蓝"),
       ("Does the whole image have a visible colour cast?", "整张图是否有明显的偏色？")),
    _e("full-body", "camera", "composition",
       ("The whole body is in frame, from head to feet", "全身入画，从头到脚都在画面内"),
       ("Is the person's whole body in frame, from head to feet?", "人物是否从头到脚完整入画？"), when=_PERSON),
    _e("neutral-pose", "camera", "composition",
       ("Standing upright in a neutral pose, facing the camera", "自然站立，正面朝向镜头"),
       ("Is the person standing upright and facing the camera?", "人物是否自然站立并正面朝向镜头？"), when=_PERSON),
    _e("one-person", "camera", "composition",
       ("Exactly one person in the image", "画面中只有一个人物"),
       ("Is there exactly one person in the image?", "画面中是否正好只有一个人物？")),
    _e("wide-shot", "camera", "composition",
       ("A wide establishing shot that shows the whole setting", "交代环境的大全景，能看到场景全貌"),
       ("Is this a wide shot that shows the whole setting?", "画面是否是能看到场景全貌的全景？")),
    _e("straight-verticals", "camera", "composition",
       ("Walls and columns stand straight, with no leaning or warped lines", "墙体和立柱横平竖直，没有倾斜或扭曲"),
       ("Are the vertical lines of the buildings straight, without leaning or warping?",
        "建筑的竖直线条是否笔直、没有倾斜或扭曲？")),
    _e("people", "camera", "forbid",
       ("People or characters in the scene", "场景中出现人物"),
       ("Are any people visible in the image?", "画面中是否能看到人物？")),
    _e("broken-architecture", "anatomy", "forbid",
       ("Impossible architecture: stairs that lead nowhere, misaligned windows, roofs that merge",
        "不合理的建筑结构：不通向任何地方的楼梯、错位的门窗、粘连的屋顶"),
       ("Does any building have an impossible or broken structure?", "是否有建筑的结构不合理或出现错乱？")),
    _e("anachronism", "anatomy", "forbid",
       ("Things from the wrong era, such as modern objects in a period setting", "不属于这个时代的东西，比如古装场景里的现代物品"),
       ("Does the image contain anything that does not belong to the era of the setting?",
        "画面中是否出现了不属于场景所在时代的东西？")),
    # --- style ---------------------------------------------------------------------------
    _e("photoreal", "style", "texture",
       ("Looks like a photograph taken with a real camera", "看起来是真实相机拍摄的照片"),
       ("Does this look like a real photograph rather than a render or an illustration?",
        "这张图看起来是真实拍摄的照片，而不是渲染图或插画吗？"),
       status="verified",
       note=("Verified only against a strong change (the image redrawn as flat colour); a subtle AI look is untested.",
             "只用强改动（把图变成色块插画）验证过；细微的“AI 味”还没测。")),
    _e("muted-tones", "style", "texture",
       ("Muted, low-saturation tones", "低饱和、柔和的色调"),
       ("Are the colours muted and low in saturation?", "画面的颜色是否柔和、饱和度偏低？"), level="should"),
    _e("flat-illustration", "style", "texture",
       ("Flat illustration: solid areas of colour, no photographic shading", "扁平插画：纯色色块，没有照片式的明暗过渡"),
       ("Is the image drawn in a flat style with solid areas of colour?", "画面是否是用纯色色块画成的扁平风格？")),
    _e("limited-palette", "style", "texture",
       ("A limited palette of about five main colours", "有限的配色，主要颜色不超过五种左右"),
       ("Does the image use only a few main colours, about five or fewer?", "画面是否只用了少数几种主要颜色（约五种以内）？")),
    _e("clean-lines", "style", "texture",
       ("Clean outlines of even weight", "线条干净，粗细一致"),
       ("Are the outlines clean and of even weight?", "线条是否干净、粗细一致？"), level="should"),
    _e("render-look", "style", "forbid",
       ("A 3D-render or game-engine look", "3D 渲染或游戏引擎的质感"),
       ("Does the image look like a 3D render or a video-game screenshot?", "这张图是否像 3D 渲染图或游戏截图？")),
    _e("photo-shading", "style", "forbid",
       ("Photographic detail or realistic shading", "照片式的细节或写实的明暗"),
       ("Does the image contain photographic detail or realistic shading?", "画面中是否有照片式的细节或写实的明暗？")),
    # --- consistency with a reference -----------------------------------------------------
    _e("same-face", "consistency", "composition",
       ("The character has the same face as the reference", "人物的脸和参考图是同一个人"),
       ("Is the person's face the same person as in the reference image?", "人物的脸和参考图里的是否是同一个人？"),
       when=_FACE, ref=("refs/character.png", "the character", "角色定妆图"), status="weak", measure="face-match",
       note=("In a 7-pair trial the judge called 3 of 3 different generated faces the same person. With the face "
             "tools installed this rule is decided by a face-comparison model instead.",
             "7 对图的小测试里，3 对不同的生成人脸全被判官判成同一个人。装了人脸工具后，这条规则改由人脸比对模型来判。")),
    _e("same-outfit", "consistency", "composition",
       ("The same outfit and hairstyle as the reference", "服装和发型与参考图一致"),
       ("Are the person's outfit and hairstyle the same as in the reference image?", "人物的服装和发型是否与参考图一致？"),
       when=_PERSON, ref=("refs/character.png", "the character", "角色定妆图")),
    _e("same-place", "consistency", "composition",
       ("The setting is the place shown in the reference: the same buildings and layout", "场景就是参考图里的地方：建筑和布局相同"),
       ("Is the setting the same place as in the reference image?", "场景是否与参考图是同一个地方？"),
       ref=("refs/scene.png", "the setting", "场景图")),
    _e("same-light", "consistency", "texture",
       ("The same light direction and time of day as the reference", "光线方向和时间段与参考图一致"),
       ("Do the light direction and time of day match the reference image?", "光线方向和时间段是否与参考图一致？"),
       level="should", ref=("refs/scene.png", "the setting", "场景图")),
    _e("same-style", "consistency", "texture",
       ("The same rendering style and colour grading as the reference", "画风和色调与参考图一致"),
       ("Do the rendering style and colour grading match the reference image?", "画风和色调是否与参考图一致？"),
       ref=("refs/scene.png", "the setting", "场景图")),
)

_BY_ID = {e.id: e for e in ENTRIES}


def get(entry_id: str) -> Entry:
    """Look up one entry. Raises ``KeyError`` for an unknown id."""
    return _BY_ID[entry_id]


def entries(category: str | None = None, status: str | None = None) -> list[Entry]:
    return [e for e in ENTRIES if category in (None, e.category) and status in (None, e.status)]


def compose(ids: list[str], lang: str = "en", *, name: str = "", summary: str = "",
            settings: dict[str, str] | None = None) -> Spec:
    """Build a spec from library entries, grouped into the three usual sections."""
    i = 1 if lang == "zh" else 0
    spec = Spec(name=name, lang=lang, preamble=[summary] if summary else [], settings=dict(settings or {}))
    for kind, titles in SECTIONS.items():
        rules = [get(x).rule(lang) for x in ids if get(x).kind == kind]
        if rules:
            spec.categories.append(Category(title=titles[i], kind=kind, rules=rules))
    return spec


@dataclass(frozen=True)
class Template:
    name: tuple[str, str]
    summary: tuple[str, str]
    size: str
    ids: tuple[str, ...]

    def spec(self, lang: str = "en") -> Spec:
        i = 1 if lang == "zh" else 0
        return compose(list(self.ids), lang, name=self.name[i], summary=self.summary[i],
                       settings={"size": self.size, "quality": "high"})


TEMPLATES: dict[str, Template] = {
    "portrait": Template(
        ("Realistic portrait", "写实人像"),
        ("A natural-light portrait that looks like a real photograph, not a retouched studio shot.",
         "自然光下的写实人像，看起来是真实拍摄的照片，不是精修的棚拍。"),
        "1024x1536",
        ("photoreal", "skin-texture", "sharp-face", "eye-catchlight", "shallow-depth", "natural-expression",
         "plastic-skin", "beautified-face", "staged-smile", "bad-hands", "text"),
    ),
    "product": Template(
        ("Product photo", "电商产品图"),
        ("A clean studio product photograph for an online shop listing.", "用于电商商品页的干净棚拍产品图。"),
        "1024x1024",
        ("photoreal", "sharp-subject", "soft-studio-light", "whole-product", "plain-background",
         "colour-cast", "oversaturated", "warped-objects", "overlay-text"),
    ),
    "illustration": Template(
        ("Flat illustration", "扁平插画"),
        ("A flat editorial illustration with a limited palette.", "配色有限的扁平风格编辑插画。"),
        "1536x1024",
        ("flat-illustration", "limited-palette", "clean-lines", "muted-tones", "off-centre", "empty-side",
         "photo-shading", "render-look", "bad-hands", "text"),
    ),
    "drama-character": Template(
        ("Short drama: character sheet", "短剧：角色定妆图"),
        ("A character reference image for a short drama: one character, clearly lit, easy to reuse in later shots.",
         "短剧的角色定妆图：单个角色，光线清楚，方便在后续镜头里复用。"),
        "1024x1536",
        ("soft-studio-light", "sharp-face", "skin-texture", "one-person", "full-body", "neutral-pose",
         "neutral-expression", "plain-background", "plastic-skin", "bad-hands", "text"),
    ),
    "drama-scene": Template(
        ("Short drama: scene and architecture", "短剧：场景与建筑"),
        ("An empty establishing shot of a setting for a short drama, to be reused as the backdrop of later shots.",
         "短剧的空镜场景图，作为后续镜头的背景复用。"),
        "1536x1024",
        ("consistent-shadows", "wide-shot", "straight-verticals", "people", "broken-architecture",
         "warped-objects", "text"),
    ),
    "drama-shot": Template(
        ("Short drama: shot keyframe", "短剧：分镜关键帧"),
        ("A vertical keyframe for one shot of a short drama. The character and the setting must match the "
         "reference images.",
         "短剧单个镜头的竖屏关键帧。角色和场景必须与参考图一致。"),
        "864x1536",
        ("same-style", "same-light", "sharp-face", "same-face", "same-outfit", "same-place",
         "bad-hands", "bad-limbs", "text"),
    ),
}
