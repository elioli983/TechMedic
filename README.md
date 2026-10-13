# TechMedic v1.5.6 - SQLCipher edition

Windows-only development/evaluation release. Documentation reviewed October 12, 2026. Database encryption works in the tested offline scenarios; the four targeted reliability/transport/startup/performance fixes are implemented; other security limitations remain. See [SQLCIPHER_VALIDATION.md](SQLCIPHER_VALIDATION.md). This is not unrestricted production approval.

## Windows setup

1. Install **Python 3.14 for Windows x64**, including the Python launcher. This is the tested Python environment.
2. Download and extract this repository, or clone it with `git clone https://github.com/elioli983/TechMedic.git`. Open the extracted/cloned folder containing `INSTALL_WINDOWS.bat`.
3. Double-click **`INSTALL_WINDOWS.bat`**. It creates `.venv`, installs dependencies, checks SQLCipher, and creates `.env` from `.env.example` if it does not already exist. Internet access and a compatible SQLCipher wheel are required.
4. Choose one of the startup modes below. The application opens at **http://127.0.0.1:8519**. Keep the launcher console open while using it; press **Ctrl+C** in that console to stop it.

### Offline demonstration

Double-click **`START_TECHMEDIC.bat`** for the synthetic offline demonstration. No API keys are required for this mode. It does not perform live OpenAI/Jev analysis.

### Live development/evaluation with OpenAI and Jev

**Each user must obtain their own OpenAI API key and Jev API key. No keys, API access, or credits are included.** Enter both keys in the local **`.env`** file in the application folder:

```dotenv
OPENAI_API_KEY=your_openai_api_key
JEV_API_KEY=your_jev_api_key
```

Use a plain-text editor and retain the filename `.env` (not `.env.txt`). The file is created by the installer; alternatively, copy `.env.example` to `.env`. Leave model and endpoint defaults unchanged unless your provider/account requires a different configuration. An optional custom `JEV_API_URL` must use HTTPS; redirects are rejected.

Stop any running offline instance, then double-click **`START_LIVE_TECHMEDIC.bat`** and turn on **Enable Live OpenAI / Jev** in the app. Restart through this launcher after changing API keys. API calls may incur provider charges, and submitted inputs are sent to the live services. Use fictional inputs for evaluation.

**Never commit or share `.env`.** It contains plaintext credentials and is excluded by `.gitignore`. The repository also excludes `.venv`, case databases, protected encryption keys, and local dependency caches. Every fresh download needs installation and its own local configuration.

## Development fixes - October 12, 2026

Lease renewal and current-time expiry checks are fixed. Jev URLs must use HTTPS and redirects are rejected. The supported launchers hold one SQLCipher server per Windows user and atomically publish the existing-format journal key. History starts with the latest 50 turns; use Load older messages for more. Exports retain complete history and recent-case sorting uses an index.

After updating an existing installation, stop its old console with Ctrl+C and restart through START_TECHMEDIC.bat or START_LIVE_TECHMEDIC.bat. Direct `streamlit run` bypasses the startup guard and is unsupported. The new lock cannot take control of an already-running older launcher.

## Storage and UI

All application database records use SQLCipher with a random key protected by Windows current-user DPAPI. A fresh `data/techmedic_v1_5_6.sqlcipher` is created. Existing SQLite data is ignored, not converted or deleted.

Use **+ New case** to start, **Diagnostic Options** for handoff/bundle/trace, and **Recents > ... > Delete** for confirmed deletion. Downloaded reports and bundles are not encrypted and can include secrets pasted into a case.

## Documentation and checks

- [USER_MANUAL.md](USER_MANUAL.md): installation, operation, recovery and exports.
- [SQLCIPHER_STORAGE.md](SQLCIPHER_STORAGE.md): key locations, backup requirements and protection boundaries.
- [SQLCIPHER_VALIDATION.md](SQLCIPHER_VALIDATION.md): actual test evidence, performance and outstanding findings.
- [RELEASE_NOTES_v1.5.6.md](RELEASE_NOTES_v1.5.6.md): current release changes and restrictions.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): current implementation.

Run `VALIDATE_OFFLINE_OPTIONAL.bat` for 190 core/encryption/development-fix tests. Run `.venv\Scripts\python.exe -m unittest -v hardening_tests` for 10 additional tests. The combined 200 tests and expanded UI checks cover the targeted fixes; they are not general-production approval.

Version-specific older release notes, upgrade instructions, test plans and the v1.0 specification are historical references. Their database-copy, platform and validation statements are not instructions for this SQLCipher edition. `requirements.txt` is an installer input; `fixtures/*.txt` are exact synthetic test inputs.
