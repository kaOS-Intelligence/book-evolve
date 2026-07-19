import type { ProjectConfig } from './types.js';
/**
 * Check whether a book project already exists at the given path.
 * Returns the existing config if found, null otherwise.
 */
export declare function detectExistingProject(projectDir: string): {
    exists: boolean;
    configPath: string;
};
export declare function scaffoldProject(config: ProjectConfig, force?: boolean): Promise<string>;
/**
 * Seed the cognition store with dictation and reference data.
 *
 * Validates inputs before calling the Python seeder so the user gets an
 * actionable message instead of a Python traceback.
 */
export declare function seedCognition(projectDir: string, options: {
    dictation?: string;
    reference?: string;
    referenceSource?: string;
}): Promise<void>;
//# sourceMappingURL=scaffold.d.ts.map