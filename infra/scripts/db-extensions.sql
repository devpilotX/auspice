-- Extensions the Permission Graph depends on.
--
-- CREATE EXTENSION needs superuser, so it happens here at cluster initialisation rather
-- than inside a migration. The first migration asserts these are present and refuses to
-- run if they are not, which turns a half provisioned database into a loud failure at the
-- first step instead of a quiet one three stages later.

CREATE EXTENSION IF NOT EXISTS postgis;      -- spatial join from parcel to jurisdiction
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- entity resolution and fuzzy search
CREATE EXTENSION IF NOT EXISTS vector;       -- document and chunk embeddings
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- exclusion constraints on bi-temporal ranges
