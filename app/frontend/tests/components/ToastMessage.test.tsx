import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { ToastMessage } from "../../src/components/ToastMessage";

afterEach(() => { vi.useRealTimers(); });

it("continues auto-dismissing ordinary notices and supports explicit dismissal", () => {
  vi.useFakeTimers();
  const dismiss = vi.fn();
  const rendered = render(<ToastMessage toast={{ id: "one", tone: "info", message: "Notice" }} onDismiss={dismiss} />);
  act(() => { vi.advanceTimersByTime(7000); });
  expect(dismiss).toHaveBeenCalledWith("one");
  fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(dismiss).toHaveBeenCalledTimes(2);
  rendered.unmount();
});
