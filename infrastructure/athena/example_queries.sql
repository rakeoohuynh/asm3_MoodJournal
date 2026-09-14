-- Analytics queries shown in the dashboard's "Long-term Insights" card and
-- served by the /analytics/athena endpoint.
-- Replace {env} with the deployment environment, e.g. moodjournal_dev, and
-- {userId} with the user to query. The deployed versions live in
-- backend/services/athena_service.py (QUERIES dict), where the user id is an
-- execution parameter rather than text in the SQL.
--
-- Every daily export rewrites the last 90 days of entries into a new day=
-- partition, so one entry appears in many partitions. Each query therefore
-- starts from the most recent export of each entry.

-- ---------------------------------------------------------------------------
-- mood_count_by_week
-- Entries, average score and mood breakdown for each week.
-- ---------------------------------------------------------------------------
WITH latest AS (
    SELECT entryid, entrydate, mood, moodscore,
           row_number() OVER (
               PARTITION BY entryid ORDER BY year DESC, month DESC, day DESC
           ) AS export_rank
    FROM moodjournal_{env}.journal_entries
    WHERE userid = '{userId}'
),
entries AS (
    SELECT entryid, entrydate, mood, moodscore FROM latest WHERE export_rank = 1
)
SELECT
    cast(date_trunc('week', date_parse(entrydate, '%Y-%m-%d')) AS date) AS week_start,
    count(*) AS entry_count,
    round(avg(cast(moodscore AS double)), 2) AS avg_mood_score,
    count_if(mood = 'POSITIVE') AS positive,
    count_if(mood = 'NEUTRAL') AS neutral,
    count_if(mood = 'ANXIOUS') AS anxious,
    count_if(mood = 'NEGATIVE') AS negative
FROM entries
GROUP BY 1
ORDER BY week_start DESC;

-- ---------------------------------------------------------------------------
-- most_common_mood_by_month
-- The dominant mood for each month.
-- ---------------------------------------------------------------------------
WITH latest AS (
    SELECT entryid, entrydate, mood, moodscore,
           row_number() OVER (
               PARTITION BY entryid ORDER BY year DESC, month DESC, day DESC
           ) AS export_rank
    FROM moodjournal_{env}.journal_entries
    WHERE userid = '{userId}'
),
entries AS (
    SELECT entryid, entrydate, mood, moodscore FROM latest WHERE export_rank = 1
),
monthly AS (
    SELECT
        substr(entrydate, 1, 7) AS month,
        mood,
        count(*) AS mood_count,
        sum(count(*)) OVER (PARTITION BY substr(entrydate, 1, 7)) AS entry_count,
        row_number() OVER (
            PARTITION BY substr(entrydate, 1, 7)
            ORDER BY count(*) DESC, mood
        ) AS rnk
    FROM entries
    GROUP BY 1, 2
)
SELECT month, mood AS most_common_mood, mood_count, entry_count
FROM monthly
WHERE rnk = 1
ORDER BY month DESC;

-- ---------------------------------------------------------------------------
-- average_mood_score_over_time
-- Average mood score per day. Positive=2, Neutral=1, Anxious=0, Negative=-1.
-- ---------------------------------------------------------------------------
WITH latest AS (
    SELECT entryid, entrydate, mood, moodscore,
           row_number() OVER (
               PARTITION BY entryid ORDER BY year DESC, month DESC, day DESC
           ) AS export_rank
    FROM moodjournal_{env}.journal_entries
    WHERE userid = '{userId}'
),
entries AS (
    SELECT entryid, entrydate, mood, moodscore FROM latest WHERE export_rank = 1
)
SELECT
    entrydate,
    round(avg(cast(moodscore AS double)), 2) AS avg_mood_score,
    count(*) AS entry_count
FROM entries
GROUP BY entrydate
ORDER BY entrydate DESC;

-- ---------------------------------------------------------------------------
-- entry_count_by_day
-- Simple journaling-consistency measure.
-- ---------------------------------------------------------------------------
WITH latest AS (
    SELECT entryid, entrydate, mood, moodscore,
           row_number() OVER (
               PARTITION BY entryid ORDER BY year DESC, month DESC, day DESC
           ) AS export_rank
    FROM moodjournal_{env}.journal_entries
    WHERE userid = '{userId}'
),
entries AS (
    SELECT entryid, entrydate, mood, moodscore FROM latest WHERE export_rank = 1
)
SELECT
    entrydate,
    count(*) AS entry_count
FROM entries
GROUP BY entrydate
ORDER BY entrydate DESC;
