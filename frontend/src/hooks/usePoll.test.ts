import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { usePoll } from "./usePoll";

describe("usePoll", () => {
  it("loads data and refreshes on demand", async () => {
    let n = 0;
    const fn = vi.fn(async () => ++n);
    const { result } = renderHook(() => usePoll(fn, 100000));

    await waitFor(() => expect(result.current.data).toBe(1));
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.data).toBe(2);
    expect(result.current.error).toBeNull();
  });

  it("captures errors as a message string", async () => {
    const fn = vi.fn(async () => {
      throw new Error("boom");
    });
    const { result } = renderHook(() => usePoll(fn, 100000));

    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.data).toBeNull();
  });
});
