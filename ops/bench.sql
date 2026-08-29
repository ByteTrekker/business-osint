-- Benchmark zapytań grafowych. Uruchamiać po `make seed`.
-- Cel: pokazać, że przy realnych wolumenach 1-3 poziomy mieszczą się w budżecie
-- czasowym (<100 ms dla depth 2 na ciepłym cache).

\timing on

-- Rozkład stopni węzłów — pokazuje huby, które trzeba przycinać.
SELECT
    width_bucket(degree, 0, 500, 10) AS bucket,
    min(degree) AS min_degree,
    max(degree) AS max_degree,
    count(*) AS entities
FROM entities
GROUP BY bucket
ORDER BY bucket;

-- Top 20 hubów.
SELECT e.entity_type, e.display_name, e.degree
FROM entities e
ORDER BY e.degree DESC
LIMIT 20;

-- Plan zapytania dla jednego poziomu ekspansji (to samo SQL, co w repozytorium).
EXPLAIN (ANALYZE, BUFFERS)
WITH candidate_edges AS (
    SELECT e.relationship_id, e.from_id, e.to_id, e.confidence_score,
           row_number() OVER (PARTITION BY e.from_id ORDER BY e.confidence_score DESC) AS rn
    FROM graph_edges e
    WHERE e.from_id = ANY(ARRAY(SELECT id FROM entities ORDER BY degree DESC LIMIT 5))
      AND e.superseded_at IS NULL
      AND (e.valid_to IS NULL OR e.valid_to >= CURRENT_DATE)
)
SELECT count(*) FROM candidate_edges WHERE rn <= 25;

-- Wyszukiwanie rozmyte po nazwie — sprawdza, czy używany jest indeks GIN trigram.
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, display_name, similarity(normalized_name, 'alfa technologie') AS score
FROM entities
WHERE normalized_name % 'alfa technologie'
ORDER BY score DESC
LIMIT 20;
