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
};

function toQuery(params: Record<string, unknown>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  return qs.toString();
}
