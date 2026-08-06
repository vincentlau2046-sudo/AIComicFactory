import { drizzle } from "drizzle-orm/better-sqlite3";
import * as schema from "./schema";
import fs from "node:fs";
import path from "node:path";

type DrizzleDB = ReturnType<typeof drizzle<typeof schema>>;
type SqliteConnection = import("better-sqlite3").Database;
type MigrationMeta = {
  folderMillis: number;
  hash: string;
};

const globalForDb = globalThis as unknown as {
  sqlite: SqliteConnection | undefined;
  drizzleDb: DrizzleDB | undefined;
};

function resolveDbPath() {
  // Dynamic require to avoid loading native binary at build time
  const dbPath = process.env.DATABASE_URL?.replace("file:", "") || "./data/aicomic.db";
  return path.resolve(dbPath);
}

function getSqlite(): SqliteConnection {
  if (globalForDb.sqlite) return globalForDb.sqlite;

  // Dynamic require to avoid loading native binary at build time
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const Database = require("better-sqlite3") as typeof import("better-sqlite3");
  const absolutePath = resolveDbPath();

  // Ensure the directory exists before opening the database
  fs.mkdirSync(path.dirname(absolutePath), { recursive: true });

  const sqlite = new Database(absolutePath);
  if (process.env.NODE_ENV !== "production") {
    globalForDb.sqlite = sqlite;
  }

  sqlite.pragma("journal_mode = WAL");
  sqlite.pragma("foreign_keys = ON");

  return sqlite;
}

function createDb(): DrizzleDB {
  if (globalForDb.drizzleDb) return globalForDb.drizzleDb;

  const sqlite = getSqlite();
  const instance = drizzle(sqlite, { schema });
  if (process.env.NODE_ENV !== "production") {
    globalForDb.drizzleDb = instance;
  }
  return instance;
}

function tableExists(sqlite: SqliteConnection, tableName: string) {
  const row = sqlite
    .prepare<[string], { name: string }>(
      "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
    )
    .get(tableName);

  return Boolean(row);
}

function columnExists(
  sqlite: SqliteConnection,
  tableName: string,
  columnName: string,
) {
  if (!tableExists(sqlite, tableName)) return false;

  const columns = sqlite
    .prepare<[], { name: string }>(`PRAGMA table_info("${tableName}")`)
    .all();

  return columns.some((column) => column.name === columnName);
}

function ensureMigrationsTable(sqlite: SqliteConnection) {
  sqlite.prepare(`
    CREATE TABLE IF NOT EXISTS "__drizzle_migrations" (
      id SERIAL PRIMARY KEY,
      hash text NOT NULL,
      created_at numeric
    )
  `).run();
}

function getRecordedMigrationCount(sqlite: SqliteConnection) {
  const row = sqlite
    .prepare<[], { count: number }>(
      'SELECT COUNT(*) AS count FROM "__drizzle_migrations"',
    )
    .get();

  return Number(row?.count ?? 0);
}

function getAppTableCount(sqlite: SqliteConnection) {
  const row = sqlite
    .prepare<[], { count: number }>(`
      SELECT COUNT(*) AS count
      FROM sqlite_master
      WHERE type = 'table'
        AND name NOT LIKE 'sqlite_%'
        AND name != '__drizzle_migrations'
    `)
    .get();

  return Number(row?.count ?? 0);
}

function isCurrentSchemaSnapshot(sqlite: SqliteConnection) {
  return (
    columnExists(sqlite, "projects", "user_id") &&
    columnExists(sqlite, "projects", "world_setting") &&
    tableExists(sqlite, "episodes") &&
    tableExists(sqlite, "shot_assets") &&
    tableExists(sqlite, "agents") &&
    columnExists(sqlite, "agents", "platform") &&
    tableExists(sqlite, "agent_bindings")
  );
}

function shouldBaselineExistingSchema(sqlite: SqliteConnection) {
  return (
    getRecordedMigrationCount(sqlite) === 0 &&
    getAppTableCount(sqlite) > 0 &&
    isCurrentSchemaSnapshot(sqlite)
  );
}

function baselineMigrations(
  sqlite: SqliteConnection,
  migrationsFolder: string,
) {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { readMigrationFiles } = require("drizzle-orm/migrator") as {
    readMigrationFiles: (config: { migrationsFolder: string }) => MigrationMeta[];
  };

  const migrations = readMigrationFiles({ migrationsFolder });
  const insert = sqlite.prepare<[string, number]>(
    'INSERT INTO "__drizzle_migrations" ("hash", "created_at") VALUES (?, ?)',
  );

  sqlite.transaction(() => {
    for (const migration of migrations) {
      insert.run(migration.hash, migration.folderMillis);
    }
  })();
}

export function runMigrations() {
  const sqlite = getSqlite();
  const migrationsFolder = path.resolve("drizzle");
  ensureMigrationsTable(sqlite);

  if (shouldBaselineExistingSchema(sqlite)) {
    console.log(
      "[DB] Existing schema detected without migration history. Baselining migrations...",
    );
    baselineMigrations(sqlite, migrationsFolder);
    return;
  }

  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { migrate } = require("drizzle-orm/better-sqlite3/migrator");
  migrate(createDb(), { migrationsFolder });
}

// Proxy preserves the `db` export API — lazy-inits on first property access
export const db: DrizzleDB = new Proxy({} as DrizzleDB, {
  get(_, prop) {
    const instance = createDb();
    const value = (instance as never)[prop];
    if (typeof value === "function") {
      return (value as (...args: unknown[]) => unknown).bind(instance);
    }
    return value;
  },
});

export type DB = typeof db;
