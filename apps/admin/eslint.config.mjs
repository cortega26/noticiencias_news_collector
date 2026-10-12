import js from '@eslint/js';
import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import astroPlugin from 'eslint-plugin-astro';
import securityPlugin from 'eslint-plugin-security';
import noSecretsPlugin from 'eslint-plugin-no-secrets';
import astroParser from 'astro-eslint-parser';
import globals from 'globals';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export default [
  {
    ignores: ['dist/', '.astro/', 'node_modules/', 'coverage/', 'src/lib/generated/'],
  },
  {
    plugins: {
      '@typescript-eslint': tsPlugin,
      security: securityPlugin,
      'no-secrets': noSecretsPlugin,
    },
  },
  js.configs.recommended,
  {
    files: ['**/*.{js,mjs,cjs,ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        project: './tsconfig.json',
        tsconfigRootDir: __dirname,
      },
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    rules: {
      ...tsPlugin.configs.recommended.rules,
      // Disable no-undef for TS files as TSC handles it
      'no-undef': 'off',
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', ignoreRestSiblings: true },
      ],
      'security/detect-object-injection': 'off',
      'no-secrets/no-secrets': 'error',
    },
  },
  ...astroPlugin.configs.recommended,
  {
    files: ['**/*.astro'],
    languageOptions: {
      parser: astroParser,
      parserOptions: {
        parser: tsParser,
        extraFileExtensions: ['.astro'],
        project: './tsconfig.json',
        tsconfigRootDir: __dirname,
      },
      globals: {
        ...globals.node,
        ...globals.browser,
        Astro: 'readonly',
        Fragment: 'readonly',
      },
    },
    rules: {
      // Disable no-undef for Astro files
      'no-undef': 'off',
      'no-secrets/no-secrets': 'error',
    },
  },
];
