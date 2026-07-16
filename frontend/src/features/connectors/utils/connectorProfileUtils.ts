import type { UpdateConnectorProfileRequest } from "@/lib/api/contracts";
import { WORKSPACE_TIMEZONE } from "@/features/ingestion/state/folderIngest";
import type { ConnectorProfile, ConnectorSchemaCatalog, ConnectorType } from "@/types/api";

export type ConnectorProfileDraft = {
  connectorType: Extract<ConnectorType, "sql_server" | "postgres">;
  name: string;
  server: string;
  port: string;
  database: string;
  username: string;
  password: string;
  driver: string;
  customDriver: string;
  sslMode: string;
};

export type ProfileValidationOptions = {
  credentialsRequired: boolean;
};

export function formatDateTime(value: string | null): string {
  if (!value) return "Not scheduled";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: WORKSPACE_TIMEZONE }).format(new Date(value));
}

export function validateProfileDraft(draft: ConnectorProfileDraft, options: ProfileValidationOptions = { credentialsRequired: true }): string | null {
  if (!draft.name.trim()) return "Enter a connection name.";
  if (!draft.server.trim()) return draft.connectorType === "postgres" ? "Enter the PostgreSQL host." : "Enter the SQL Server host or listener.";
  if (draft.port.trim() && !Number.isInteger(Number(draft.port))) return "Enter a valid database port.";
  if (!draft.database.trim()) return "Enter the database name.";
  if (options.credentialsRequired) {
    if (!draft.username.trim()) return "Enter a read-only username.";
    if (!draft.password) return "Enter the connector password.";
  } else if (draft.username.trim() || draft.password) {
    if (!draft.username.trim() || !draft.password) return "Enter both replacement user and replacement password, or leave both blank.";
  }
  if (draft.connectorType === "sql_server" && draft.driver === "custom" && !draft.customDriver.trim()) return "Enter the custom SQL Server driver name.";
  return null;
}

export function profileTestDetail(profile: ConnectorProfile): string {
  if (!profile.last_test_status) return "Connection not tested";
  const result = profile.last_test_status === "ok" ? "Connection test passed" : "Connection test failed";
  const message = profile.last_test_message?.trim();
  const testedAt = profile.last_tested_at ? ` (${formatDateTime(profile.last_tested_at)})` : "";
  return `${result}${message ? `: ${message}` : ""}${testedAt}`;
}

export function profileEndpointSummary(profile: ConnectorProfile): string {
  const host = profile.connector_type === "postgres"
    ? stringConfig(profile.public_config.host)
    : parseSqlServerServer(stringConfig(profile.public_config.server)).host || stringConfig(profile.public_config.host);
  const database = stringConfig(profile.public_config.database);
  return [host, database].filter(Boolean).join(" / ") || "Endpoint redacted";
}

export function profileHealthLabel(profile: ConnectorProfile): string {
  if (profile.last_test_status === "ok") return "Passed";
  if (profile.last_test_status === "failed") return "Failed";
  return "Not tested";
}

export function profileHealthPillClass(profile: ConnectorProfile): string {
  if (profile.last_test_status === "ok") return "sv-pill sv-pill-success";
  if (profile.last_test_status === "failed") return "sv-pill border-error-red/30 bg-error-container text-error-red";
  return "sv-pill";
}

export function catalogName(catalog: ConnectorSchemaCatalog, profile: ConnectorProfile): string {
  const name = catalog.catalog_json.name;
  return typeof name === "string" && name.trim() ? name.trim() : `${profile.name} Live DB access`;
}

export function connectorTypeLabel(value: string): string {
  if (value === "sql_server") return "SQL Server";
  if (value === "postgres") return "PostgreSQL";
  if (value === "mysql") return "MySQL";
  if (value === "mariadb") return "MariaDB";
  if (value === "mongodb") return "MongoDB";
  if (value === "opensearch") return "OpenSearch";
  if (value === "elasticsearch") return "Elasticsearch";
  if (value === "redis") return "Redis";
  if (value === "cassandra") return "Cassandra";
  if (value === "fake") return "Fake connector";
  return value.replace("_", " ");
}

export function defaultProfileDraft(): ConnectorProfileDraft {
  return defaultProfileDraftForType("sql_server");
}

export function defaultProfileDraftForType(connectorType: ConnectorProfileDraft["connectorType"]): ConnectorProfileDraft {
  return {
    connectorType,
    name: "",
    server: "",
    port: connectorType === "postgres" ? "5432" : "1433",
    database: "",
    username: "",
    password: "",
    driver: connectorType === "sql_server" ? "ODBC Driver 18 for SQL Server" : "",
    customDriver: "",
    sslMode: connectorType === "postgres" ? "prefer" : "",
  };
}

export function profilePublicConfig(draft: ConnectorProfileDraft): Record<string, string | number | boolean> {
  if (draft.connectorType === "postgres") {
    return {
      host: draft.server.trim(),
      port: Number(draft.port.trim() || 5432),
      database: draft.database.trim(),
      sslmode: draft.sslMode || "prefer",
    };
  }
  const driver = draft.driver === "custom" ? draft.customDriver.trim() : draft.driver.trim();
  return {
    server: draft.port.trim() ? `${draft.server.trim()},${draft.port.trim()}` : draft.server.trim(),
    database: draft.database.trim(),
    driver: driver || "ODBC Driver 18 for SQL Server",
    encrypt: true,
    trust_server_certificate: true,
  };
}

export function profileUpdateRequest(draft: ConnectorProfileDraft): UpdateConnectorProfileRequest {
  const request: UpdateConnectorProfileRequest = {
    name: draft.name.trim(),
    public_config: profilePublicConfig(draft),
  };
  if (draft.username.trim() && draft.password) {
    request.secrets = {
      username: draft.username.trim(),
      password: draft.password,
    };
  }
  return request;
}

export function profileDraftFromProfile(profile: ConnectorProfile): ConnectorProfileDraft {
  if (profile.connector_type === "postgres") {
    return {
      connectorType: "postgres",
      name: profile.name,
      server: stringConfig(profile.public_config.host),
      port: stringConfig(profile.public_config.port) || "5432",
      database: stringConfig(profile.public_config.database),
      username: "",
      password: "",
      driver: "",
      customDriver: "",
      sslMode: stringConfig(profile.public_config.sslmode) || "prefer",
    };
  }
  const parsedServer = parseSqlServerServer(stringConfig(profile.public_config.server));
  const driver = stringConfig(profile.public_config.driver) || "ODBC Driver 18 for SQL Server";
  const knownDriver = driver === "ODBC Driver 18 for SQL Server" || driver === "ODBC Driver 17 for SQL Server";
  return {
    connectorType: "sql_server",
    name: profile.name,
    server: parsedServer.host,
    port: parsedServer.port || "1433",
    database: stringConfig(profile.public_config.database),
    username: "",
    password: "",
    driver: knownDriver ? driver : "custom",
    customDriver: knownDriver ? "" : driver,
    sslMode: "",
  };
}

function parseSqlServerServer(value: string): { host: string; port: string } {
  const [host, port] = value.split(",", 2);
  return { host: host?.trim() ?? "", port: port?.trim() ?? "" };
}

function stringConfig(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}
