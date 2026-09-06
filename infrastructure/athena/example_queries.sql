-- Analytics queries used by the dashboard and by the /analytics/athena endpoint.
-- Replace {env} with the deployment environment, e.g. moodjournal_dev.
--
-- Each query below has a name in run_athena_query.py (QUERIES dict).

-- ---------------------------------------------------------------------------
-- mood_count_by_week
-- How many entries of each mood were written each week.
-- ---------------------------------------------------------------------------
SELECT
    date_trunc('week', date_parse(entrydate, '%Y-%m-%d')) AS week_start,
    mood,
    count(*) AS entry_count
FROM moodjournal_{env}.journal_entries
GROUP BY 1, 2
ORDER BY week_start DESC, mood;

-- ---------------------------------------------------------------------------
-- most_common_mood_by_month
-- The dominant mood for each month.
-- ---------------------------------------------------------------------------
WITH monthly AS (
    SELECT
        substr(entrydate, 1, 7) AS month,
        mood,
        count(*) AS entry_count,
        row_number() OVER (
            PARTITION BY substr(entrydate, 1, 7)
            ORDER BY count(*) DESC
        ) AS rank
    FROM moodjournal_{env}.journal_entries
    GROUP BY 1, 2
)
SELECT month, mood AS most_common_mood, entry_count
FROM monthly
WHERE rank = 1
ORDER BY month DESC;

-- ---------------------------------------------------------------------------
-- average_mood_score_over_time
-- Average mood score per day. Positive=2, Neutral=1, Anxious=0, Negative=-1.
-- ---------------------------------------------------------------------------
SELECT
    entrydate,
    round(avg(cast(moodscore AS double)), 2) AS avg_mood_score,
    count(*) AS entry_count
FROM moodjournal_{env}.journal_entries
GROUP BY entrydate
ORDER BY entrydate DESC
LIMIT 90;

-- ---------------------------------------------------------------------------
-- entry_count_by_day
-- Simple journaling-consistency measure.
-- ---------------------------------------------------------------------------
SELECT
    entrydate,
    count(*) AS entry_count
FROM moodjournal_{env}.journal_entries
GROUP BY entrydate
ORDER BY entrydate DESC
LIMIT 90;
