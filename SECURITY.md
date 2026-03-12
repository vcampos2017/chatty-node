# Security Policy

## Chatty Node Security Model

Chatty Node is designed as a **privacy-first, local AI assistant** intended to run primarily on edge devices such as Raspberry Pi systems.

The architecture prioritizes:

- local data processing
- minimal external dependencies
- protection of user credentials
- transparency in open-source development

---

## Secrets and Credentials

Sensitive credentials are **never stored in the repository**.

Secrets are loaded from a local environment file:

/etc/chatty/secrets.env

Examples include:

- API keys
- access tokens
- service credentials

These files are excluded from version control via `.gitignore`.

Developers should **never commit credentials** to the repository.

---

## Network Exposure

Chatty Node is designed to run **locally on a private network**.

If the system is exposed externally, implement the following protections:

- HTTPS / TLS
- firewall rules
- API token authentication
- rate limiting
- secure router configuration

---

## Voice Interface Safety

Chatty uses wake-word activation to prevent unintended commands.

Recommended safeguards:

- wake phrase detection
- command validation
- allow-listed system actions
- avoidance of direct shell command execution from voice input

---

## Responsible Disclosure

If you discover a security issue in Chatty Node, please report it responsibly.

Preferred method:

Open a **GitHub Issue** describing the vulnerability.

Include:

- reproduction steps
- affected version
- potential impact

---

## Security Philosophy

Chatty Node follows several core principles:

1. Process data locally whenever possible
2. Respect user privacy by default
3. Store secrets outside version control
4. Avoid unnecessary cloud dependencies
5. Keep the system understandable and auditable

Chatty is designed to act as a **civic-minded, privacy-respecting AI assistant** rather than a surveillance device.
