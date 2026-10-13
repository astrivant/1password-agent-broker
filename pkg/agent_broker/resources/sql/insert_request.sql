INSERT INTO requests (request_id, principal, binding) VALUES (?, ?, ?)
ON CONFLICT (request_id) DO NOTHING;
