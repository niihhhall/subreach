-- Training tables used by the Neural Intelligence (Training) dashboard.
-- Apply via the Supabase SQL editor or `supabase db push`.

-- Neural Brain: dynamic rules injected from the dashboard and consumed by the agent.
CREATE TABLE IF NOT EXISTS dynamic_training (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  category text NOT NULL DEFAULT 'sales',
  subcategory text,
  scenario text NOT NULL,
  ideal_response text NOT NULL,
  trigger_keywords text[] DEFAULT '{}',
  priority integer NOT NULL DEFAULT 1,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dynamic_training_active   ON dynamic_training(is_active);
CREATE INDEX IF NOT EXISTS idx_dynamic_training_priority ON dynamic_training(priority DESC);

-- Real-time training pool: auto-captured conversations awaiting human audit.
CREATE TABLE IF NOT EXISTS training_data (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
  score integer DEFAULT 0,
  outcome text,
  manual_score integer,
  feedback text,
  is_reviewed boolean NOT NULL DEFAULT false,
  payload jsonb,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_training_data_lead_id    ON training_data(lead_id);
CREATE INDEX IF NOT EXISTS idx_training_data_created_at ON training_data(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_training_data_reviewed   ON training_data(is_reviewed);

-- NOTE ON ACCESS:
-- This matches migration 001 (no Row Level Security), so the frontend anon key can
-- read/write these tables directly. If you enable RLS on the project, add policies
-- that allow the dashboard's anon role to SELECT training_data and dynamic_training,
-- and restrict writes to the service role used by the FastAPI backend.
