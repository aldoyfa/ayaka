# Ayaka (绫华) — ITB Academic Assistant & Notification Bot

Ayaka is an autonomous academic synchronization and notification assistant for Institut Teknologi Bandung (ITB) students. It continuously monitors academic platforms (**six.itb.ac.id**, **edunex.itb.ac.id**, **edu.omnicamp.us**) and scans **Gmail** for critical announcements.

Ayaka automatically synchronizes schedules and deadlines to **Google Calendar** and **Google Tasks**, and delivers tiered milestone alerts directly to your **Discord Direct Messages (DM)** with interactive one-click completion buttons.

---

## Key Features

1. **Multi-Platform Fetcher**:
   - **Edunex ITB**: Fetches assignments, quizzes, and submission deadlines via browser session cookies or bearer tokens.
   - **SIX ITB**: Extracts course schedules, midterm/final exam timetables, and academic announcements via session cookie (`ci_session`).
   - **Omnicampus**: Parses course assignments and class activities via bearer token.
2. **Gmail Monitor (Option C)**:
   - Scans unread incoming emails from ITB domains (`@itb.ac.id`, `@mahasiswa.itb.ac.id`) or messages marked *Important/Starred*.
   - Filters academic priority keywords (*assignment, exam, midterm, final, deadline, announcement, grade, lecturer, quiz, practicum, schedule, tugas, ujian, uts, uas, pengumuman, kuliah, nilai, dosen, asistensi, kuis, praktikum, revisi, jadwal*).
   - Forwards real-time summaries of urgent emails straight to your Discord DM.
3. **Google Workspace Synchronization**:
   - **Google Calendar**: Creates scheduled deadline blocks (30-minute time slots prior to due dates).
   - **Google Tasks**: Generates actionable checklist items linked to Calendar and Gmail.
4. **Tiered Milestone Reminders & Anime Character Persona (Discord DM)**:
   - **Kamisato Ayaka Persona**: Speaks with an elegant, devoted, polite, and encouraging tone in English.
   - **Customizable Dialogue Config (`dialogues.json`)**: Every scenario (H-3, H-1, J-6, J-1, Due, Task Complete, Gmail Alert, Empty State) is mapped to customizable voice lines.
   - **Modern Aesthetic Discord UI**:
     - **Dynamic Relative Timestamps**: Discord native `<t:timestamp:R>` for live countdowns (e.g. *in 3 days*, *in 6 hours*).
     - **Visual ASCII Progress Bar**: Time elapsed indicator (`[▰▰▰▰▱▱▱▱] 45% elapsed`).
     - **Interactive Buttons**: `[✅ Mark Complete]` and direct `[🔗 Open Assignment]` link button.
5. **Dual Interface**:
   - **24/7 Daemon on VPS**: Containerized Discord bot and scheduler running continuously via Docker Compose.
   - **AI Workspace Chat**: Manage, fetch, or mark tasks done conversationally by chatting with your AI assistant.

---

## Directory Structure

```text
projects/ayaka/
├── .env.example              # Private tokens and session cookie template
├── config.json               # Operational settings (Gmail keywords, intervals, URLs)
├── dialogues.json            # Customizable anime character dialogue map
├── .gitignore                # Security rules preventing token/database leaks
├── Dockerfile                # Lightweight Python 3.12 slim container definition
├── docker-compose.yml        # Docker Compose configuration with volume persistence
├── pyproject.toml            # Project metadata and pinned dependencies
├── requirements.txt          # Python requirements list
├── README.md                 # Complete documentation and setup guide
├── ayaka/
│   ├── config.py             # Secure configuration loader (config.json + .env)
│   ├── cli.py                # Command-line interface for chat and manual control
│   ├── dialogue.py           # Dialogue manager and aesthetic Discord UI generator
│   ├── scheduler.py          # Periodic polling and reminder milestone evaluation engine
│   ├── main.py               # 24/7 background daemon runner
│   ├── fetchers/
│   │   ├── edunex.py         # Edunex ITB scraper & API client
│   │   ├── six.py            # SIX ITB academic schedule & exam scraper
│   │   ├── omnicampus.py     # Omnicampus task parser
│   │   └── gmail_reader.py   # Option C Gmail monitor
│   ├── services/
│   │   ├── google_sync.py    # Google Calendar & Tasks sync service
│   │   └── discord_bot.py    # Discord bot DM client with interactive UI views
│   └── storage/
│       └── db.py             # SQLite state persistence and deduplication engine
└── tests/
    ├── test_config.py                 # Unit tests for config.json loading
    ├── test_dialogue_and_ui.py        # Unit tests for character dialogue & UI helpers
    └── test_storage_and_milestones.py # Unit tests for storage and milestone triggers
```

---

## Configuration Architecture

Ayaka separates configuration into three clean, dedicated layers:

1. **Private Credentials (`.env`)**:
   - Strictly reserved for private secrets: `DISCORD_BOT_TOKEN`, `DISCORD_USER_ID`, `EDUNEX_COOKIE`, `SIX_COOKIE`, `OMNICAMPUS_TOKEN`.
   - Never committed to version control.
2. **Operational Settings (`config.json`)**:
   - **Gmail Filters**: List of priority keywords (`assignment`, `exam`, `deadline`, `tugas`, `ujian`, etc.) and monitored campus domains.
   - **Timers & Intervals**: Background polling intervals for academic platforms and Gmail.
   - **Platform URLs**: Base URLs for Edunex, SIX ITB, and Omnicampus.
   - **Timezone**: Default `Asia/Jakarta`.
3. **Character Voice & Dialogue (`dialogues.json`)**:
   - In-character voice lines, kaomoji, and embed titles for each scenario (H-3, H-1, J-6, J-1, Due, Task Complete, Gmail Alert, etc.).

---

## Setup & Configuration

### 1. Configure `.env`

In `projects/ayaka/`:
```bash
cp .env.example .env
```
Open `.env` and fill in your credentials:

#### A. Discord Bot
1. Create a Discord application and bot in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Copy your bot token into `DISCORD_BOT_TOKEN`.
3. Under the **Bot** tab, enable **Message Content Intent**.
4. Invite the bot to a server you share with it.
5. Copy your personal Discord User ID (Right-click avatar with Developer Mode enabled > *Copy User ID*) into `DISCORD_USER_ID`.

#### B. Academic Platforms (Session Cookies / Tokens)
1. **Edunex**: Open DevTools (`F12`) > **Network** tab while viewing `edunex.itb.ac.id`, copy the `Cookie` header or Bearer token into `EDUNEX_COOKIE` / `EDUNEX_BEARER_TOKEN`.
2. **SIX ITB**: Open DevTools > **Application** > **Cookies** > `https://six.itb.ac.id`, copy the session cookie (typically `ci_session`) into `SIX_COOKIE`.
3. **Omnicampus**: Open DevTools > **Application** > **Local Storage** / **Cookies**, copy the auth token into `OMNICAMPUS_TOKEN`.

#### C. Google Cloud Credentials
1. Download your `credentials.json` (OAuth 2.0 Client ID for Desktop App) from Google Cloud Console.
2. Place the file inside `projects/ayaka/credentials.json`.
3. On first execution, Ayaka will open an authorization link to generate `token.json`.

---

## Deployment & Usage

### Method A: 24/7 Deployment on VPS via Docker Compose (Recommended)

1. Copy the `projects/ayaka` directory to your VPS.
2. Ensure `.env` is configured with your credentials.
3. Start the container in the background:
   ```bash
   docker compose up -d --build
   ```
4. View live bot logs:
   ```bash
   docker compose logs -f
   ```
5. Manage container lifecycle:
   ```bash
   docker compose restart   # Restart bot service
   docker compose down      # Stop bot service
   ```

*Note: All SQLite data is stored in the host `./data` directory, preserving task histories across container restarts and rebuilds.*

---

### Method B: Conversational & CLI Interaction in AI Workspace

You can ask the AI assistant in chat to execute CLI commands at any time, or run them directly in your shell:

- **Check system status and credentials:**
  ```bash
  python -m ayaka.cli status
  ```
- **List active pending tasks:**
  ```bash
  python -m ayaka.cli list
  ```
- **Mark a task completed manually:**
  ```bash
  python -m ayaka.cli complete <TASK_ID>
  ```
- **Add a manual task or deadline:**
  ```bash
  python -m ayaka.cli add "Project Milestone 1" "2026-10-15T23:59:00" --course "IF2210"
  ```
- **Trigger an on-demand sync cycle:**
  ```bash
  python -m ayaka.cli sync
  ```

---

## Discord Bot Commands

When messaging the bot or in a server channel:
- `!tasks` or `!list`: Displays currently pending academic tasks with deadlines.
- `!complete <task_id>`: Marks a task as completed directly from Discord.
- Clicking the **[✅ Mark Complete]** button on any reminder embed instantly resolves the task and prevents further notifications.
