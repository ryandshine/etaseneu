import { afterEach, describe, expect, it, vi } from "vitest";
import { createApiClient, setAuthToken, setUnauthorizedHandler } from "../lib/api";

afterEach(() => {
  setAuthToken(null);
  setUnauthorizedHandler(null);
  vi.restoreAllMocks();
});

describe("lib/api auth", () => {
  it("melampirkan Authorization header saat token diset", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    setAuthToken("tok-123");

    await createApiClient().getHealth();

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
  });

  it("tidak ada Authorization header saat token null", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await createApiClient().getHealth();

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("memanggil unauthorized handler dan melempar saat respons 401", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("nope", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    const onUnauth = vi.fn();
    setUnauthorizedHandler(onUnauth);

    await expect(createApiClient().getHealth()).rejects.toThrow();
    expect(onUnauth).toHaveBeenCalledOnce();
  });
});
