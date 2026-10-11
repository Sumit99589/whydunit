"""mock ads platform (SIMULATED, Google-Ads-shaped) and live simulator state

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UP = """
CREATE SCHEMA IF NOT EXISTS mock_ads;

CREATE TABLE mock_ads.campaigns (
    id                     text PRIMARY KEY,
    name                   text NOT NULL,
    status                 text NOT NULL DEFAULT 'ENABLED',
    daily_budget_micros    bigint NOT NULL,
    demand_clicks_per_day  double precision NOT NULL,
    avg_cpc                double precision NOT NULL,
    ctr                    double precision NOT NULL,
    updated_at             timestamptz NOT NULL DEFAULT now()
);

-- Shaped like Google Ads change_event resources.
CREATE TABLE mock_ads.change_events (
    id                          bigserial PRIMARY KEY,
    change_date_time            timestamptz NOT NULL,
    campaign_id                 text NOT NULL REFERENCES mock_ads.campaigns(id),
    change_resource_type        text NOT NULL,
    resource_change_operation   text NOT NULL,
    changed_fields              text NOT NULL,
    old_resource                jsonb NOT NULL,
    new_resource                jsonb NOT NULL,
    user_email                  text NOT NULL,
    client_type                 text NOT NULL
);
CREATE INDEX mock_ads_change_events_ts ON mock_ads.change_events (change_date_time);

CREATE TABLE mock_ads.hourly_stats (
    campaign_id     text NOT NULL REFERENCES mock_ads.campaigns(id),
    hour            timestamptz NOT NULL,
    impressions     integer NOT NULL DEFAULT 0,
    clicks          integer NOT NULL DEFAULT 0,
    cost_micros     bigint NOT NULL DEFAULT 0,
    budget_limited  boolean NOT NULL DEFAULT false,
    PRIMARY KEY (campaign_id, hour)
);

CREATE TABLE mock_ads.settings (
    key    text PRIMARY KEY,
    value  jsonb NOT NULL
);
INSERT INTO mock_ads.settings (key, value) VALUES ('api_enabled', 'true');

CREATE SCHEMA IF NOT EXISTS sim;

CREATE TABLE sim.state (
    key         text PRIMARY KEY,
    value       jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sim.ticks (
    id            bigserial PRIMARY KEY,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    window_start  timestamptz NOT NULL,
    window_end    timestamptz NOT NULL,
    ok            boolean,
    summary       jsonb NOT NULL DEFAULT '{}'::jsonb,
    error         text
);

CREATE TABLE sim.health (
    id              bigserial PRIMARY KEY,
    ts              timestamptz NOT NULL DEFAULT now(),
    probe           text NOT NULL,
    ok              boolean NOT NULL,
    deployment_url  text,
    detail          jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX sim_health_ts ON sim.health (ts);
"""

DOWN = """
DROP SCHEMA sim CASCADE;
DROP SCHEMA mock_ads CASCADE;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
