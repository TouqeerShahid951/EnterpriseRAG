import { describe, expect, it } from "vitest";

import { connectorFlowStep, nextConnectorAction, normalizeCatalogJson, type ConnectorNextAction } from "./connectorPanelUtils";
import type { ConnectorProfile, ConnectorSchemaCatalog } from "@/types/api";

describe("nextConnectorAction", () => {
  it.each([
    ["untested connection", null, null, "test"],
    ["failed connection", "failed", null, "test"],
    ["passed connection without a catalog", "ok", null, "read_schema"],
    ["draft catalog", "ok", "draft", "review"],
    ["reviewed catalog", "ok", "reviewed", "review"],
    ["disabled catalog", "ok", "disabled", "review"],
    ["approved catalog", "ok", "approved", "live"],
  ] satisfies Array<[string, ConnectorProfile["last_test_status"], ConnectorSchemaCatalog["status"] | null, ConnectorNextAction]>)(
    "%s advances to %s",
    (_case, testStatus, catalogStatus, expected) => {
      const profile = { last_test_status: testStatus } as ConnectorProfile;
      const catalog = catalogStatus ? { status: catalogStatus } as ConnectorSchemaCatalog : null;

      expect(nextConnectorAction(profile, catalog)).toBe(expected);
    },
  );
});

describe("connectorFlowStep", () => {
  it("returns the current wizard stage for the connector", () => {
    expect(connectorFlowStep({ last_test_status: null } as ConnectorProfile, null)).toBe(1);
    expect(connectorFlowStep({ last_test_status: "ok" } as ConnectorProfile, null)).toBe(2);
    expect(connectorFlowStep({ last_test_status: "ok" } as ConnectorProfile, { status: "draft" } as ConnectorSchemaCatalog)).toBe(3);
    expect(connectorFlowStep({ last_test_status: "ok" } as ConnectorProfile, { status: "approved" } as ConnectorSchemaCatalog)).toBe(4);
  });
});

describe("normalizeCatalogJson", () => {
  it("keeps generated routing metadata editable", () => {
    const catalog = normalizeCatalogJson({
      routing_profile: {
        capabilities: ["exact_lookup", "filtering"],
        data_origin: "document_extraction",
        freshness: "batch",
        provenance: "connector_introspection",
      },
    });

    expect(catalog.routing_profile).toMatchObject({
      capabilities: ["exact_lookup", "filtering"],
      data_origin: "document_extraction",
      freshness: "batch",
      provenance: "connector_introspection",
    });
  });
});
