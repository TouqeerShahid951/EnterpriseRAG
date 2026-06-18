import { describe, expect, it } from "vitest";

import {
  buildMinioPrefixScheduleRequest,
  buildRecurrence,
  buildSnapshotScheduleRequest,
  defaultFolderScheduleDraft,
  folderSnapshotLabel,
  relativePathForFile,
  summarizeFolderFiles,
} from "./folderIngest";

describe("folder ingestion scheduling", () => {
  it("extracts browser folder relative paths and summarizes supported files", () => {
    const pdf = withRelativePath(new File(["%PDF-1.7"], "policy.pdf", { type: "application/pdf" }), "Finance/Policies/policy.pdf");
    const jpg = withRelativePath(new File(["jpeg"], "diagram.jpg", { type: "image/jpeg" }), "Finance/Images/diagram.jpg");
    const png = withRelativePath(new File(["png"], "chart.png", { type: "image/png" }), "Finance/Images/chart.png");
    const json = withRelativePath(new File(['{"case_id":"FIR-001"}'], "records.json", { type: "application/json" }), "Finance/Data/records.json");
    const text = withRelativePath(new File(["notes"], "notes.txt", { type: "text/plain" }), "Finance/notes.txt");

    const summary = summarizeFolderFiles([pdf, jpg, png, json, text]);

    expect(relativePathForFile(pdf)).toBe("Finance/Policies/policy.pdf");
    expect(summary.entries.map((entry) => entry.relativePath)).toEqual(["Finance/Policies/policy.pdf", "Finance/Images/diagram.jpg", "Finance/Images/chart.png", "Finance/Data/records.json", "Finance/notes.txt"]);
    expect(summary.supportedEntries).toHaveLength(4);
    expect(summary.unsupportedEntries).toHaveLength(1);
    expect(summary.validationMessages).toEqual([]);
  });

  it("labels the selected browser folder from relative paths", () => {
    const policy = withRelativePath(new File(["%PDF-1.7"], "policy.pdf", { type: "application/pdf" }), "Finance/Policies/policy.pdf");
    const chart = withRelativePath(new File(["png"], "chart.png", { type: "image/png" }), "Finance/Images/chart.png");
    const hr = withRelativePath(new File(["%PDF-1.7"], "handbook.pdf", { type: "application/pdf" }), "HR/handbook.pdf");

    expect(folderSnapshotLabel(summarizeFolderFiles([policy, chart]).entries)).toBe("Finance");
    expect(folderSnapshotLabel(summarizeFolderFiles([policy, hr]).entries)).toBe("2 folders selected");
    expect(folderSnapshotLabel([])).toBe("No folder selected");
  });

  it("reports empty supported folders and builds snapshot requests with relative paths", () => {
    const text = withRelativePath(new File(["notes"], "notes.txt", { type: "text/plain" }), "Finance/notes.txt");
    const summary = summarizeFolderFiles([text]);

    expect(summary.validationMessages).toEqual(["The selected folder does not contain any PDF, DOCX, JPG, PNG, or JSON files."]);

    const draft = {
      ...defaultFolderScheduleDraft("2026-06-09"),
      name: "Nightly snapshot",
      groupPath: "/finance",
      clearanceLevel: "NATO_SECRET" as const,
      scheduledAt: "2026-06-09T22:00",
      description: "Folder metadata",
    };
    const request = buildSnapshotScheduleRequest(draft, summary.entries);

    expect(request.relative_paths).toEqual(["Finance/notes.txt"]);
    expect(request.clearance_level).toBe("NATO_SECRET");
    expect(request.schedule_type).toBe("one_time");
    expect(request.scheduled_at).toBe("2026-06-09T22:00");
    expect(request.description).toBe("Folder metadata");
  });

  it("builds recurrence and MinIO prefix schedule payloads", () => {
    const draft = {
      ...defaultFolderScheduleDraft("2026-06-09"),
      sourceMode: "minio_prefix" as const,
      name: "Nightly prefix",
      groupPath: "/finance",
      clearanceLevel: "NATO_CONFIDENTIAL" as const,
      scheduleType: "recurring" as const,
      recurrenceDays: [0, 1, 2, 3, 4],
      recurrenceStartTime: "21:00",
      recurrenceEndTime: "06:00",
      bucket: "enterprise-docs",
      prefix: "/finance/policies/",
    };

    expect(buildRecurrence(draft)).toEqual({ days_of_week: [0, 1, 2, 3, 4], start_time: "21:00", end_time: "06:00" });
    expect(buildMinioPrefixScheduleRequest(draft)).toMatchObject({
      name: "Nightly prefix",
      bucket: "enterprise-docs",
      prefix: "finance/policies/",
      group_path: "/finance",
      clearance_level: "NATO_CONFIDENTIAL",
      scheduled_at: null,
      recurrence: { days_of_week: [0, 1, 2, 3, 4], start_time: "21:00", end_time: "06:00" },
    });
  });

  it("allows schedules without an effective date", () => {
    const draft = {
      ...defaultFolderScheduleDraft(""),
      sourceMode: "minio_prefix" as const,
      name: "Undated policies",
      groupPath: "/finance",
      bucket: "docs",
      prefix: "finance/",
      scheduledAt: "2026-06-09T22:00",
    };

    expect(buildMinioPrefixScheduleRequest(draft).effective_date).toBeNull();
  });

  it("rejects browser folder snapshots larger than 5 GB", () => {
    const oversized = {
      name: "archive.pdf",
      type: "application/pdf",
      size: 5 * 1024 * 1024 * 1024 + 1,
    } as File;

    expect(summarizeFolderFiles([oversized]).validationMessages).toEqual([
      "Folder snapshots cannot exceed 5 GB of supported files.",
    ]);
  });
});

function withRelativePath(file: File, relativePath: string): File {
  Object.defineProperty(file, "webkitRelativePath", { value: relativePath });
  return file;
}
