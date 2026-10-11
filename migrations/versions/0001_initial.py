"""initial schema: ingest, cases, evidence, verdicts, fixes, llm cost, and Acme's own tables

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UP = """
CREATE TABLE projects (
    id            text PRIMARY KEY,
    name          text NOT NULL,
    api_key_hash  text NOT NULL UNIQUE,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    id            text PRIMARY KEY,
    project_id    text NOT NULL REFERENCES projects(id),
    anon_id       text,
    user_id       text,
    started_at    timestamptz NOT NULL,
    last_seen_at  timestamptz NOT NULL,
    browser       text, os text, device text, viewport text,
    country       text,
    channel       text,
    utm_source    text, utm_medium text, utm_campaign text,
    landing_path  text,
    synthetic     boolean NOT NULL DEFAULT false,
    has_replay    boolean NOT NULL DEFAULT false
);
CREATE INDEX sessions_project_started ON sessions (project_id, started_at);

CREATE TABLE events (
    id            bigserial PRIMARY KEY,
    event_id      text NOT NULL,
    project_id    text NOT NULL REFERENCES projects(id),
    name          text NOT NULL,
    ts            timestamptz NOT NULL,
    received_at   timestamptz NOT NULL DEFAULT now(),
    session_id    text,
    anon_id       text,
    user_id       text,
    path          text,
    browser       text, os text, device text, viewport text,
    country       text,
    channel       text,
    props         jsonb NOT NULL DEFAULT '{}'::jsonb,
    synthetic     boolean NOT NULL DEFAULT false,
    UNIQUE (project_id, event_id)
);
CREATE INDEX events_project_name_ts ON events (project_id, name, ts);
CREATE INDEX events_session ON events (session_id);

CREATE TABLE replays (
    id            text PRIMARY KEY,
    project_id    text NOT NULL REFERENCES projects(id),
    session_id    text NOT NULL,
    chunk_index   integer NOT NULL,
    started_at    timestamptz,
    ended_at      timestamptz,
    blob_key      text NOT NULL,
    size_bytes    integer NOT NULL,
    event_count   integer NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, chunk_index)
);
CREATE INDEX replays_project_started ON replays (project_id, started_at);

CREATE TABLE deployments_cache (
    id            text PRIMARY KEY,
    project_id    text NOT NULL,
    provider      text NOT NULL,
    url           text NOT NULL,
    git_sha       text,
    git_ref       text,
    state         text,
    created_at    timestamptz NOT NULL,
    ready_at      timestamptz,
    meta          jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX deployments_project_created ON deployments_cache (project_id, created_at);

CREATE TABLE cases (
    id             text PRIMARY KEY,
    project_id     text,
    world          text NOT NULL,
    metric         text NOT NULL,
    question       text NOT NULL,
    window_start   timestamptz NOT NULL,
    window_end     timestamptz NOT NULL,
    baseline_start timestamptz NOT NULL,
    baseline_end   timestamptz NOT NULL,
    status         text NOT NULL DEFAULT 'investigating',
    auto_opened    boolean NOT NULL DEFAULT false,
    cost_usd       double precision NOT NULL DEFAULT 0,
    summary        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cases_created ON cases (created_at DESC);

CREATE TABLE case_events (
    id         bigserial PRIMARY KEY,
    case_id    text NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    seq        integer NOT NULL,
    ts         timestamptz NOT NULL DEFAULT clock_timestamp(),
    type       text NOT NULL,
    actor      text,
    payload    jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (case_id, seq)
);

CREATE TABLE evidence (
    id            text PRIMARY KEY,
    case_id       text NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    kind          text NOT NULL,
    connector     text NOT NULL,
    tier          integer NOT NULL,
    detective     text,
    query         jsonb NOT NULL DEFAULT '{}'::jsonb,
    window_start  timestamptz,
    window_end    timestamptz,
    data_ref      jsonb NOT NULL DEFAULT '{}'::jsonb,
    summary       text NOT NULL,
    artifacts     jsonb NOT NULL DEFAULT '[]'::jsonb,
    confidence    double precision,
    fetched_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX evidence_case ON evidence (case_id);

CREATE TABLE hypotheses (
    id             text PRIMARY KEY,
    case_id        text NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    statement      text NOT NULL,
    effect         jsonb NOT NULL DEFAULT '{}'::jsonb,
    supporting     text[] NOT NULL DEFAULT '{}',
    contradicting  text[] NOT NULL DEFAULT '{}',
    status         text NOT NULL DEFAULT 'open',
    created_by     text,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE findings (
    id            text PRIMARY KEY,
    case_id       text NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    detective     text NOT NULL,
    claim         text NOT NULL,
    kind          text NOT NULL,
    evidence_ids  text[] NOT NULL DEFAULT '{}',
    metrics_refs  jsonb NOT NULL DEFAULT '{}'::jsonb,
    confidence    double precision,
    status        text NOT NULL DEFAULT 'accepted',
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE verdicts (
    id           text PRIMARY KEY,
    case_id      text NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    kind         text NOT NULL,
    narrative    text NOT NULL,
    causes       jsonb NOT NULL DEFAULT '[]'::jsonb,
    unexplained  jsonb NOT NULL DEFAULT '{}'::jsonb,
    not_checked  jsonb NOT NULL DEFAULT '[]'::jsonb,
    actions      jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE fixes (
    id             text PRIMARY KEY,
    case_id        text NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    hypothesis_id  text,
    type           text NOT NULL,
    status         text NOT NULL DEFAULT 'proposed',
    title          text NOT NULL,
    detail         jsonb NOT NULL DEFAULT '{}'::jsonb,
    pr_url         text,
    preview_url    text,
    approved_at    timestamptz,
    applied_at     timestamptz,
    verified_at    timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE llm_calls (
    id                 bigserial PRIMARY KEY,
    case_id            text,
    role               text NOT NULL,
    model              text NOT NULL,
    prompt_tokens      integer NOT NULL,
    completion_tokens  integer NOT NULL,
    cost_usd           double precision NOT NULL,
    latency_s          double precision NOT NULL,
    cached             boolean NOT NULL,
    tag                text,
    ts                 timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX llm_calls_case ON llm_calls (case_id);

-- Acme's own application data (the sandbox startup). Acme writes these; Whydunit only reads them.
CREATE SCHEMA IF NOT EXISTS acme;

CREATE TABLE acme.users (
    id          text PRIMARY KEY,
    email       text NOT NULL,
    name        text,
    country     text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    synthetic   boolean NOT NULL DEFAULT false
);

CREATE TABLE acme.payment_attempts (
    id                   text PRIMARY KEY,
    user_id              text,
    created_at           timestamptz NOT NULL DEFAULT now(),
    amount_cents         integer NOT NULL,
    currency             text NOT NULL DEFAULT 'usd',
    provider             text NOT NULL,          -- 'stripe' or 'mock'
    stripe_customer      text,
    stripe_subscription  text,
    stripe_payment_intent text,
    outcome              text NOT NULL,          -- succeeded | declined | error
    decline_code         text,
    card_country         text,
    card_brand           text,
    synthetic            boolean NOT NULL DEFAULT false
);
CREATE INDEX acme_payment_attempts_created ON acme.payment_attempts (created_at);

CREATE TABLE acme.helpdesk_tickets (
    id          bigserial PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    email       text,
    name        text,
    subject     text NOT NULL,
    body        text NOT NULL,
    channel     text NOT NULL DEFAULT 'contact_form',
    meta        jsonb NOT NULL DEFAULT '{}'::jsonb,
    synthetic   boolean NOT NULL DEFAULT false
);
CREATE INDEX acme_helpdesk_created ON acme.helpdesk_tickets (created_at);

CREATE TABLE acme.reviews (
    id          bigserial PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    platform    text NOT NULL,
    rating      integer NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title       text,
    body        text NOT NULL,
    author      text,
    synthetic   boolean NOT NULL DEFAULT false
);
CREATE INDEX acme_reviews_created ON acme.reviews (created_at);
"""

DOWN = """
DROP SCHEMA acme CASCADE;
DROP TABLE llm_calls, fixes, verdicts, findings, hypotheses, evidence, case_events, cases,
    deployments_cache, replays, events, sessions, projects CASCADE;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
