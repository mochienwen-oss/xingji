import { describe, expect, it } from "vitest";
import { distanceKmBetween, parseLocation, straightLineKm } from "./geo";

/** 参考点一律用高德的 "lng,lat"（经度在前）写法，避免把经纬度读反的测试跟着写反。 */
const HANGZHOU_XIHU: [number, number] = [120.166525, 30.239091];
const SHANGHAI_RENMIN: [number, number] = [121.473701, 31.230416];
const BEIJING_TIANANMEN: [number, number] = [116.397499, 39.908722];

describe("parseLocation：把后端存的 \"lng,lat\" 转成坐标", () => {
  it("解析逗号分隔的经纬度，两侧空白不影响", () => {
    expect(parseLocation("120.166525,30.239091")).toEqual([120.166525, 30.239091]);
    expect(parseLocation(" 120.15 , 30.28 ")).toEqual([120.15, 30.28]);
    expect(parseLocation("-122.4,37.7")).toEqual([-122.4, 37.7]);
  });

  it("没有坐标（null / undefined / 空串）时返回 null", () => {
    expect(parseLocation(null)).toBeNull();
    expect(parseLocation(undefined)).toBeNull();
    expect(parseLocation("")).toBeNull();
    expect(parseLocation("   ")).toBeNull();
  });

  it("只有一项时返回 null：单个数字不是坐标", () => {
    expect(parseLocation("120.15")).toBeNull();
    expect(parseLocation("30.28")).toBeNull();
  });

  it("非数字分量返回 null", () => {
    expect(parseLocation("abc,30")).toBeNull();
    expect(parseLocation("120.15,abc")).toBeNull();
    expect(parseLocation("NaN,30")).toBeNull();
    expect(parseLocation("120.15,Infinity")).toBeNull();
  });

  it("多余字段只会被忽略，不会把 lat 当成 lng", () => {
    // 后端契约是 "lng,lat"；多出来的字段不能改变前两项的经纬度语义。
    expect(parseLocation("120,30,0")).toEqual([120, 30]);
  });

  it("脏坐标必须按未知处理，不能当成有效经纬度（回归）", () => {
    // 需求依据：README:108「缺失时显示未知」；geo.ts 注释「缺值或非数字返回 null」。
    // 回归背景：修复前 Number("") === 0，于是 "120.15," 会变成 [120.15, 0]，
    // 在行程体检里被算成上万公里、在时间估算里变成几小时的直线路段。
    expect(parseLocation("120.15,")).toBeNull();
    expect(parseLocation(",30.28")).toBeNull();
    expect(parseLocation("120.15, ")).toBeNull();
    // 经纬度超出地球范围时同样不是可以参与距离计算的坐标。
    expect(parseLocation("200,100")).toBeNull();
    expect(parseLocation("120.15,100")).toBeNull();
    expect(distanceKmBetween("200,100", "121.473701,31.230416")).toBeNull();
  });
});

describe("straightLineKm：大圆直线距离（公里）", () => {
  it("同一点距离为 0", () => {
    expect(straightLineKm(HANGZHOU_XIHU, HANGZHOU_XIHU)).toBe(0);
    expect(straightLineKm([0, 0], [0, 0])).toBe(0);
  });

  it("1 个纬度约 111.2 公里，赤道 1 个经度也约 111.2 公里", () => {
    expect(straightLineKm([120, 30], [120, 31])).toBeCloseTo(111.19, 1);
    expect(straightLineKm([0, 0], [1, 0])).toBeCloseTo(111.19, 1);
    // 北纬 30 度处经度圈收窄，1 个经度约 96.3 公里。
    expect(straightLineKm([120, 30], [121, 30])).toBeCloseTo(96.3, 0);
  });

  it("城市间距离与地理常识一致", () => {
    const hangzhouShanghai = straightLineKm(HANGZHOU_XIHU, SHANGHAI_RENMIN);
    expect(hangzhouShanghai).toBeGreaterThan(160);
    expect(hangzhouShanghai).toBeLessThan(175);
    const beijingShanghai = straightLineKm(BEIJING_TIANANMEN, SHANGHAI_RENMIN);
    expect(beijingShanghai).toBeGreaterThan(1060);
    expect(beijingShanghai).toBeLessThan(1075);
  });

  it("对跖点不会因浮点误差超过半周长", () => {
    const antipodal = straightLineKm([0, 0], [180, 0]);
    expect(Number.isFinite(antipodal)).toBe(true);
    expect(antipodal).toBeCloseTo(Math.PI * 6371, 0); // 约 20015.1 公里
    expect(antipodal).toBeLessThanOrEqual(Math.PI * 6371 + 0.01);
    // 同样的对跖关系换个写法：南极点与北极点。
    expect(straightLineKm([0, 90], [0, -90])).toBeCloseTo(Math.PI * 6371, 0);
  });

  it("跨国际日期变更线时按短边计算，而不是绕地球一圈", () => {
    // 经度 179.9 与 -179.9 只差 0.2 度，约 22.2 公里。
    expect(straightLineKm([179.9, 0], [-179.9, 0])).toBeCloseTo(22.24, 1);
    // 靠近极点时跨 180 度经线其实是越过极点，约 2 度 = 222 公里。
    const overPole = straightLineKm([0, 89], [180, 89]);
    expect(overPole).toBeCloseTo(222.39, 0);
    expect(overPole).toBeGreaterThan(200);
  });

  it("距离与方向无关（对称）", () => {
    expect(straightLineKm(HANGZHOU_XIHU, SHANGHAI_RENMIN)).toBeCloseTo(
      straightLineKm(SHANGHAI_RENMIN, HANGZHOU_XIHU),
      6,
    );
  });
});

describe("distanceKmBetween：直接从后端的 location 字符串算距离", () => {
  it("两端都能解析时等于按坐标算出的直线距离", () => {
    const from = "120.166525,30.239091";
    const to = "121.473701,31.230416";
    expect(distanceKmBetween(from, to)).toBeCloseTo(
      straightLineKm(parseLocation(from) as [number, number], parseLocation(to) as [number, number]),
      9,
    );
  });

  it("同一个地点字符串距离为 0", () => {
    expect(distanceKmBetween("120.15,30.28", "120.15,30.28")).toBe(0);
  });

  it("任一端缺坐标或不可解析时返回 null，不能用 0 或直线蒙混", () => {
    expect(distanceKmBetween("", "121.47,31.23")).toBeNull();
    expect(distanceKmBetween("120.16,30.23", "")).toBeNull();
    expect(distanceKmBetween("", "")).toBeNull();
    expect(distanceKmBetween("abc", "121.47,31.23")).toBeNull();
    expect(distanceKmBetween("120.16,30.23", "121.47")).toBeNull();
    // 半夜里写成 "null" 或被前端 JSON 拼成 "undefined" 这类脏值同样算未知。
    expect(distanceKmBetween("undefined", "121.47,31.23")).toBeNull();
  });
});
