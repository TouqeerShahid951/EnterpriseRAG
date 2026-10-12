import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantResponseActions } from "./AssistantResponseActions";

const { setStatus } = vi.hoisted(() => ({ setStatus: vi.fn() }));
vi.mock("react", async (importOriginal) => ({
  ...await importOriginal<typeof import("react")>(),
  useState: () => ["", setStatus],
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

const props = { answer: "**Answer** with citation [1]", createdAt: "2026-09-08T10:30:00Z", onReply: vi.fn() };

describe("AssistantResponseActions", () => {
  it("renders labeled actions and the saved timestamp, omitting invalid dates", () => {
    const markup = renderToStaticMarkup(<AssistantResponseActions {...props} />);
    expect(markup).toContain('aria-label="Copy response"');
    expect(markup).toContain('aria-label="Reply to this answer"');
    expect(markup).toContain('dateTime="2026-09-08T10:30:00Z"');
    expect(renderToStaticMarkup(<AssistantResponseActions {...props} createdAt="invalid" />)).not.toContain("<time");
  });

  it("copies the full answer and reports clipboard success and failure", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const actions = AssistantResponseActions(props);
    await actions.props.children[0].props.onClick();
    expect(writeText).toHaveBeenCalledWith(props.answer);
    expect(setStatus).toHaveBeenLastCalledWith("Copied");
    writeText.mockRejectedValue(new Error("Permission denied"));
    await actions.props.children[0].props.onClick();
    expect(setStatus).toHaveBeenLastCalledWith("Could not copy. Select the response and copy it manually.");
    vi.stubGlobal("navigator", {});
    await actions.props.children[0].props.onClick();
    expect(setStatus).toHaveBeenLastCalledWith("Could not copy. Select the response and copy it manually.");
  });
});
