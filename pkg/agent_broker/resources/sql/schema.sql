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
