CREATE TABLESPACE d_space LOCATION 'D:/pgdata';
CREATE DATABASE smart_grid TABLESPACE d_space;
ALTER DATABASE smart_grid SET timezone = 'Africa/Kigali';
\c smart_grid
CREATE EXTENSION IF NOT EXISTS timescaledb;