/**
 * Typed mirrors of the Phase-1 admin contracts
 * (`news_collector/contracts/admin.py`). Field-for-field copies of the
 * Pydantic models; the backend contract tests are the source of truth and
 * the runtime responses validate these shapes on every fetch.
 */

export interface AdminSource {
  id: string;
  name: string;
}

export interface AdminArticleListItem {
  id: number;
  title: string;
  summary: string | null;
  url: string;
  source: AdminSource;
  category: string | null;
  topics: string[];
  published_at: string | null;
  collected_at: string | null;
  final_score: number | null;
  score_components: Record<string, number | null> | null;
  why_ranked: string[];
  processing_status: string | null;
  error_message: string | null;
  published_url: string | null;
  refinery_id: string | null;
  publishable: boolean;
  export_score: number | null;
}

export interface AdminArticleDetail extends AdminArticleListItem {
  content: string | null;
  cluster_id: string | null;
  article_metadata: Record<string, unknown>;
  publication: Record<string, unknown>;
  audit: Record<string, unknown>;
  latest_score: number | null;
  latest_score_explanation: Record<string, unknown> | null;
}

export interface AdminPagination {
  next_cursor: string | null;
  has_more: boolean;
  page_size: number;
  returned: number;
}

export interface AdminArticleListEnvelope {
  data: AdminArticleListItem[];
  pagination: AdminPagination;
  filters: { status: string; source: string[] };
  meta: { generated_at: string };
}

export interface AdminSourceHealthEnvelope {
  sources: Array<Record<string, unknown>>;
}

export interface AdminAnalyticsEnvelope {
  stats: Array<Record<string, unknown>>;
  total_articles: number;
  source_perf: Array<Record<string, unknown>>;
  avg_score_overall: number;
  dist: Record<string, unknown>;
  cats: Array<Record<string, unknown>>;
  top_sources: Array<Record<string, unknown>>;
  as_of: string;
}

export interface AdminConfigSnapshot {
  environment: string;
  debug: boolean;
  timezone: string;
  github: Record<string, unknown>;
  ollama: Record<string, unknown>;
  scoring: Record<string, unknown>;
  sources: Array<Record<string, unknown>>;
  meta?: Record<string, unknown>;
}

export interface AdminMutationResult {
  status: "ok" | "not_found" | "noop";
  detail: string;
  updated: number;
}

export type ArticleStatus =
  | "new"
  | "pending"
  | "publishing"
  | "rejected"
  | "completed";

export const ARTICLE_STATUSES: ArticleStatus[] = [
  "pending",
  "publishing",
  "rejected",
  "completed",
];

export interface AdminCollectStarted {
  run_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";
  detail: string;
}

export interface AdminCollectStatus {
  run_id: string | null;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  summary: Record<string, unknown>;
  active: boolean;
}

export interface AdminPublishStarted {
  run_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";
  detail: string;
}

export interface AdminPublishStatus {
  run_id: string | null;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  summary: Record<string, unknown>;
  active: boolean;
  pr_url: string | null;
  failure_class: string | null;
  final_slug: string | null;
}

export interface AdminSourceListItem {
  source_id: string;
  name: string | null;
  url: string | null;
  category: string | null;
  content_mode: string | null;
  enrichment_strategy: string | null;
  is_active: boolean;
  circuit: Record<string, unknown> | null;
}

export interface AdminPromptsEnvelope {
  prompts: Record<string, Record<string, unknown>>;
}

export interface AdminContentEnvelope {
  source_label: string;
  freshness_label: string;
  articles: Array<{
    file_name: string;
    title: string;
    refinery_id: string | null;
    modified_at: string;
  }>;
}

export interface AdminImageBriefItem {
  slug: string;
  article_id: string;
  status: string;
  reason: string;
  topic: string;
  news_angle: string | null;
  scientific_domain: string | null;
  subject_scene: string | null;
  draft_alt_text: string | null;
  tone: string | null;
  updated_at: string | null;
}

export interface AdminBulkResetResult {
  succeeded: string[];
  failed: Array<{ refinery_id: string; error: string }>;
  summary: string;
}

export interface AdminImageBriefUploadResult {
  brief: Record<string, unknown>;
  asset_path: string;
}

export interface AdminSourceUpsertPayload {
  source_id: string;
  name: string;
  url: string;
  credibility_score: number;
  category: string;
  update_frequency: string;
  group: string;
}
