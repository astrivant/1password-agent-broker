CREATE TABLE IF NOT EXISTS requests (
    request_id TEXT PRIMARY KEY,
    principal TEXT NOT NULL,
    binding TEXT NOT NULL,
    result TEXT,
    cancelled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS request_context (
    request_id TEXT PRIMARY KEY REFERENCES requests (request_id),
    recovery_binding TEXT NOT NULL,
    attempted INTEGER NOT NULL DEFAULT 0
);
