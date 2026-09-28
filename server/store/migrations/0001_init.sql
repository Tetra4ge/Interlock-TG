CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY,               -- sha256
  company_id TEXT,
  doc_type TEXT NOT NULL,
  fiscal_year TEXT,
  source_url TEXT,
  file_path TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'registered',  -- registered|parsed|extracted|failed
  error TEXT
);

CREATE TABLE IF NOT EXISTS fetch_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id TEXT, doc_type TEXT, fiscal_year TEXT,
  url TEXT, attempted_at TEXT, http_status INTEGER, outcome TEXT, error TEXT
);

CREATE TABLE IF NOT EXISTS sections (
  doc_id TEXT, kind TEXT, page_start INTEGER, page_end INTEGER,
  PRIMARY KEY (doc_id, kind, page_start)
);

CREATE TABLE IF NOT EXISTS extraction_runs (
  run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT,
  model TEXT, prompt_version TEXT, git_commit TEXT, notes TEXT
);

CREATE TABLE IF NOT EXISTS records (
  record_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  doc_id TEXT NOT NULL,
  record_type TEXT NOT NULL,             -- director|shareholding|rpt|auditor|subsidiary|regulatory
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL,                  -- accepted|rejected|review|fixed
  reason TEXT
);

CREATE TABLE IF NOT EXISTS review_queue (
  record_id TEXT PRIMARY KEY,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  decided_at TEXT, decision TEXT, decided_payload_json TEXT
);

CREATE TABLE IF NOT EXISTS entities (
  entity_id TEXT PRIMARY KEY,            -- "P:<din>" | "C:<cin>" | "A:<frn>" | "P:x<hash>" fallback
  kind TEXT NOT NULL,                    -- person|company|audit_firm
  canonical_name TEXT NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]'
);

-- Entity-name search (TigerGraph has no built-in full-text index) - rebuilt from `entities` by the build
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
  entity_id UNINDEXED, kind UNINDEXED, name, aliases
);

CREATE TABLE IF NOT EXISTS merge_log (
  mention_id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL,
  method TEXT NOT NULL,                  -- din|cin|frn|exact_name|fuzzy|manual
  score REAL,
  reason TEXT
);

CREATE TABLE IF NOT EXISTS questions (
  qid TEXT PRIMARY KEY,
  version TEXT NOT NULL,
  question TEXT NOT NULL,
  category TEXT NOT NULL,
  answer_type TEXT NOT NULL,
  gold_answer_json TEXT NOT NULL,
  gold_evidence_json TEXT NOT NULL,
  split TEXT NOT NULL,                   -- dev|test
  difficulty TEXT,
  template_id TEXT,
  verified INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  pipeline TEXT NOT NULL,
  split TEXT NOT NULL,
  question_version TEXT NOT NULL,
  config_json TEXT NOT NULL,
  git_commit TEXT,
  started_at TEXT, finished_at TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS results (
  run_id TEXT, qid TEXT,
  answer_json TEXT NOT NULL,             -- full AnswerResult
  PRIMARY KEY (run_id, qid)
);

CREATE TABLE IF NOT EXISTS scores (
  run_id TEXT, qid TEXT,
  correct REAL,                          -- 0..1 (F1 for sets)
  faithfulness REAL,
  citation_accuracy REAL,
  evidence_recall REAL,
  abstention_ok INTEGER,
  failure_label TEXT,
  judge_reason TEXT,
  PRIMARY KEY (run_id, qid)
);

CREATE TABLE IF NOT EXISTS traces (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT, pipeline TEXT, step INTEGER, kind TEXT, name TEXT,
  input_summary TEXT, output_summary TEXT,
  tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL, latency_ms INTEGER, error TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cache_key TEXT, role TEXT, provider TEXT, model TEXT,
  tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL, latency_ms INTEGER,
  cache_hit INTEGER, error TEXT, created_at TEXT
);
