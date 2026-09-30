-- Phase 4: Freigabe-Knopf. Ein Angebot = eine neue Version eines Dienstes.
-- Der Telegram-Knopf traegt nur die id; Dienst und Version liest der Server von hier.
CREATE TABLE IF NOT EXISTS update_angebote (
    id               BIGSERIAL PRIMARY KEY,
    dienst           TEXT NOT NULL CHECK (dienst IN ('n8n', 'litellm')),
    version_alt      TEXT NOT NULL,
    version_neu      TEXT NOT NULL CHECK (version_neu ~ '^v?[0-9]+\.[0-9]+\.[0-9]+$'),
    release_url      TEXT,
    release_datum    TIMESTAMPTZ,
    zusammenfassung  TEXT,
    status           TEXT NOT NULL DEFAULT 'neu' CHECK (status IN (
                         'neu', 'offen', 'laeuft', 'erledigt', 'fehler', 'simulation_rot',
                         'spaeter', 'uebersprungen', 'ersetzt')),
    ersetzt_durch    BIGINT REFERENCES update_angebote(id),
    erinnern_ab      TIMESTAMPTZ,
    message_id       BIGINT,
    laeuft_seit      TIMESTAMPTZ,
    ergebnis         TEXT,
    gemeldet         BOOLEAN NOT NULL DEFAULT true,   -- false: Agent muss Ergebnis/Hinweis/Ersetzung noch melden
    erstellt         TIMESTAMPTZ NOT NULL DEFAULT now(),
    aktualisiert     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dienst, version_neu)
);
CREATE INDEX IF NOT EXISTS update_angebote_status_idx ON update_angebote (status);
