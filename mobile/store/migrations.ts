/**
 * Schema version history and migration functions for AsyncStorage persistence.
 *
 * How it works:
 *   - Each persisted store snapshot is tagged with a version number.
 *   - When the app loads and the stored version is older than STORE_VERSION,
 *     Zustand's persist middleware calls `migrate()` which applies every
 *     intermediate migration in order (v0→v1→v2→…).
 *
 * Adding a new migration:
 *   1. Write a migration function in the `migrations` map below.
 *      The key is the OLD version (source), and the function returns the
 *      state transformed to the NEXT version.
 *   2. Bump STORE_VERSION by 1.
 *   3. That's it — existing users will migrate automatically on next app launch.
 *
 * Example – renaming a field:
 *   // v1 → v2: Rename `optimizerMethod` to `optimizerStrategy`
 *   1: (state) => {
 *     const { optimizerMethod, ...rest } = state;
 *     return { ...rest, optimizerStrategy: optimizerMethod ?? 'legacy' };
 *   },
 *
 * Example – adding a new persisted field with a default:
 *   // v2 → v3: Add `units` preference (default 'metric')
 *   2: (state) => {
 *     return { ...state, units: 'metric' };
 *   },
 *
 * Example – removing a deprecated field:
 *   // v3 → v4: Remove `legacyFlag`
 *   3: (state) => {
 *     const { legacyFlag: _removed, ...rest } = state;
 *     return rest;
 *   },
 */

// ---------------------------------------------------------------------------
// Current schema version – bump this when the persisted state shape changes.
// ---------------------------------------------------------------------------
export const STORE_VERSION = 2;

// Loosely typed so migrations can handle arbitrary shapes across versions.
type PersistedState = Record<string, unknown>;

// ---------------------------------------------------------------------------
// Migration functions: key = source version, fn transforms state → next version.
// ---------------------------------------------------------------------------
const migrations: Record<number, (state: PersistedState) => PersistedState> = {
  // v0 → v1: Baseline migration – introduces versioning to existing stores.
  // No structural changes; all pre-existing AsyncStorage data is compatible.
  0: (state) => state,

  // v1 → v2: Add savedEfforts array for progression tracking.
  1: (state) => ({ ...state, savedEfforts: [] }),
};

// ---------------------------------------------------------------------------
// Main migrate function – called by Zustand persist middleware.
// Runs all migrations sequentially from `fromVersion` up to STORE_VERSION.
// ---------------------------------------------------------------------------
export function migrate(
  persistedState: unknown,
  fromVersion: number,
): PersistedState {
  let state = (persistedState as PersistedState) || {};

  for (let v = fromVersion; v < STORE_VERSION; v++) {
    const migrationFn = migrations[v];
    if (migrationFn) {
      console.log(`[Store Migration] v${v} → v${v + 1}`);
      state = migrationFn(state);
    } else {
      console.warn(
        `[Store Migration] No migration for v${v} → v${v + 1}, passing through`,
      );
    }
  }

  if (fromVersion < STORE_VERSION) {
    console.log(
      `[Store Migration] Complete: v${fromVersion} → v${STORE_VERSION}`,
    );
  }

  return state;
}
