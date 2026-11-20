DELETE FROM identifiers
WHERE namespace='arxiv' AND value GLOB '[0-9][0-9][0-9][0-9].*'
AND CAST(substr(value,3,2) AS INTEGER) NOT BETWEEN 1 AND 12
AND EXISTS (SELECT 1 FROM works w WHERE w.id=identifiers.work_id
    AND json_extract(w.metadata,'$.arxiv_id') IS NULL
    AND lower(coalesce(json_extract(w.metadata,'$.doi'),'')) NOT LIKE '10.48550/arxiv.%'
    AND lower(json_extract(w.metadata,'$.doi')) LIKE '%' || identifiers.value);
