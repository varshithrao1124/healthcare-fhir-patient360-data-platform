-- Databricks / Delta maintenance for the conformed encounter table.
-- Local runs execute the OPTIMIZE statement through the Spark session.
-- Liquid clustering is the warehouse form of the same access pattern and is
-- declared in sql/unity/catalog.sql for Unity Catalog tables.

OPTIMIZE acn_prod.restricted.encounter ZORDER BY (enterprise_person_id, admit_time);

OPTIMIZE acn_prod.insight.lab_trend ZORDER BY (enterprise_person_id, loinc);
