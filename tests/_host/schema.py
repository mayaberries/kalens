"""
The host tables `kalens` requires but does not own.

This is the prerequisite contract from docs/integration-contract.md, written
out as the smallest schema that satisfies it. Deliberately *not* a copy of
pets-appts' tables: only the columns the library's foreign keys and its
injected repositories actually touch are here. If the library ever starts
needing a column that isn't in this file, the contract grew and the docs are
out of date -- which is most of the point of keeping this minimal.

Raw DDL rather than an Alembic chain because there is nothing to migrate: the
test session creates it once and drops the database afterwards.
"""

HOST_TABLES_DDL = """
CREATE TABLE clinics (
    id          CHAR(36) PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id            CHAR(36) PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    email         TEXT NOT NULL UNIQUE,
    role          TEXT NOT NULL DEFAULT 'client',
    clinic_id     CHAR(36) REFERENCES clinics(id) ON DELETE SET NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    is_guest      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE owner_profiles (
    id            CHAR(36) PRIMARY KEY,
    user_id       CHAR(36) NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    full_name     TEXT,
    phone_number  TEXT,
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- The SUBJECT of an appointment. `appointments.pet_id` points here.
CREATE TABLE pet_profiles (
    id                CHAR(36) PRIMARY KEY,
    owner_profile_id  CHAR(36) NOT NULL REFERENCES owner_profiles(id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    species           TEXT,
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE services (
    id                CHAR(36) PRIMARY KEY,
    clinic_id         CHAR(36) NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    duration_minutes  INTEGER,
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- The overlap check joins appointments -> services on clinic_id on every
-- create and every confirm. The index is the host's responsibility; the
-- library documents it rather than creating it on a table it doesn't own.
CREATE INDEX ix_services_clinic_id ON services (clinic_id);

CREATE TABLE clinic_owner_profiles (
    clinic_id         CHAR(36) NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    owner_profile_id  CHAR(36) NOT NULL REFERENCES owner_profiles(id) ON DELETE CASCADE,
    status            TEXT NOT NULL DEFAULT 'active',
    PRIMARY KEY (clinic_id, owner_profile_id)
);

CREATE TABLE clinic_api_keys (
    id          CHAR(36) PRIMARY KEY,
    clinic_id   CHAR(36) NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    public_key  TEXT NOT NULL UNIQUE,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE
);
"""

HOST_TABLES_DROP = """
DROP TABLE IF EXISTS clinic_api_keys;
DROP TABLE IF EXISTS clinic_owner_profiles;
DROP TABLE IF EXISTS services;
DROP TABLE IF EXISTS pet_profiles;
DROP TABLE IF EXISTS owner_profiles;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS clinics;
"""
