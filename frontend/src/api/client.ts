// Typed API client mirroring the FastAPI routers one-to-one.
export type Role =
  | "system_admin"
  | "certification_admin"
  | "reviewer"
  | "auditor"
  | "report_viewer";

export interface Me {
  id: number;
  username: string | null;
  email: string | null;
  role: Role;
  must_change_password: boolean;
}

export interface Paged<T> {
  total: number;
  page: number;
  items: T[];
}

export interface Identity {
  id: number;
  employee_id: string;
  username: string | null;
  email: string | null;
  first_name: string | null;
  last_name: string | null;
  department: string | null;
  job_title: string | null;
  manager_id: number | null;
  is_active: boolean;
  source: string | null;
}

export interface IdentityInput {
  employee_id: string;
  username?: string | null;
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  department?: string | null;
  job_title?: string | null;
  manager_employee_id?: string | null;
  is_active?: boolean;
}

export interface Source {
  id: number;
  name: string;
  source_type: string | null;
  description: string | null;
  is_active: boolean;
  account_count: number;
  unlinked_count: number;
  connector?: ConnectorBlock;
}

export interface ConnectorBlock {
  configured: boolean;
  interval_minutes: number | null;
  next_sync_at: string | null;
  has_secret: boolean;
  last_run_status: string | null;
}

export interface SyncRunView {
  id: number;
  data_source_id: number;
  status: string;
  triggered_by: string;
  started_at: string | null;
  finished_at: string | null;
  stats: Record<string, number | string> | null;
  error: string | null;
}

export interface ConnectorInput {
  config: Record<string, string>;
  secret?: string;
  sync_interval_minutes?: number | null;
}

export interface Account {
  id: number;
  account_value: string;
  account_type: string | null;
  identity_id: number | null;
  entitlement_name: string | null;
  privilege_level: string | null;
  last_seen_at: string | null;
}

export interface Entitlement {
  id: number;
  catalog_id: string;
  name: string;
  description: string | null;
  privilege_level: string | null;
  source_id: number;
  last_seen_at: string | null;
}

export interface Campaign {
  id: number;
  name: string;
  status: string;
  review_mode: string;
  pending_reviews: number;
  deadline: string | null;
}

export interface CampaignDetail {
  id: number;
  name: string;
  description: string | null;
  status: string;
  review_mode: string;
  scope: Record<string, unknown>;
  deadline: string | null;
  total_reviews: number;
  completed_reviews: number;
}

export interface ReviewQueueItem {
  id: number;
  campaign_id: number;
  campaign_name: string;
  account_value: string;
  privilege_level: string | null;
  status: string;
}

export interface ReviewHistoryItem {
  id: number;
  campaign_name: string;
  account_value: string;
  decision: string | null;
  comments: string | null;
  completed_at: string | null;
}

export interface ReviewDetail {
  id: number;
  campaign_id: number;
  campaign_name: string;
  account_value: string;
  account_type: string | null;
  privilege_level: string | null;
  identity_employee_id: string | null;
  identity_name: string | null;
  sod_violations: SodViolation[];
  status: string;
  decision: string | null;
  comments: string | null;
}

export interface SodViolation {
  rule_id: number;
  rule_name: string;
  severity: string;
  entitlement_a: string;
  entitlement_b: string;
}

export interface SodRule {
  id: number;
  name: string;
  description: string | null;
  entitlement_a_id: number;
  entitlement_b_id: number;
  entitlement_a_name: string | null;
  entitlement_b_name: string | null;
  severity: string;
  is_active: boolean;
  created_at: string | null;
}

export interface SodRuleInput {
  name: string;
  description?: string | null;
  entitlement_a_id: number;
  entitlement_b_id: number;
  severity?: string;
  is_active?: boolean;
}

export interface AuditEntryView {
  id: number;
  ts: string | null;
  actor_username: string;
  action: string;
  entity_type: string;
  entity_id: number | null;
  details: string;
  record_hash: string;
}

export interface RemediationRule {
  id: number;
  name: string;
  description: string | null;
  data_source_id: number | null;
  privilege_level: string | null;
  entitlement_pattern: string | null;
  action: string;
  target: string | null;
  webhook_url: string | null;
  is_active: boolean;
  require_approval: boolean;
  times_triggered: number;
  times_executed: number;
  times_failed: number;
  created_at: string | null;
}

export interface RemediationRuleInput {
  name: string;
  description?: string | null;
  data_source_id?: number | null;
  privilege_level?: string | null;
  entitlement_pattern?: string | null;
  action?: string;
  target?: string | null;
  webhook_url?: string | null;
  is_active?: boolean;
  require_approval?: boolean | null;
}

export interface RemediationAction {
  id: number;
  review_id: number;
  rule_id: number | null;
  rule_name: string | null;
  account_id: number;
  action_type: string;
  status: string;
  requires_approval: boolean;
  approved_by_id: number | null;
  approved_at: string | null;
  attempts: number;
  result: string | null;
  executed_at: string | null;
  created_at: string | null;
  snapshot: {
    campaign_id?: number;
    campaign_name?: string;
    data_source_id?: number;
    data_source_name?: string;
    account_value?: string;
    account_type?: string;
    privilege_level?: string;
    entitlement_name?: string;
    identity_name?: string;
    target?: string;
    [key: string]: unknown;
  };
}

export interface ScimConfig {
  enabled: boolean;
  token_prefix: string | null;
  token_created_at: string | null;
}

export interface ScimTokenCreated {
  token: string;
  token_prefix: string;
}

export interface RemediationSettings {
  enabled: boolean;
  default_action: string;
  require_approval_for_high_risk: boolean;
}

export interface OutboxRow {
  id: number;
  campaign_id: number;
  review_id: number;
  reviewer_id: number;
  recipient: string | null;
  subject: string;
  due_at: string | null;
  sent_at: string | null;
  attempts: number;
  status: string;
  last_error: string | null;
  created_at: string | null;
}

export interface OutboxPage {
  items: OutboxRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface DashboardData {
  identities: number;
  accounts: number;
  unlinked_accounts: number;
  privileged_accounts: number;
  active_campaigns: number;
  my_pending_reviews: number;
}

export interface ChainStatus {
  valid: boolean;
  entries?: number;
  head?: string;
  broken_at?: number;
  reason?: string;
}

export interface RiskFactor {
  signal: string;
  contribution: number;
  detail: string;
}

export interface RiskTopIdentity {
  employee_id: string;
  name: string | null;
  score: number;
  band: string;
  top_factors: RiskFactor[];
}

export interface RiskSummary {
  run_id: string | null;
  run_at: string | null;
  scored_identities: number;
  average_score: number;
  band_distribution: Record<string, number>;
  top_risky: RiskTopIdentity[];
}

export interface RiskSnapshotRow {
  id: number;
  run_id: string;
  identity_id: number | null;
  employee_id: string;
  score: number;
  band: string;
  signals: Record<string, number>;
  name: string | null;
  department: string | null;
}

export interface RiskTrendPoint {
  run_id: string;
  score: number;
  band: string;
  signals: Record<string, number>;
  computed_at: string;
}

export interface CampaignReport {
  campaign: {
    id: number;
    name: string;
    description: string | null;
    status: string;
    review_mode: string;
    deadline: string | null;
    created_at: string | null;
  };
  generated_at: string;
  completion: {
    total: number;
    completed: number;
    pending: number;
    progress_pct: number;
  };
  decisions: Record<string, number>;
  reviewer_workload: Array<{
    reviewer: string;
    assigned: number;
    approved: number;
    revoked: number;
    pending: number;
  }>;
  revocations: Array<{
    identity: string | null;
    employee_id: string | null;
    account: string | null;
    entitlement: string | null;
    source: string | null;
    decided_at: string | null;
    reviewer: string | null;
    comment: string | null;
  }>;
  risk: {
    run_id: string;
    scored_in_campaign: number;
    band_distribution: Record<string, number>;
  } | null;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface CampaignPreviewItem {
  account_id: number;
  reviewer: string;
  sod_violations?: SodViolation[];
}

export interface CampaignPreview {
  total_in_scope: number;
  will_create: number;
  skipped: Array<{ account_id: number; account_value: string; reason: string }>;
  sample: CampaignPreviewItem[];
  sod: { identities_flagged: number; accounts_flagged: number };
}

export interface CampaignInput {
  name: string;
  description?: string | null;
  review_mode?: string;
  scope?: Record<string, unknown>;
  deadline?: string | null;
}

export interface ApiKeyRow {
  id: number;
  name: string;
  key_prefix: string;
  role: Role;
  is_active: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string | null;
}

export interface ApiKeyCreated extends ApiKeyRow {
  key: string;
}

export interface ApiKeyInput {
  name: string;
  role: string;
  expires_at?: string | null;
}

export const api = {
  auth: {
    login: (username: string, password: string) =>
      request<{ ok: boolean; role: Role }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      }),
    me: () => request<Me>("/api/auth/me"),
    logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
    changePassword: (current_password: string, new_password: string) =>
      request<{ ok: boolean }>("/api/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password, new_password }),
      }),
  },
  identities: {
    list: (params: { q?: string; department?: string; page?: number; page_size?: number }) =>
      request<Paged<Identity>>(`/api/identities?${toQuery(params)}`),
    get: (id: number) => request<Identity>(`/api/identities/${id}`),
    create: (input: IdentityInput) =>
      request<{ id: number }>("/api/identities", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    update: (id: number, input: IdentityInput) =>
      request<{ ok: boolean }>(`/api/identities/${id}`, {
        method: "PUT",
        body: JSON.stringify(input),
      }),
    remove: (id: number) =>
      request<{ ok: boolean }>(`/api/identities/${id}`, { method: "DELETE" }),
    importCsv: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return request<{ created: number; updated: number; errors: Array<{ line: number; error: string }> }>(
        "/api/identities/import",
        { method: "POST", body: fd },
      );
    },
    exportUrl: () => "/api/identities/export",
  },
  sources: {
    list: () => request<{ items: Source[] }>("/api/sources"),
    get: (id: number) => request<Source & { owner_employee_id?: string }>(`/api/sources/${id}`),
    create: (input: { name: string; source_type: string; description?: string | null; owner_employee_id?: string | null }) =>
      request<{ id: number }>("/api/sources", { method: "POST", body: JSON.stringify(input) }),
    remove: (id: number) => request<{ ok: boolean }>(`/api/sources/${id}`, { method: "DELETE" }),
    accounts: (id: number, params: { linked?: string; page?: number; page_size?: number }) =>
      request<Paged<Account>>(`/api/sources/${id}/accounts?${toQuery(params)}`),
    linkAccount: (sourceId: number, accountId: number, identityId: number) =>
      request<{ ok: boolean }>(`/api/sources/${sourceId}/accounts/${accountId}/link`, {
        method: "PUT",
        body: JSON.stringify({ identity_id: identityId }),
      }),
    bulkLink: (sourceId: number, matchOn: "username" | "email") =>
      request<{ linked: number; considered: number }>(`/api/sources/${sourceId}/accounts/bulk-link`, {
        method: "POST",
        body: JSON.stringify({ match_on: matchOn }),
      }),
    uploadCsv: (sourceId: number, file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return request<{ accounts_created: number; entitlements_created: number }>(
        `/api/sources/${sourceId}/upload`,
        { method: "POST", body: fd },
      );
    },
    configureConnector: (sourceId: number, input: ConnectorInput) =>
      request<{ ok: boolean; validated: boolean }>(`/api/sources/${sourceId}/connector`, {
        method: "PUT",
        body: JSON.stringify(input),
      }),
    syncNow: (sourceId: number) =>
      request<{ run_id: number }>(`/api/sources/${sourceId}/sync`, { method: "POST" }),
    syncs: (sourceId: number, params?: { page?: number; page_size?: number }) =>
      request<Paged<SyncRunView>>(`/api/sources/${sourceId}/syncs?${toQuery(params ?? {})}`),
  },
  syncs: {
    get: (runId: number) => request<SyncRunView>(`/api/syncs/${runId}`),
    cancel: (runId: number) =>
      request<{ ok: boolean; status: string }>(`/api/syncs/${runId}/cancel`, { method: "POST" }),
  },
  entitlements: {
    list: (params: { q?: string; privilege?: string; source_id?: number; page?: number; page_size?: number }) =>
      request<Paged<Entitlement>>(`/api/entitlements?${toQuery(params)}`),
    stats: () =>
      request<{ total: number; classified: number; unclassified: number; by_level: Record<string, number> }>(
        "/api/entitlements/stats",
      ),
    setPrivilege: (id: number, privilege_level: string) =>
      request<{ ok: boolean }>(`/api/entitlements/${id}/privilege`, {
        method: "PUT",
        body: JSON.stringify({ privilege_level }),
      }),
  },
  campaigns: {
    list: () => request<{ items: Campaign[] }>("/api/campaigns"),
    get: (id: number) => request<CampaignDetail>(`/api/campaigns/${id}`),
    create: (input: CampaignInput) =>
      request<{ id: number }>("/api/campaigns", { method: "POST", body: JSON.stringify(input) }),
    update: (id: number, input: CampaignInput) =>
      request<{ ok: boolean }>(`/api/campaigns/${id}`, { method: "PUT", body: JSON.stringify(input) }),
    remove: (id: number) => request<{ ok: boolean }>(`/api/campaigns/${id}`, { method: "DELETE" }),
    preview: (id: number) =>
      request<CampaignPreview>(`/api/campaigns/${id}/preview`, { method: "POST" }),
    stage: (id: number) => request<{ ok: boolean; status: string }>(`/api/campaigns/${id}/stage`, { method: "POST" }),
    start: (id: number) => request<{ reviews_created: number; skipped: number }>(`/api/campaigns/${id}/start`, { method: "POST" }),
    cancel: (id: number) => request<{ ok: boolean; status: string }>(`/api/campaigns/${id}/cancel`, { method: "POST" }),
    metrics: (id: number) =>
      request<{ campaign_id: number; status: string; by_status: Record<string, number>; total: number; completed: number; progress_pct: number }>(
        `/api/campaigns/${id}/metrics`,
      ),
    report: (id: number) =>
      request<CampaignReport>(`/api/campaigns/${id}/report`),
    reportCsvUrl: (id: number) => `/api/campaigns/${id}/report.csv`,
  },
  risk: {
    run: () =>
      request<{ run_id: string; scored_identities: number; average_score: number; band_distribution: Record<string, number> }>(
        "/api/risk/runs",
        { method: "POST" },
      ),
    summary: () => request<RiskSummary>("/api/risk/summary"),
    snapshots: (params: { run_id?: string; band?: string; department?: string; page?: number; page_size?: number }) =>
      request<Paged<RiskSnapshotRow> & { run_id: string | null }>(`/api/risk/snapshots?${toQuery(params)}`),
    trend: (identityId: number) =>
      request<{ identity_id: number; items: RiskTrendPoint[] }>(`/api/risk/trend/${identityId}`),
  },
  reviews: {
    queue: (params?: { page?: number; page_size?: number }) =>
      request<Paged<ReviewQueueItem> & { page: number }>(`/api/reviews/queue?${toQuery(params ?? {})}`),
    count: () => request<{ count: number }>("/api/reviews/count"),
    history: (params?: { page?: number; page_size?: number }) =>
      request<{ items: ReviewHistoryItem[] }>(`/api/reviews/history?${toQuery(params ?? {})}`),
    get: (id: number) => request<ReviewDetail>(`/api/reviews/${id}`),
    submit: (id: number, decision: "approve" | "revoke", comments?: string) =>
      request<{ ok: boolean }>(`/api/reviews/${id}/submit`, {
        method: "POST",
        body: JSON.stringify({ decision, comments }),
      }),
    bulkSubmit: (review_ids: number[], decision: "approve" | "revoke", comments?: string) =>
      request<{ submitted: number }>(`/api/reviews/bulk-submit`, {
        method: "POST",
        body: JSON.stringify({ review_ids, decision, comments }),
      }),
  },
  audit: {
    list: (params: { action?: string; entity_type?: string; page?: number; page_size?: number }) =>
      request<Paged<AuditEntryView>>("/api/audit?" + toQuery(params)),
    verify: () => request<ChainStatus>("/api/audit/verify"),
    exportUrl: () => "/api/audit/export",
  },
  dashboard: {
    get: () => request<DashboardData>("/api/dashboard"),
  },
  reminders: {
    outbox: (params: { campaign_id?: number; status?: string; page?: number; page_size?: number }) =>
      request<OutboxPage>("/api/reminders/outbox?" + toQuery(params)),
    campaign: (campaignId: number, params: { page?: number; page_size?: number }) =>
      request<OutboxPage & { by_status: Record<string, number> }>(`/api/reminders/campaigns/${campaignId}?` + toQuery(params)),
  },
  sod: {
    rules: () => request<{ items: SodRule[] }>("/api/sod/rules"),
    createRule: (input: SodRuleInput) =>
      request<{ id: number; name: string }>("/api/sod/rules", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    updateRule: (id: number, input: SodRuleInput) =>
      request<{ ok: boolean }>(`/api/sod/rules/${id}`, {
        method: "PUT",
        body: JSON.stringify(input),
      }),
    deleteRule: (id: number) =>
      request<{ ok: boolean }>(`/api/sod/rules/${id}`, { method: "DELETE" }),
  },
  remediation: {
    rules: () =>
      request<{ items: RemediationRule[] }>("/api/remediation/rules"),
    createRule: (input: RemediationRuleInput) =>
      request<{ id: number; name: string }>("/api/remediation/rules", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    updateRule: (id: number, input: RemediationRuleInput) =>
      request<{ ok: boolean }>(`/api/remediation/rules/${id}`, {
        method: "PUT",
        body: JSON.stringify(input),
      }),
    deleteRule: (id: number) =>
      request<{ ok: boolean }>(`/api/remediation/rules/${id}`, { method: "DELETE" }),
    actions: (params: { status?: string; campaign_id?: number; rule_id?: number; limit?: number }) =>
      request<{ items: RemediationAction[]; total: number }>(
        "/api/remediation/actions?" + toQuery(params),
      ),
    act: (id: number, op: "approve" | "cancel") =>
      request<{ ok: boolean; status: string }>(`/api/remediation/actions/${id}`, {
        method: "PUT",
        body: JSON.stringify({ op }),
      }),
    retry: (id: number) =>
      request<{ ok: boolean; attempts: number }>(`/api/remediation/actions/${id}/retry`, {
        method: "POST",
      }),
    settings: () =>
      request<RemediationSettings>("/api/remediation/settings"),
    updateSettings: (input: RemediationSettings) =>
      request<RemediationSettings>("/api/remediation/settings", {
        method: "PUT",
        body: JSON.stringify(input),
      }),
  },
  apiKeys: {
    list: () => request<{ items: ApiKeyRow[] }>("/api/api-keys"),
    create: (input: ApiKeyInput) =>
      request<ApiKeyCreated>("/api/api-keys", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    revoke: (id: number) =>
      request<{ ok: boolean; already_revoked: boolean }>(`/api/api-keys/${id}/revoke`, {
        method: "POST",
      }),
  },
  scim: {
    getConfig: () => request<ScimConfig>("/api/scim/config"),
    updateConfig: (enabled: boolean) =>
      request<ScimConfig>("/api/scim/config", {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      }),
    createToken: () =>
      request<ScimTokenCreated>("/api/scim/token", { method: "POST" }),
    revokeToken: () =>
      request<{ ok: boolean; already_revoked: boolean }>("/api/scim/token", {
        method: "DELETE",
      }),
  },
};

function toQuery(params: Record<string, unknown>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  return qs.toString();
}
