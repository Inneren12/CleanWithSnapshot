# Web unit tests (Vitest)

## Prerequisites (ephemeral dev dependencies)

Install the testing dependencies without touching package manifests:

```bash
cd web
npm i -D --no-save --no-package-lock vitest @testing-library/react @testing-library/jest-dom jsdom
```

## Running the tests

```bash
cd web
npx vitest run
```

## Notes

- The Vitest configuration lives in `web/vitest.config.ts` and targets `web/tests/**/*.test.tsx`.
- DOM assertions are enabled via `web/tests/setup.ts` (jest-dom).
- Existing node-based tests in `web/tests/*.test.ts` continue to run via the legacy `npm test` script.
