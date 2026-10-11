SELECT
    principal,
    binding,
    result,
    cancelled
FROM requests
WHERE request_id = ?;
