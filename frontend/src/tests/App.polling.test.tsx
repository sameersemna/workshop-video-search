import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";

const getVideoGroupsMock = vi.fn();
const getProcessingStatusMock = vi.fn();

vi.mock("../components/VideoLibrary", () => ({
  default: () => <div data-testid="video-library" />,
}));

vi.mock("../components/VideoPlayer", () => ({
  default: () => <div data-testid="video-player" />,
}));

vi.mock("../components/AddVideoModal", () => ({
  default: () => <div data-testid="add-video-modal" />,
}));

vi.mock("../components/SearchPanel", () => ({
  default: () => <div data-testid="search-panel" />,
}));

vi.mock("../services/api", () => ({
  getApiErrorMessage: (error: unknown, fallback: string) => {
    if (error instanceof Error && error.message) {
      return error.message;
    }
    return fallback;
  },
  getVideoGroups: (...args: unknown[]) => getVideoGroupsMock(...args),
  getProcessingStatus: (...args: unknown[]) => getProcessingStatusMock(...args),
}));

const flushPromises = async () => {
  await Promise.resolve();
};

let visibilityState: "visible" | "hidden" = "visible";
let visibilityStateSpy: ReturnType<typeof vi.spyOn>;

describe("App polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    visibilityState = "visible";
    visibilityStateSpy = vi
      .spyOn(document, "visibilityState", "get")
      .mockImplementation(() => visibilityState);

    getVideoGroupsMock.mockResolvedValue({ groups: [] });
    getProcessingStatusMock
      .mockResolvedValueOnce({ queueLength: 1, processing: [] })
      .mockResolvedValueOnce({ queueLength: 0, processing: [] })
      .mockResolvedValue({ queueLength: 0, processing: [] });
  });

  afterEach(() => {
    visibilityStateSpy.mockRestore();
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("polls quickly while processing, then backs off when idle", async () => {
    await act(async () => {
      render(<App />);
      await flushPromises();
    });

    // Immediate poll on mount.
    expect(getProcessingStatusMock).toHaveBeenCalledTimes(1);

    // processing count > 0 => next poll in 3 seconds.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
      await flushPromises();
    });
    expect(getProcessingStatusMock).toHaveBeenCalledTimes(2);

    // processing count == 0 => next poll in 10 seconds.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
      await flushPromises();
    });
    expect(getProcessingStatusMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
      await flushPromises();
    });
    expect(getProcessingStatusMock).toHaveBeenCalledTimes(3);

    expect(getVideoGroupsMock).toHaveBeenCalled();
  });

  it("uses hidden-tab interval and polls immediately when tab becomes visible", async () => {
    getProcessingStatusMock.mockReset();
    getProcessingStatusMock
      .mockResolvedValueOnce({ queueLength: 0, processing: [] })
      .mockResolvedValue({ queueLength: 0, processing: [] });

    visibilityState = "hidden";

    await act(async () => {
      render(<App />);
      await flushPromises();
    });

    expect(getProcessingStatusMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
      await flushPromises();
    });

    // Hidden tab should back off to 30 seconds while idle.
    expect(getProcessingStatusMock).toHaveBeenCalledTimes(1);

    visibilityState = "visible";
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(0);
      await flushPromises();
    });

    expect(getProcessingStatusMock).toHaveBeenCalledTimes(2);
  });
});
