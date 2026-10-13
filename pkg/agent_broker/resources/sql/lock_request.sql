-- Acquire the request write lock before reading cancellation or changing submission state.
UPDATE requests SET result = result
WHERE request_id = ?;
