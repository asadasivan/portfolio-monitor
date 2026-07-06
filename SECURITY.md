# Security Policy

Portfolio Monitor is designed to run locally for portfolio tracking and performance analysis. It does not require broker credentials and does not send statements to a hosted service.

## Supported Use

- Run locally on a trusted machine.
- Store real statements only in `input/`.
- Store generated reports only in `reports/`.
- Keep local databases under `data/`.
- Keep API keys in `.env` if future provider integrations are added.

## Sensitive Data

Do not commit:

- brokerage statements
- tax documents
- screenshots with balances or account identifiers
- generated reports
- SQLite databases
- `.env`
- API keys
- real cost-basis exports

The repository `.gitignore` is configured to exclude these by default.

## Reporting Issues

If you find a security or privacy issue, open a private advisory or contact the maintainer directly. Do not post real portfolio data in a public issue.

## Current Security Boundaries

- No broker login support.
- No trade execution.
- No hosted backend.
- No required LLM integration.
- Market data refresh uses public market data endpoints.

## Residual Risks

- PDF parsing can misread statements; verify imported holdings.
- Public market data can be delayed or wrong.
- HTML reports contain private financial data and should not be shared publicly.
- Local machines with malware or weak access controls can expose local reports and databases.
