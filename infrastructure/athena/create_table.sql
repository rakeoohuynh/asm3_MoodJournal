-- External table over the analytics export written by export_analytics.py.
--
-- The SAM template already creates this table (resource: AnalyticsTable).
-- This file documents the schema and allows manual recreation.
--
-- Data layout in S3:
--   s3://{analytics-bucket}/moodjournal/year=YYYY/month=MM/day=DD/{userId}.json
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
LOCATION 's3://{analytics-bucket}/moodjournal/'
TBLPROPERTIES (
    -- Partition projection: Athena derives partitions from the query rather
    -- than the Glue catalogue, so new exports are queryable immediately and
    -- MSCK REPAIR TABLE is never needed. The SAM template sets the same
    -- properties on the AnalyticsTable resource; keep the two in step.
    'projection.enabled' = 'true',
    'projection.year.type' = 'integer',
    'projection.year.range' = '2026,2035',
    'projection.year.digits' = '4',
    'projection.month.type' = 'integer',
    'projection.month.range' = '1,12',
    'projection.month.digits' = '2',
    'projection.day.type' = 'integer',
    'projection.day.range' = '1,31',
    'projection.day.digits' = '2',
    'storage.location.template' =
        's3://{analytics-bucket}/moodjournal/year=${year}/month=${month}/day=${day}'
);
