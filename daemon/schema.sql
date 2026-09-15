-- Nexus Fleet Database Schema
-- PostgreSQL 16 — event-driven via LISTEN/NOTIFY
-- Principle 1: Nothing is Deleted — append-only, status transitions, no DELETEs

-- ─── Conversations ───────────────────────────────────────────────

CREATE TABLE conversations (
    id              SERIAL PRIMARY KEY,
    chat_id         TEXT NOT NULL UNIQUE,          -- Telegram chat_id or internal channel
    type            TEXT NOT NULL DEFAULT 'group', -- group, private, channel, oracle
    title           TEXT,                          -- display name
    oracle_name     TEXT,                          -- linked oracle (FK to oracle_status)
    metadata        JSONB DEFAULT '{}',            -- flexible extra fields
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_conversations_oracle ON conversations (oracle_name) WHERE oracle_name IS NOT NULL;

-- ─── Messages ────────────────────────────────────────────────────

CREATE TYPE message_status AS ENUM ('pending', 'acknowledged', 'in_progress', 'completed', 'failed', 'cancelled');
CREATE TYPE message_type AS ENUM ('task', 'query', 'info', 'escalation', 'result', 'reply', 'broadcast', 'command');

CREATE TABLE messages (
    id              SERIAL PRIMARY KEY,
    msg_id          TEXT NOT NULL UNIQUE,          -- human-readable ID: MSG-NEXUS-001
    from_oracle     TEXT NOT NULL,                 -- sending oracle name or 'human'
    to_oracle       TEXT NOT NULL,                 -- receiving oracle name or 'human'
    type            message_type NOT NULL DEFAULT 'info',
    status          message_status NOT NULL DEFAULT 'pending',
    content         TEXT NOT NULL,                 -- message body
    content_json    JSONB DEFAULT '{}',            -- structured payload (tasks, polls, etc.)
    respond_in      TEXT,                          -- Telegram chat_id for reply routing
    reply_to_msg_id TEXT,                          -- reply chain
    conversation_id INTEGER REFERENCES conversations(id),
    priority        INTEGER NOT NULL DEFAULT 0,    -- 0=normal, 1=high, 2=urgent
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ack_at          TIMESTAMPTZ,                   -- when acknowledged
    completed_at    TIMESTAMPTZ                    -- when completed
);

CREATE INDEX idx_messages_from ON messages (from_oracle, status);
CREATE INDEX idx_messages_to ON messages (to_oracle, status);
CREATE INDEX idx_messages_status ON messages (status, created_at);
CREATE INDEX idx_messages_created ON messages (created_at DESC);
CREATE INDEX idx_messages_conversation ON messages (conversation_id);

-- ─── Goals ───────────────────────────────────────────────────────

CREATE TYPE goal_status AS ENUM ('active', 'paused', 'completed', 'archived', 'cancelled');

CREATE TABLE goals (
    id              SERIAL PRIMARY KEY,
    goal_id         TEXT NOT NULL UNIQUE,          -- human-readable: GOAL-001
    title           TEXT NOT NULL,
    description     TEXT,
    oracle_owner    TEXT NOT NULL,                 -- primary oracle responsible
    status          goal_status NOT NULL DEFAULT 'active',
    progress_pct    INTEGER NOT NULL DEFAULT 0 CHECK (progress_pct >= 0 AND progress_pct <= 100),
    priority        INTEGER NOT NULL DEFAULT 0,
    tags            TEXT[] DEFAULT '{}',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_goals_owner ON goals (oracle_owner, status);
CREATE INDEX idx_goals_status ON goals (status, priority DESC);
CREATE INDEX idx_goals_tags ON goals USING gin (tags);

-- ─── Tasks ───────────────────────────────────────────────────────

CREATE TYPE task_status AS ENUM ('pending', 'assigned', 'in_progress', 'blocked', 'completed', 'cancelled');

CREATE TABLE tasks (
    id              SERIAL PRIMARY KEY,
    task_id         TEXT NOT NULL UNIQUE,          -- human-readable: TASK-001
    goal_id         TEXT NOT NULL REFERENCES goals(goal_id),
    title           TEXT NOT NULL,
    description     TEXT,
    assigned_oracle TEXT,                          -- NULL until assigned
    status          task_status NOT NULL DEFAULT 'pending',
    priority        INTEGER NOT NULL DEFAULT 0,
    depends_on      INTEGER[] DEFAULT '{}',        -- task IDs this depends on
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_tasks_goal ON tasks (goal_id, status);
CREATE INDEX idx_tasks_oracle ON tasks (assigned_oracle, status);
CREATE INDEX idx_tasks_status ON tasks (status, priority DESC);

-- ─── Goal Progress Log (append-only) ─────────────────────────────

CREATE TABLE goal_progress_log (
    id              SERIAL PRIMARY KEY,
    goal_id         TEXT NOT NULL REFERENCES goals(goal_id),
    task_id         TEXT REFERENCES tasks(task_id),
    oracle_name     TEXT NOT NULL,
    progress_pct    INTEGER,                       -- snapshot at this point
    note            TEXT NOT NULL,                  -- what happened
    evidence        TEXT,                          -- link to artifact or report
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_progress_goal ON goal_progress_log (goal_id, created_at DESC);
CREATE INDEX idx_progress_oracle ON goal_progress_log (oracle_name, created_at DESC);

-- ─── Oracle Status ───────────────────────────────────────────────

CREATE TYPE oracle_state AS ENUM ('online', 'offline', 'busy', 'idle', 'error');

CREATE TABLE oracle_status (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,          -- oracle name (emily, nexus, dev, etc.)
    fleet_id        TEXT,                          -- 00-emily, 02-nexus, etc.
    state           oracle_state NOT NULL DEFAULT 'offline',
    last_seen       TIMESTAMPTZ,
    session_count   INTEGER NOT NULL DEFAULT 0,
    active_goals    INTEGER NOT NULL DEFAULT 0,
    active_tasks    INTEGER NOT NULL DEFAULT 0,
    workload_pct    INTEGER NOT NULL DEFAULT 0 CHECK (workload_pct >= 0 AND workload_pct <= 100),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── Activity Log (append-only) ──────────────────────────────────

CREATE TYPE activity_type AS ENUM (
    'message_sent', 'message_ack', 'message_completed',
    'goal_created', 'goal_updated', 'goal_completed',
    'task_created', 'task_assigned', 'task_started', 'task_completed', 'task_blocked',
    'oracle_online', 'oracle_offline', 'oracle_busy', 'oracle_idle',
    'session_start', 'session_end',
    'error', 'warning'
);

CREATE TABLE activity_log (
    id              SERIAL PRIMARY KEY,
    activity_type   activity_type NOT NULL,
    oracle_name     TEXT NOT NULL,
    entity_type     TEXT,                          -- 'message', 'goal', 'task', 'oracle'
    entity_id       TEXT,                          -- reference ID
    detail          TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_activity_oracle ON activity_log (oracle_name, created_at DESC);
CREATE INDEX idx_activity_type ON activity_log (activity_type, created_at DESC);
CREATE INDEX idx_activity_entity ON activity_log (entity_type, entity_id);
CREATE INDEX idx_activity_created ON activity_log (created_at DESC);

-- ─── NOTIFY Triggers ─────────────────────────────────────────────

-- Notify on message changes (INSERT or status change)
CREATE OR REPLACE FUNCTION notify_message_change()
RETURNS TRIGGER AS $$
DECLARE
    channel TEXT;
    payload JSONB;
BEGIN
    channel := 'message_change';
    payload := jsonb_build_object(
        'op', TG_OP,
        'msg_id', COALESCE(NEW.msg_id, OLD.msg_id),
        'from_oracle', COALESCE(NEW.from_oracle, OLD.from_oracle),
        'to_oracle', COALESCE(NEW.to_oracle, OLD.to_oracle),
        'status', COALESCE(NEW.status::text, OLD.status::text),
        'type', COALESCE(NEW.type::text, OLD.type::text),
        'timestamp', now()
    );
    PERFORM pg_notify(channel, payload::text);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_message_notify
    AFTER INSERT OR UPDATE OF status ON messages
    FOR EACH ROW EXECUTE FUNCTION notify_message_change();

-- Notify on goal progress changes
CREATE OR REPLACE FUNCTION notify_goal_progress()
RETURNS TRIGGER AS $$
DECLARE
    channel TEXT;
    payload JSONB;
BEGIN
    channel := 'goal_progress';
    payload := jsonb_build_object(
        'op', TG_OP,
        'goal_id', COALESCE(NEW.goal_id, OLD.goal_id),
        'title', COALESCE(NEW.title, OLD.title),
        'status', COALESCE(NEW.status::text, OLD.status::text),
        'progress_pct', COALESCE(NEW.progress_pct, OLD.progress_pct),
        'timestamp', now()
    );
    PERFORM pg_notify(channel, payload::text);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_goal_progress_notify
    AFTER INSERT OR UPDATE OF status, progress_pct ON goals
    FOR EACH ROW EXECUTE FUNCTION notify_goal_progress();

-- Notify on goal progress log inserts
CREATE OR REPLACE FUNCTION notify_progress_log()
RETURNS TRIGGER AS $$
DECLARE
    payload JSONB;
BEGIN
    payload := jsonb_build_object(
        'op', 'INSERT',
        'goal_id', NEW.goal_id,
        'task_id', NEW.task_id,
        'oracle_name', NEW.oracle_name,
        'progress_pct', NEW.progress_pct,
        'note', NEW.note,
        'timestamp', NEW.created_at
    );
    PERFORM pg_notify('goal_progress', payload::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_progress_log_notify
    AFTER INSERT ON goal_progress_log
    FOR EACH ROW EXECUTE FUNCTION notify_progress_log();

-- Notify on oracle status changes
CREATE OR REPLACE FUNCTION notify_oracle_state()
RETURNS TRIGGER AS $$
DECLARE
    payload JSONB;
BEGIN
    payload := jsonb_build_object(
        'op', TG_OP,
        'name', COALESCE(NEW.name, OLD.name),
        'state', COALESCE(NEW.state::text, OLD.state::text),
        'workload_pct', COALESCE(NEW.workload_pct, OLD.workload_pct),
        'timestamp', now()
    );
    PERFORM pg_notify('oracle_state', payload::text);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_oracle_state_notify
    AFTER INSERT OR UPDATE OF state, workload_pct ON oracle_status
    FOR EACH ROW EXECUTE FUNCTION notify_oracle_state();

-- Notify on activity log inserts (for real-time event stream)
CREATE OR REPLACE FUNCTION notify_activity()
RETURNS TRIGGER AS $$
DECLARE
    payload JSONB;
BEGIN
    payload := jsonb_build_object(
        'activity_type', NEW.activity_type,
        'oracle_name', NEW.oracle_name,
        'entity_type', NEW.entity_type,
        'entity_id', NEW.entity_id,
        'detail', NEW.detail,
        'timestamp', NEW.created_at
    );
    PERFORM pg_notify('activity', payload::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_activity_notify
    AFTER INSERT ON activity_log
    FOR EACH ROW EXECUTE FUNCTION notify_activity();

-- ─── Helper Functions ────────────────────────────────────────────

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_messages_updated_at
    BEFORE UPDATE ON messages
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_goals_updated_at
    BEFORE UPDATE ON goals
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_oracle_status_updated_at
    BEFORE UPDATE ON oracle_status
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

-- Record activity on message lifecycle changes
CREATE OR REPLACE FUNCTION log_message_activity()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO activity_log (activity_type, oracle_name, entity_type, entity_id, detail)
    VALUES (
        CASE
            WHEN NEW.status = 'acknowledged' THEN 'message_ack'::activity_type
            WHEN NEW.status = 'completed' THEN 'message_completed'::activity_type
            ELSE 'message_sent'::activity_type
        END,
        NEW.to_oracle,
        'message',
        NEW.msg_id,
        'Message from ' || NEW.from_oracle || ' to ' || NEW.to_oracle || ' [' || NEW.status || ']'
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_log_message_activity
    AFTER INSERT OR UPDATE OF status ON messages
    FOR EACH ROW EXECUTE FUNCTION log_message_activity();

-- Record activity on goal changes
CREATE OR REPLACE FUNCTION log_goal_activity()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO activity_log (activity_type, oracle_name, entity_type, entity_id, detail)
    VALUES (
        CASE
            WHEN TG_OP = 'INSERT' THEN 'goal_created'::activity_type
            WHEN NEW.status = 'completed' AND (OLD.status IS NULL OR OLD.status != 'completed')
                THEN 'goal_completed'::activity_type
            ELSE 'goal_updated'::activity_type
        END,
        NEW.oracle_owner,
        'goal',
        NEW.goal_id,
        'Goal: ' || NEW.title || ' [' || NEW.progress_pct || '%]'
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_log_goal_activity
    AFTER INSERT OR UPDATE OF status, progress_pct ON goals
    FOR EACH ROW EXECUTE FUNCTION log_goal_activity();
