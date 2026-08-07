# Credentials

Save one Firebase service-account JSON key in this directory, for example
`kinshield-nonprod-service-account.json`. The publisher automatically uses the
only `*.json` file here; use `--credentials` when supplying a different file.

Create the key from Firebase console: **Project settings → Service accounts →
Generate new private key**. Give that service account a role that can manage
Remote Config (for example, Firebase Remote Config Admin) and ensure the
Firebase Remote Config API is enabled for the target project.

Private keys are ignored by Git. Do not commit or share them.
