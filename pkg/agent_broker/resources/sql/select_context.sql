SELECT
    recovery_binding,
    attempted
FROM request_context
WHERE request_id = ?;
