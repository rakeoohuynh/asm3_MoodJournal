-- External table over the analytics export written by export_analytics.py.
--
-- The SAM template already creates this table (resource: AnalyticsTable).
-- This file documents the schema and allows manual recreation.
--
-- Data layout in S3:
--   s3://{analytics-bucket}/moodjournal/year=YYYY/month=MM/day=DD/entries.json
--
-- One JSON object per line (JSON Lines), which is what JsonSerDe expects.

CREATE EXTERNAL TABLE IF NOT EXISTS moodjournal_{env}.journal_entries (
    entryid                 string,
    userid                  string,
    entrydate               string,
    mood                    string,
    moodscore               int,
    confidence              double,
    contentlength           int,
    classificationfallback  boolean,
    createdat               string
)
PARTITIONED BY (
    year  string,
    month string,
    day   string
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://{analytics-bucket}/moodjournal/';

-- Partitions are created by the export Lambda writing new prefixes.
-- Run this after a new export so Athena can see the new partitions:
MSCK REPAIR TABLE moodjournal_{env}.journal_entries;
