/**
 * Project configuration — populated by the onboarding wizard.
 */
export interface ProjectConfig {
  bookTitle: string;
  bookAuthor?: string;
  bookGoal: string;
  dictationDir: string;
  referenceDir: string;
  provider: ProviderType;
  outputDir: string;
  targetScore: number;
  patience: number;
  maxSteps: number;
}

export type ProviderType =
  | 'sovereign'
  | 'cursor'
  | 'claude'
  | 'terminal'
  | 'api';

export interface ProviderConfig {
  type: ProviderType;
  apiKey?: string;
  apiEndpoint?: string;
  modelName?: string;
}
