# Security Policy

Report vulnerabilities privately via GitHub Security Advisories on this repository (or contact https://github.com/Waqas-Ai-Engineer). Please do not open public issues for security problems.

Never commit Twilio credentials. The webhook reads secrets only from environment variables and verifies `X-Twilio-Signature` when sending is enabled.
