# Ayaka (绫华) — ITB Academic Assistant & Notification Bot 🌸

Ayaka is an autonomous, local-first academic synchronization and proactive notification assistant tailored for students of Institut Teknologi Bandung (ITB). It continuously monitors academic platforms (**six.itb.ac.id**, **edunex.itb.ac.id**, **edu.omnicamp.us**) and scans **Gmail** for critical announcements.

Ayaka synchronizes schedules and deadlines to **Google Calendar** and **Google Tasks**, delivers tiered milestone alerts directly to your **Discord Direct Messages (DM)** with interactive UI components, manages class attendance reminders, and provides a conversational **AI Assistant** powered by Google Gemini with tool calling and persistent memory.

---

## 🌟 Key Features

### 1. High-Performance Asynchronous Multi-Platform Fetcher
- **Edunex ITB**: Scrapes assignments, quizzes, and submission deadlines via browser session cookies or bearer tokens. Features dynamic period discovery and parallel task detail retrieval.
- **SIX ITB**: Scrapes student lecture calendars, midterm/final exam timetables (UTS/UAS), and meeting details (lecturers, topics, Teams/Edunex links, room numbers, attendance windows) concurrently (<500ms using `asyncio.gather()`).
- **Omnicampus**: Parses course assignments, reports, and attendance questionnaires asynchronously across configurable course IDs.
- **Dynamic Academic Configuration**: Configurable student ID (NIM), semester code, period ID, and course IDs without modifying source code.

### 2. Intelligent Lecture Schedule & Attendance Management
- **Google Calendar & SIX Integration**: Synchronizes SIX lecture meetings with Google Calendar.
- **Daily Morning Briefing (05:00 WIB)**: Proactively sends an embed summarizing today's class schedule and tasks nearing their deadlines.
- **Class Start Proactive Alerts**: Dispatches DM reminders when a lecture starts with instant action buttons: `[Open SIX]`, `[Open Edunex]`, and `[Join Teams]`.
- **Class Attendance Proactive Alerts**: Dispatches attendance reminders 10 minutes before class ends with a `[Checked In]` status button.
- **Schedule Slash Command (`/schedule`)**: Interactive calendar views for `today`, `tomorrow`, `week`, or custom dates with lecture topics and room details.

### 3. Gmail Monitor (Priority Scanning)
- Scans unread incoming emails from ITB domains (`@itb.ac.id`, `@mahasiswa.itb.ac.id`) or messages marked *Important/Starred*.
- Filters academic priority keywords (*assignment, exam, deadline, announcement, grade, lecturer, quiz, schedule, tugas, ujian, uts, uas, pengumuman, kuliah, nilai, dosen, kuis, jadwal*).
- Forwards real-time summaries of urgent emails straight to your Discord DM.

### 4. Google Workspace Synchronization
- **Google Calendar**: Automatically creates scheduled deadline blocks prior to due dates.
- **Google Tasks**: Generates actionable checklist items linked to Calendar and Gmail. Marking a task completed in Discord marks it completed in Google Tasks.

### 5. Discord Bot with Modular Cogs Architecture & Rich UI
- **Modern Aesthetic Discord UI**:
  - **Dynamic Relative Timestamps**: Discord native `<t:timestamp:R>` countdowns (e.g. *in 3 days*, *in 6 hours*).
  - **Visual ASCII Progress Bar**: Time elapsed indicator (`[▰▰▰▰▱▱▱▱] 45% elapsed`).
  - **Interactive Action Buttons**: `[✅ Mark Complete]`, `[🔗 Open Assignment]`, `[Join Teams]`, `[Checked In]`.
  - **Interactive Pagination**: Browse tasks with `[◀ Prev]` and `[Next ▶]` buttons.
- **Kamisato Ayaka Persona**: Speaks with an elegant, devoted, polite, and encouraging tone. Dialogue voice lines and scenarios are fully customizable via `dialogues.json`.

### 6. Conversational AI Agent with Tool Calling & Persistent Memory
- Powered by Google Gemini (`gemini-3.5-flash`, `gemini-2.5-flash`, etc.).
- **Function / Tool Calling**: Ayaka can look up deadlines, search upcoming classes, add new tasks via natural language, mark assignments done, and query system status during casual chat.
- **Persistent Chat History**: Backed by SQLite `ai_conversations` table with automatic TTL pruning (>48h), maintaining memory across bot restarts and deployments.

---

## 🏛️ Architecture & Directory Structure

```text
projects/ayaka/
├── .env.example                       # Template for private credentials and tokens
├── config.json                        # Operational settings (Gmail keywords, intervals, URLs)
├── dialogues.json                     # Character voice lines and persona scenarios
├── task_filters.json                  # Task rules, course filters, and blacklist
├── Dockerfile                         # Production Python 3.12 container definition
├── docker-compose.yml                 # Container service with volume persistence
├── pyproject.toml                     # Project metadata and dependencies
├── requirements.txt                   # Pinned dependency specifications
├── CODE_REVIEW_AND_REFACTORING_ROADMAP.md # Engineering architecture & refactoring roadmap
├── README.md                          # Main documentation and operational guide
├── ayaka/
│   ├── config.py                      # Dataclass-based settings loader (.env + config.json)
│   ├── cli.py                         # Unified terminal CLI (status, list, add, complete, bot, sync)
│   ├── dialogue.py                    # Dialogue manager & Discord UI formatting helpers
│   ├── scheduler.py                   # Async periodic loops (sync, reminder, gmail, schedule)
│   ├── task_filters.py                # Blacklist & course filtering engine
│   ├── main.py                        # 24/7 background daemon runner (DaemonBot)
│   ├── core/                          # Core domain utilities
│   │   └── time.py                    # Unified timezone & natural language date parser
│   ├── fetchers/                      # Asynchronous LMS scrapers & clients
│   │   ├── base.py                    # BaseFetcher abstraction & sync/async bridges
│   │   ├── edunex.py                  # Edunex ITB async fetcher (concurrent tasks)
│   │   ├── six.py                     # SIX ITB async scraper (concurrent modal dialogs)
│   │   ├── omnicampus.py              # Omnicampus API async client
│   │   └── gmail_reader.py            # Gmail API monitor
│   ├── storage/                       # Storage & Repository Layer
│   │   ├── connection.py              # Thread-safe persistent connection manager (WAL mode)
│   │   ├── db.py                      # High-level database coordinator facade
│   │   └── repositories/              # Domain-specific repositories
│   │       ├── task_repo.py           # Task CRUD & milestone queries
│   │       ├── meeting_repo.py        # Lecture meeting range queries
│   │       ├── alert_repo.py          # Session & reminder logs
│   │       └── ai_repo.py             # Persistent conversational memory with TTL pruning
│   ├── services/                      # Application Domain Services
│   │   ├── ai_agent.py                # Gemini AI agent with function calling
│   │   ├── google_sync.py             # Google Tasks & Calendar sync service
│   │   ├── schedule_service.py        # Class meeting & schedule reminder manager
│   │   └── discord_bot.py             # Facade export for Discord client
│   └── discord/                       # Modular Discord Bot UI & Cogs
│       ├── bot.py                     # AyakaBot client & global error handling
│       ├── constants.py               # Theme colors, icons, and emojis
│       ├── views/                     # Discord UI component views
│       │   ├── pagination.py          # TaskPaginationView
│       │   ├── task_actions.py        # TaskActionView
│       │   └── meeting_actions.py     # AttendanceActionView, ClassStartActionView
│       ├── formatters/                # Discord Embed builders
│       │   ├── schedule_embed.py      # Schedule embed formatter
│       │   ├── sync_embed.py          # Multi-platform sync embed formatter
│       │   └── task_embed.py          # Task reminder & upcoming embeds
│       └── cogs/                      # Discord App Command Cogs
│           ├── academic_cog.py        # /tasks, /upcoming, /sync, /add, /complete, /blacklist
│           ├── schedule_cog.py        # /schedule (today, tomorrow, week, date picker)
│           ├── admin_cog.py           # /status, /session, /filter, /ping
│           └── ai_cog.py              # /ai, mention listener (@Ayaka)
└── tests/                             # Comprehensive test suite (46 passed)
    ├── test_ai_agent.py               # AI tool calling & natural date tests
    ├── test_async_fetchers.py         # Async fetchers, concurrency & dynamic config tests
    ├── test_config.py                 # Configuration loading & override tests
    ├── test_core_time.py              # Timezone & date parsing tests
    ├── test_dialogue_and_ui.py        # Dialogue manager & UI progress bar tests
    ├── test_discord_cogs.py           # Cogs loading & views initialization tests
    ├── test_enhancements.py           # Blacklist filters & WAL mode tests
    ├── test_repositories.py           # Repository pattern & AI history pruning tests
    ├── test_schedule_service.py       # Meeting enrichment & calendar tests
    └── test_storage_and_milestones.py # Task milestone evaluation tests
```

---

## ⚙️ Configuration Setup

### 1. Copy Environment Template
```bash
cp .env.example .env
```

### 2. Fill in Private Credentials (`.env`)
```ini
# Discord Bot
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_USER_ID=your_discord_user_id

# Academic Platform Cookies & Tokens
EDUNEX_COOKIE=your_edunex_cookie_or_token
SIX_COOKIE=ci_session=your_six_cookie
OMNICAMPUS_TOKEN=your_omnicampus_token

# Google Workspace (Optional Overrides)
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_TOKEN_FILE=token.json

# Gemini AI (Optional)
AI_API_KEY=your_gemini_api_key
AI_MODEL=gemini-3.5-flash
```

### 3. Operational Settings (`config.json`)
You can fine-tune academic sync intervals, semester codes, and student ID directly in `config.json` without touching Python files:
```json
{
  "system": {
    "timezone": "Asia/Jakarta",
    "database_path": "data/ayaka_state.db"
  },
  "platforms": {
    "edunex": {
      "base_url": "https://edunex.itb.ac.id",
      "period_id": 26
    },
    "six": {
      "base_url": "https://six.itb.ac.id",
      "student_id": "<your-NIM>",
      "semester_code": "2026-1"
    },
    "omnicampus": {
      "base_url": "https://edu.omnicamp.us",
      "course_ids": [170]
    }
  },
  "scheduler": {
    "academic_sync_interval_minutes": 30,
    "reminder_poll_interval_seconds": 60
  }
}
```

---

## 🚀 Deployment & Running

### Method A: Docker Compose on VPS (Recommended for 24/7 Production)

1. Clone or upload the repository to your VPS.
2. Configure `.env` with your credentials.
3. Start the container in background daemon mode:
   ```bash
   docker compose up -d --build
   ```
4. View live logs:
   ```bash
   docker compose logs -f
   ```
5. Manage container lifecycle:
   ```bash
   docker compose restart   # Restart bot service
   docker compose down      # Stop bot service
   ```

*Persistent SQLite data is safely stored in `./data` on the host.*

---

### Method B: Systemd Service (Native Linux VPS)

A pre-configured service file `ayaka.service` is included:
```bash
sudo cp ayaka.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ayaka
sudo journalctl -u ayaka -f
```

---

### Method C: Local Virtual Environment / CLI

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the 24/7 Daemon
python -m ayaka.main

# Or run via CLI
python -m ayaka.cli bot
```

---

## 💻 CLI Commands

The `ayaka.cli` module allows manual ledger management and sync triggers:

```bash
# Check system status and credentials
python -m ayaka.cli status

# List active pending tasks
python -m ayaka.cli list
python -m ayaka.cli list --all
python -m ayaka.cli list --platform edunex

# Mark a task completed manually
python -m ayaka.cli complete <TASK_ID>

# Add a manual task (supports natural language dates)
python -m ayaka.cli add "Tugas Besar Milestone 1" "2026-10-25T23:59:00" --course "IF4031"

# Trigger an on-demand async sync cycle
python -m ayaka.cli sync
python -m ayaka.cli sync --platform six
```

---

## 🎮 Discord Slash Commands

Ayaka provides rich slash commands organized by domain:

### Academic Commands (`AcademicCog`)
| Command | Description |
| :--- | :--- |
| `/tasks [all_tasks] [platform]` | Interactive pagination view of pending/all assignments. |
| `/upcoming [days]` | Summary of assignments due in the next *N* days (default: 7). |
| `/sync [platform]` | Triggers on-demand async synchronization across platforms. |
| `/add <title> <due_date> [course] [desc]` | Adds a manual assignment (accepts ISO or natural language dates). |
| `/complete <task_id>` | Marks an assignment completed directly from Discord. |
| `/blacklist <task_id> [reason]` | Blacklists an assignment ID so it won't be synced again. |

### Schedule Commands (`ScheduleCog`)
| Command | Description |
| :--- | :--- |
| `/schedule [view] [date]` | Views lecture schedules (`today`, `tomorrow`, `week`, or a specific date) with class room, lecturer, topic, Teams link, and attendance window. |

### AI Assistant Commands (`AICog`)
| Command | Description |
| :--- | :--- |
| `/ai <prompt>` | Converse with Ayaka AI. Supports tool calling (querying schedule, checking tasks, adding reminders). |
| `@Ayaka <message>` | Mention Ayaka anywhere in a channel to chat naturally. Maintains 48-hour conversation memory. |

### Administrative Commands (`AdminCog`)
| Command | Description |
| :--- | :--- |
| `/status` | Displays system health, uptime, configured services, and task counts. |
| `/session` | Step-by-step guide to extract and refresh expired cookies. |
| `/filter` | Inspects currently active course filters and task blacklists. |
| `/ping` | Checks bot latency and responsiveness. |

---

## 🧪 Testing & Quality Assurance

Ayaka includes a comprehensive unit test suite covering configuration parsing, repository caching, time parsing, Discord Cogs, async fetchers, and background milestone evaluation.

Run tests using pytest:
```bash
pytest -v
```

Output:
```text
======================== 46 passed, 1 warning in 2.52s =========================
```

---

## 🔒 Security Best Practices

- **Zero Credential Commits**: `.env`, `credentials.json`, `token.json`, and `data/*.db` are strictly ignored by `.gitignore`.
- **Thread-Safe SQLite**: Uses thread-local persistent connections with WAL mode and 5000ms busy timeout to prevent database locks.
- **Automatic TTL Cleanup**: Chat histories older than 48 hours are automatically pruned from the database to conserve memory and protect privacy.

---

## 📜 License

Private project developed for academic productivity at Institut Teknologi Bandung.
All character references to Kamisato Ayaka belong to © miHoYo / HoYoverse.
