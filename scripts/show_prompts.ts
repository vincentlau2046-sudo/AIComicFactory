import { buildFirstFramePrompt, buildLastFramePrompt } from "@/lib/ai/prompts/frame-generate";

const SHOT_PROMPT = "淮右荒原黎明。冷冽的青灰色晨雾如厚重的湿毯般笼罩着龟裂干涸的河床，枯黄的野草与残破的断矛交错编织出灰褐色的粗粝纹理。远处破败村庄的残垣在雾霭中若隐若现，天际线透出微弱的灰白天光。自然光为清冷低饱和的青灰色调，主光自东方地平线斜射，在沙砾上投下长长的冷调阴影。色彩基调：青灰、枯褐、暗蓝、冷白。氛围：苍凉悲壮，风沙卷起细碎沙尘的干燥质感，空气中弥漫着泥土与铁锈混合的陈旧气息，远处隐约有悲鸣般的长风呼啸。";

const FIRST_V4 = "冷冽的青灰色晨雾如厚重的湿毯般笼罩着龟裂干涸的河床，枯黄的野草与残破的断矛交错编织出灰褐色的粗粝纹理。远处破败村庄的残垣在雾霭中若隐若现，天际线透出微弱的灰白天光。一具无名枯骨与半截褪色残旗静静卧于沙砾间，朔风卷起细碎沙尘掠过枯草尖端。自然光自东方地平线斜射，在沙砾上投下长长的冷调阴影。镜头从低处平视，广角视角，画面充满苍凉的荒原质感。";

const ALL_CHARS = "朱元璋: 电影级写实历史正剧风格，自然光效，85mm镜头特写——男，跨度约25至68岁，核心呈现期35岁，身高约175cm，体型由早年皮包骨头的瘦削渐变为中年精干结实、晚年魁梧厚实，站姿沉稳如山，双肩微展透出开国帝王的绝对威压与草莽历练出的隐忍狠戾。方圆脸微带菱角，颧骨平阔，下颌线刚硬如刀削，眉骨隆起投下深邃阴影。细长凤眼内藏锐光，瞳色深褐近黑，目光阴鸷锐利如鹰隼，早年带风霜沧桑，后期凝练为帝王威仪。\n\n徐达: 电影级写实历史正剧风格，自然光效，85mm镜头特写——男，约35岁，身高约182cm，体型魁梧健硕如铁塔，肩宽背厚，站姿笔挺如松，透着一股沉稳肃杀的将帅之风。";

const EMPTY = "";

// Scenarios
const scenarios = [
  { name: "A: FIRST_FRAME, chars=[], characterDescriptions=''", prompt: buildFirstFramePrompt({
    sceneDescription: SHOT_PROMPT,
    startFrameDesc: FIRST_V4,
    characterDescriptions: EMPTY,
    previousLastFrame: undefined,
    slotContents: {}
  })},
  { name: "B: FIRST_FRAME, chars=[朱元璋], characterDescriptions=ALL_CHARS", prompt: buildFirstFramePrompt({
    sceneDescription: SHOT_PROMPT,
    startFrameDesc: FIRST_V4,
    characterDescriptions: ALL_CHARS,
    previousLastFrame: undefined,
    slotContents: {}
  })},
  { name: "C: LAST_FRAME, chars=[], characterDescriptions='', no active last_frame (endFrameDesc=shot.prompt)", prompt: buildLastFramePrompt({
    sceneDescription: SHOT_PROMPT,
    endFrameDesc: SHOT_PROMPT,
    characterDescriptions: EMPTY,
    firstFramePath: "",
    slotContents: {}
  })},
  { name: "D: LAST_FRAME, chars=[朱元璋], characterDescriptions=ALL_CHARS, has last_frame", prompt: buildLastFramePrompt({
    sceneDescription: SHOT_PROMPT,
    endFrameDesc: "朱元璋背对镜头站立于画面中央偏右位置，双脚稳稳踩在干硬的泥壳上，身体朝向远方地平线。",
    characterDescriptions: ALL_CHARS,
    firstFramePath: "",
    slotContents: {}
  })},
];

for (const sc of scenarios) {
  console.log("=".repeat(70));
  console.log("  " + sc.name);
  console.log("  PROMPT LENGTH: " + sc.prompt.length + " chars");
  console.log("=".repeat(70));
  console.log(sc.prompt);
  console.log();
}
