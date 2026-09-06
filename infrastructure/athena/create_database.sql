-- MoodJournal Athena database
--
-- The SAM template already creates this database as a Glue database
-- (resource: AthenaDatabase). This file is kept so the database can be
-- recreated by hand if the stack is deleted but the S3 data is retained.
--
-- Replace {env} with the deployment environment, e.g. moodjournal_dev.

CREATE DATABASE IF NOT EXISTS moodjournal_{env}
COMMENT 'MoodJournal analytics database';
