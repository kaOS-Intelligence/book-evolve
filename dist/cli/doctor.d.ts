/**
 * Resolve the API key exactly the way the pipeline does:
 * LITELLM_API_KEY, then ~/.litellm-master-key, then "EMPTY".
 * Returns the key plus a label describing where it came from.
 */
export declare function resolveApiKey(): {
    key: string;
    source: string;
};
/** The council/judge/embedding models the pipeline will actually use. */
export declare function resolveModels(): {
    council: string[];
    judge: string;
    fast: string;
    embed: string;
};
/**
 * Live smoke test — sends one tiny completion through every unique model the
 * pipeline will use, plus one embedding round-trip. Verifies the entire
 * model path end-to-end in under a minute, before any real evolution run.
 */
export declare function runSmoke(): Promise<boolean>;
export declare function runDoctor(projectDir: string): Promise<boolean>;
//# sourceMappingURL=doctor.d.ts.map