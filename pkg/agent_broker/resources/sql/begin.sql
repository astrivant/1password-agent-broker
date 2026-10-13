-- Admit submission once, only while the request has neither cancellation nor a durable outcome.
UPDATE request_context SET attempted = 1
WHERE
    request_id = ? AND attempted = 0
    AND EXISTS (
        SELECT 1 FROM requests
        WHERE request_id = ? AND cancelled = 0 AND result IS NULL
    );
