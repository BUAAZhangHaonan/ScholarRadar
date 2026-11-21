UPDATE proposals SET definition=json_set(definition,'$.method','same_direction_work_count','$.measure_description','同方向其他作品数量；不表示支持同一主张')
WHERE json_extract(definition,'$.method')='independent_support';
UPDATE proposals SET lifecycle='retired' WHERE json_extract(definition,'$.method')='has_located_evidence'
AND json_extract(definition,'$.target')='阅读后能否明确说出研究判断的变化' AND lifecycle='proposed';
