import { describe, expect, it } from "vitest";
import { maskShareLink, shareToken, shareUrl } from "./shareLink";

describe("shareLink", () => {
  it("用路径式链接生成分享地址", () => {
    expect(shareUrl("abc/def", "https://trip.example")).toBe("https://trip.example/s/abc%2Fdef");
  });

  it("同时解析路径式与旧 hash 链接", () => {
    expect(shareToken("https://trip.example/s/token-123")).toBe("token-123");
    expect(shareToken("https://trip.example/#share=token-456")).toBe("token-456");
    expect(shareToken("https://trip.example/#share=tok%2Fen")).toBe("tok/en");
    expect(shareToken("https://trip.example/trips")).toBe("");
  });

  it("裁剪长 token 但保留可辨认首尾", () => {
    const url = "https://trip.example/s/abcdefghijklmnopqrstuvwxyz";
    expect(maskShareLink(url)).toBe("https://trip.example/s/abcdefgh…wxyz");
    expect(maskShareLink("https://trip.example/#share=abcdefghijklmnopqrstuvwxyz"))
      .toBe("https://trip.example/#share=abcdefgh…wxyz");
    expect(maskShareLink("https://trip.example/s/short")).toBe("https://trip.example/s/short");
  });
});
