-- Preserve the first reservation so competing callers cannot overwrite its owner or binding.
INSERT INTO requests (request_id, principal, binding) VALUES (?, ?, ?)
ON CONFLICT (request_id) DO NOTHING;
