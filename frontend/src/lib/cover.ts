/**
 * D3 封面系统：没有图片资产时用「地点首字 + 地方风景线稿 + 色板」生成排印封面。
 * 所有结果必须由城市名确定：同一城市在任何页面、任何设备上落到同一色板、同一个字和同一幅风景。
 */

/** 5 套色板：纸、沙、砖红、靛蓝、墨。 */
export type CoverTone = 0 | 1 | 2 | 3 | 4;

/** 地方风景母题：决定首字字徽与背景线稿画什么。 */
export type CoverMotif =
  | 'water'
  | 'mountain'
  | 'coast'
  | 'eaves'
  | 'skyline'
  | 'dunes'
  | 'snow'
  | 'garden'
  | 'bamboo';

const TONE_COUNT = 5;

/** FNV-1a：短字符串也能得到分散的 32 位散列。 */
function hashCity(city: string): number {
  let hash = 2166136261;
  const text = city.trim();
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

/** 城市 -> 色板索引，纯函数、确定性别随机。 */
export function coverTone(city: string): CoverTone {
  return (hashCity(city) % TONE_COUNT) as CoverTone;
}

/**
 * 先认常见目的地，再按地名里的地貌词兜底，最后才用散列。
 * 顺序即优先级：同一地名命中多条规则时，取更具体的那条。
 */
const MOTIF_RULES: ReadonlyArray<{ pattern: RegExp; motif: CoverMotif }> = [
  {
    pattern: /(三亚|厦门|青岛|大连|威海|烟台|北海|珠海|舟山|海口|万宁|陵水|涠洲|东山|鼓浪屿|普陀山|长岛|秦皇岛|日照)/,
    motif: 'coast',
  },
  {
    pattern: /(敦煌|嘉峪关|张掖|中卫|吐鲁番|哈密|库尔勒|喀什|和田|阿拉善|鄂尔多斯|额济纳|沙坡头|鸣沙山|戈壁)/,
    motif: 'dunes',
  },
  {
    pattern: /(哈尔滨|长春|吉林市|延吉|漠河|呼伦贝尔|锡林郭勒|阿勒泰|禾木|喀纳斯|雪乡|崇礼|亚布力|长白山)/,
    motif: 'snow',
  },
  {
    pattern: /(桂林|阳朔|张家界|黄山|庐山|峨眉|丽江|大理|香格里拉|九寨|武夷|泰山|华山|嵩山|天山|梅里|稻城|亚丁|林芝|波密|恩施|神农架|拉萨|日喀则)/,
    motif: 'mountain',
  },
  {
    pattern: /(杭州|西湖|苏州|扬州|绍兴|乌镇|周庄|西塘|南浔|同里|甪直|朱家角|无锡|嘉兴|湖州|昆明)/,
    motif: 'garden',
  },
  {
    pattern: /(成都|宜宾|安吉|莫干山|蜀南竹海|赤水|永安|井冈山)/,
    motif: 'bamboo',
  },
  {
    pattern: /(北京|西安|洛阳|开封|南京|大同|平遥|沈阳|荆州|襄阳|曲阜|承德|正定|泉州|潮州|阆中|徽州|歙县)/,
    motif: 'eaves',
  },
  {
    pattern: /(上海|深圳|香港|广州|重庆|武汉|天津|长沙|郑州|合肥|南昌|福州|济南|石家庄|太原|贵阳|南宁|兰州|西宁|银川|乌鲁木齐)/,
    motif: 'skyline',
  },
];

const FALLBACK_MOTIFS: ReadonlyArray<CoverMotif> = [
  'garden',
  'water',
  'mountain',
  'coast',
  'eaves',
  'skyline',
  'bamboo',
  'dunes',
  'snow',
];

/** 城市 -> 风景母题；纯函数、确定性，未知地名也有稳定的兜底。 */
export function coverMotif(city: string): CoverMotif {
  const text = city.trim();
  if (!text) return 'garden';

  for (const rule of MOTIF_RULES) {
    if (rule.pattern.test(text)) return rule.motif;
  }
  if (/海|湾|岛|港|滩|澳/.test(text)) return 'coast';
  if (/沙|漠|戈壁/.test(text)) return 'dunes';
  if (/雪|冰/.test(text)) return 'snow';
  if (/山|峰|岭|峡|岩/.test(text)) return 'mountain';
  if (/江|河|湖|溪|泉|潭|塘|洲|水/.test(text)) return 'water';
  if (/竹|林/.test(text)) return 'bamboo';
  if (/京|都|城|镇|关|陵|寺|塔/.test(text)) return 'eaves';
  return FALLBACK_MOTIFS[hashCity(text) % FALLBACK_MOTIFS.length];
}

/**
 * 封面用的地点首字：中文取首字，英文取首字母并大写。
 * 与 Avatar 的 coverInitials 不同，这里始终只取一个字，给字徽留出画面。
 */
export function coverGlyph(city: string): string {
  const text = city.trim();
  if (!text) return '·';
  const first = Array.from(text)[0];
  return /[a-z0-9]/i.test(first) ? first.toUpperCase() : first;
}

/** 头像用的城市首字母：中文取首字，英文取首末词首字母。 */
export function coverInitials(city: string): string {
  const text = city.trim();
  if (!text) return '·';
  const words = text.split(/\s+/);
  if (words.length > 1) {
    return (words[0][0] + words[words.length - 1][0]).toUpperCase();
  }
  const chars = Array.from(text);
  return /[a-z0-9]/i.test(chars[0]) ? chars[0].toUpperCase() : chars[0];
}
