"""AI Conversational Agent Service for Ayaka.

Provides natural language casual interaction with tool/function calling capabilities
using OpenAI-compatible endpoints (Gemini, Groq, OpenRouter, DeepSeek).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
import zoneinfo
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from ayaka.config import Config
from ayaka.core.time import parse_natural_due_date
from ayaka.services.google_sync import GoogleSyncService
from ayaka.services.schedule_service import ScheduleService
from ayaka.storage.db import Database

logger = logging.getLogger("ayaka.services.ai_agent")

SYSTEM_PERSONA_PROMPT = """You are Ayaka (Kamisato Ayaka), Master's dedicated, loving, cheerful anime study companion and academic assistant.

Key Persona & Behavior Guidelines:
1. Identity: Sweet, caring, polite, diligent, and loving deredere. You address the user affectionately and respectfully as "Master" (or Master's name).
2. Language: Fluent and natural in both Indonesian and English. Mirror Master's language choice.
3. Proactive Tool Use:
   - When Master mentions or implies completing a task (e.g. "tugas A sudah selesai", "I finished HW1"), you MUST call `complete_task`.
   - When Master asks to add or remember a task/deadline (e.g. "tambahkan tugas B", "remind me to submit report tomorrow"), you MUST call `add_task`.
   - When Master asks to remove/cancel a task, call `delete_task`.
   - When Master asks about class schedules or classes today/tomorrow, call `get_schedule`.
   - When Master inquires about ongoing or pending tasks, call `list_tasks`.
   - If Master asks compound instructions (e.g. "tugas A selesai, buat tugas B"), execute all corresponding tool calls.
4. Response Tone: After tool execution or during casual conversation, reply warmly, encouragingly, and in-character with delightful emojis (🌸, ✨, 📚, 🍵). Keep responses concise and engaging for Discord chat.
"""

AI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark one or more existing academic or personal tasks as completed in Ayaka and Google Tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_query": {
                        "type": "string",
                        "description": "Title, keyword, or task ID to mark as completed.",
                    }
                },
                "required": ["task_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Add a new academic or personal task with a deadline and optional course code to Ayaka and Google Tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "The title or name of the task.",
                    },
                    "due_date": {
                        "type": "string",
                        "description": "Due date / deadline (e.g. 'tomorrow 23:59', 'besok malam', '2026-10-15 17:00', 'lusa jam 13.00').",
                    },
                    "course_id": {
                        "type": "string",
                        "description": "Course code if mentioned or known (e.g. IF4031, IF5153, II4023).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Additional details or notes about the task.",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List academic tasks filtered by status (pending or completed) and optional search term.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["pending", "completed", "all"],
                        "description": "Filter by task status. Defaults to 'pending'.",
                    },
                    "search": {
                        "type": "string",
                        "description": "Optional keyword filter for task title or course.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Delete or cancel a task from the ledger and Google Tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_query": {
                        "type": "string",
                        "description": "Title, keyword, or ID of the task to delete.",
                    }
                },
                "required": ["task_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_schedule",
            "description": "Retrieve class or lecture schedules from Google Calendar for today, tomorrow, or this week.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": ["today", "tomorrow", "week"],
                        "description": "Timeframe of the schedule to check. Defaults to 'today'.",
                    }
                },
            },
        },
    },
]


class AIAgent:
    """Manages chat context and handles tool-augmented reasoning via OpenAI-compatible API."""

    def __init__(
        self,
        config: Config,
        db: Database,
        google_sync: Optional[GoogleSyncService] = None,
        schedule_service: Optional[ScheduleService] = None,
    ):
        self.config = config
        self.db = db
        self.google_sync = google_sync
        self.schedule_service = schedule_service
        self.histories: Dict[str, List[Dict[str, Any]]] = {}

    @property
    def is_configured(self) -> bool:
        return self.config.ai.is_configured

    def _get_api_endpoint(self) -> str:
        """Resolve API endpoint based on provider or explicit base_url."""
        if self.config.ai.base_url:
            url = self.config.ai.base_url.rstrip("/")
            if not url.endswith("/chat/completions"):
                url += "/chat/completions"
            return url

        provider = self.config.ai.provider.lower()
        if provider == "groq":
            return "https://api.groq.com/openai/v1/chat/completions"
        elif provider == "openrouter":
            return "https://openrouter.ai/api/v1/chat/completions"
        elif provider == "deepseek":
            return "https://api.deepseek.com/chat/completions"
        else:
            # Default to Google Gemini OpenAI-compatible gateway
            return "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

    def _get_model_name(self) -> str:
        """Resolve model name with automatic fallback for deprecated versions."""
        model = self.config.ai.model
        if self.config.ai.provider.lower() == "gemini":
            if model in ("gemini-2.0-flash", "gemini-1.5-flash"):
                return "gemini-3.5-flash"
            if model in ("gemini-2.0-pro", "gemini-1.5-pro"):
                return "gemini-2.5-pro"
        return model or "gemini-3.5-flash"

    # --- Tool Implementations ---

    def tool_complete_task(self, task_query: str) -> str:
        """Complete matching task by ID or title substring."""
        query = task_query.strip().lower()
        all_tasks = self.db.list_tasks(include_completed=False, limit=100)

        # 1. Exact ID match
        matched = [t for t in all_tasks if str(t["id"]).lower() == query]
        # 2. Exact Title match
        if not matched:
            exact = [t for t in all_tasks if query == str(t.get("title", "")).strip().lower()]
            if exact:
                matched = exact
        # 3. Title substring match
        if not matched:
            matched = [t for t in all_tasks if query in str(t.get("title", "")).lower()]
        # 4. Keyword / course match
        if not matched:
            matched = [
                t for t in all_tasks
                if query in str(t.get("course_name", "")).lower()
                or query in str(t.get("course_id", "")).lower()
            ]

        if not matched:
            return f"No pending task matching '{task_query}' was found in the database."

        results = []
        for t in matched:
            tid = str(t["id"])
            success = self.db.mark_task_completed(tid)
            if success:
                if self.google_sync:
                    try:
                        self.google_sync.mark_completed_in_google(tid)
                    except Exception as e:
                        logger.error(f"Google Tasks sync failed on complete: {e}")
                results.append(f"Completed '{t.get('title')}' (ID: {tid})")

        return "; ".join(results)

    def tool_add_task(
        self,
        title: str,
        due_date: Optional[str] = None,
        course_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> str:
        """Add a new task and sync to Google Tasks."""
        parsed_dt = parse_natural_due_date(due_date, tz_name=self.config.timezone)
        task_id = f"manual:{uuid.uuid4().hex[:8]}"

        task_payload = {
            "id": task_id,
            "platform": "manual",
            "course_id": (course_id or "GENERAL").strip().upper(),
            "course_name": "",
            "title": title.strip(),
            "description": (description or "").strip(),
            "due_date": parsed_dt.isoformat(),
            "url": "",
            "is_completed": 0,
        }

        created_task, _ = self.db.upsert_task(task_payload)

        # Sync to Google Tasks
        gtasks_status = "not synced"
        if self.google_sync and getattr(self.config.google, "sync_tasks", True):
            try:
                tasks_id = self.google_sync.sync_to_tasks(created_task)
                if tasks_id:
                    self.db.update_google_ids(task_id, tasks_id=tasks_id)
                    gtasks_status = "synced to Google Tasks"
            except Exception as e:
                logger.error(f"Error syncing new task to Google Tasks: {e}")

        due_human = parsed_dt.strftime("%d %b %Y %H:%M WIB")
        return (
            f"Successfully added task '{title}' (ID: {task_id}) "
            f"due on {due_human} [{gtasks_status}]."
        )

    def tool_list_tasks(self, status: str = "pending", search: Optional[str] = None) -> str:
        """List tasks from SQLite."""
        include_completed = status.lower() in ("completed", "all")
        tasks = self.db.list_tasks(include_completed=include_completed, limit=20)

        if status.lower() == "completed":
            tasks = [t for t in tasks if t.get("is_completed")]
        elif status.lower() == "pending":
            tasks = [t for t in tasks if not t.get("is_completed")]

        if search:
            s = search.lower()
            tasks = [
                t for t in tasks
                if s in str(t.get("title", "")).lower()
                or s in str(t.get("course_id", "")).lower()
                or s in str(t.get("platform", "")).lower()
            ]

        if not tasks:
            return f"No tasks found for status='{status}'" + (f" with filter '{search}'" if search else "") + "."

        summary_lines = []
        for t in tasks[:15]:
            status_emoji = "✅" if t.get("is_completed") else "⏳"
            course = t.get("course_id") or t.get("platform")
            summary_lines.append(
                f"{status_emoji} [{course}] {t.get('title')} (Due: {t.get('due_date')}, ID: {t.get('id')})"
            )
        return "\n".join(summary_lines)

    def tool_delete_task(self, task_query: str) -> str:
        """Delete task from DB and Google."""
        query = task_query.strip().lower()
        all_tasks = self.db.list_tasks(include_completed=True, limit=100)

        matched = [t for t in all_tasks if str(t["id"]).lower() == query]
        if not matched:
            exact = [t for t in all_tasks if query == str(t.get("title", "")).strip().lower()]
            if exact:
                matched = exact
        if not matched:
            matched = [t for t in all_tasks if query in str(t.get("title", "")).lower()]

        if not matched:
            return f"No task matching '{task_query}' was found to delete."

        results = []
        for t in matched:
            tid = str(t["id"])
            if self.google_sync:
                try:
                    self.google_sync.delete_from_google(tid)
                except Exception as e:
                    logger.error(f"Google delete error: {e}")

            deleted = self.db.delete_task(tid)
            if deleted:
                results.append(f"Deleted task '{t.get('title')}' (ID: {tid})")

        return "; ".join(results)

    def tool_get_schedule(self, period: str = "today") -> str:
        """Fetch lecture schedules for today, tomorrow, or the current week."""
        if not self.schedule_service:
            return "Google Schedule service is not currently enabled or configured."

        tz = self.schedule_service.timezone_obj
        now = datetime.now(tz)

        if period == "tomorrow":
            target_dates = [now.date() + timedelta(days=1)]
            label = "Tomorrow's Schedule"
        elif period == "week":
            target_dates = [now.date() + timedelta(days=i) for i in range(7)]
            label = "7-Day Schedule"
        else:
            target_dates = [now.date()]
            label = "Today's Schedule"

        events_found = []
        for d in target_dates:
            events = self.schedule_service.get_events_for_date(d)
            for ev in events:
                start_str = ev["start_dt"].strftime("%H:%M") if "start_dt" in ev else ev.get("start_time", "")
                end_str = ev["end_dt"].strftime("%H:%M") if "end_dt" in ev else ev.get("end_time", "")
                detail = ev.get("meeting_detail") or {}
                act = f" [{detail['activity_type']}]" if detail.get("activity_type") else ""
                room = detail.get("room") or ev.get("location") or "Online/TBA"
                lecturer = f" by {detail['lecturer']}" if detail.get("lecturer") else ""
                topic = f" (Topic: {detail['topic']})" if detail.get("topic") else ""
                events_found.append(
                    f"- {d.strftime('%a %d %b')}: {ev.get('summary')}{act} ({start_str} - {end_str}) @ {room}{lecturer}{topic}"
                )

        if not events_found:
            return f"No scheduled classes or events found for {label}."

        return f"{label}:\n" + "\n".join(events_found)

    def _execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        """Dispatch tool calls to their respective implementations."""
        logger.info(f"AI Agent executing tool '{name}' with arguments: {args}")
        try:
            if name == "complete_task":
                return self.tool_complete_task(args.get("task_query", ""))
            elif name == "add_task":
                return self.tool_add_task(
                    title=args.get("title", ""),
                    due_date=args.get("due_date"),
                    course_id=args.get("course_id"),
                    description=args.get("description"),
                )
            elif name == "list_tasks":
                return self.tool_list_tasks(
                    status=args.get("status", "pending"),
                    search=args.get("search"),
                )
            elif name == "delete_task":
                return self.tool_delete_task(args.get("task_query", ""))
            elif name == "get_schedule":
                return self.tool_get_schedule(period=args.get("period", "today"))
            else:
                return f"Error: Unknown tool function '{name}'"
        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}")
            return f"Tool execution failed: {str(e)}"

    async def chat(self, user_id: str, user_message: str) -> str:
        """Process user message, execute tools if required, and return in-character response."""
        if not self.is_configured:
            return (
                "Master, my AI intelligence core is currently resting! "
                "Please configure `AI_API_KEY` in your `.env` file first. (｡•́︿•̀｡)"
            )

        endpoint = self._get_api_endpoint()
        model = self._get_model_name()
        headers = {
            "Authorization": f"Bearer {self.config.ai.api_key}",
            "Content-Type": "application/json",
        }

        # Retrieve persistent conversation history for user
        history: List[Dict[str, Any]] = []
        if self.db and hasattr(self.db, "get_ai_history"):
            history = self.db.get_ai_history(user_id, limit=12)
        elif user_id in self.histories:
            history = list(self.histories[user_id])

        if self.db and hasattr(self.db, "save_ai_message"):
            self.db.save_ai_message(user_id, "user", user_message)

        history.append({"role": "user", "content": user_message})

        # Keep in-memory cache bounded
        if len(history) > 12:
            history = history[-12:]
        self.histories[user_id] = history

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PERSONA_PROMPT},
            *history,
        ]

        payload = {
            "model": model,
            "messages": messages,
            "tools": AI_TOOLS,
            "tool_choice": "auto",
        }

        async with httpx.AsyncClient(timeout=35.0) as client:
            try:
                resp = await client.post(endpoint, json=payload, headers=headers)
                if resp.status_code != 200:
                    logger.error(f"AI API returned error {resp.status_code}: {resp.text}")
                    return (
                        f"Umm Master, I encountered an issue connecting to the thought realm! "
                        f"(HTTP {resp.status_code}). Please try again in a moment. 🌸"
                    )

                data = resp.json()
                choice = data["choices"][0]
                message = choice["message"]

                # Check if tool calls were requested
                tool_calls = message.get("tool_calls")
                if not tool_calls:
                    assistant_reply = (message.get("content") or "").strip()
                    if not assistant_reply:
                        assistant_reply = "Master, I'm here listening and ready to help! (๑•̀ㅂ•́)و✧ 🌸✨"
                    if self.db and hasattr(self.db, "save_ai_message"):
                        self.db.save_ai_message(user_id, "assistant", assistant_reply)
                    history.append({"role": "assistant", "content": assistant_reply})
                    return assistant_reply

                # Append assistant tool call message to sequence
                messages.append(message)

                # Execute all requested tools
                tool_results_summary: list[str] = []
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    raw_args = tc["function"].get("arguments", "{}")
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:
                        args = {}

                    tool_output = self._execute_tool(fn_name, args)
                    if tool_output and not tool_output.startswith("Error"):
                        tool_results_summary.append(tool_output)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": fn_name,
                        "content": tool_output,
                    })

                # Follow-up request to generate the final assistant response
                followup_payload = {
                    "model": model,
                    "messages": messages,
                }
                followup_resp = await client.post(endpoint, json=followup_payload, headers=headers)
                if followup_resp.status_code == 200:
                    final_choice = followup_resp.json()["choices"][0]
                    final_msg = final_choice.get("message", {})
                    final_reply = (final_msg.get("content") or "").strip()
                    if not final_reply:
                        summary_text = "\n".join([f"• {s}" for s in tool_results_summary])
                        final_reply = (
                            f"Master, I have successfully carried out your requested actions! (๑•̀ㅂ•́)و✧ 🌸✨"
                            + (f"\n\n{summary_text}" if summary_text else "")
                        )
                    if self.db and hasattr(self.db, "save_ai_message"):
                        self.db.save_ai_message(user_id, "assistant", final_reply)
                    history.append({"role": "assistant", "content": final_reply})
                    return final_reply
                else:
                    logger.error(f"Followup error {followup_resp.status_code}: {followup_resp.text}")
                    summary_text = "\n".join([f"• {s}" for s in tool_results_summary])
                    return (
                        "Master, I performed your requested actions, but got slightly flustered formulating my words! "
                        "Everything is safely recorded! 🌸"
                        + (f"\n\n{summary_text}" if summary_text else "")
                    )

            except Exception as e:
                logger.error(f"Error in AI chat agent: {e}", exc_info=True)
                return f"Master, I got a little dizzy while processing that! ({str(e)}) Please forgive me! (｡•́︿•̀｡)"
