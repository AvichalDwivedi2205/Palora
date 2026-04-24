from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.actions.browser_managed import BrowserManagedAdapter
from app.actions.calendar_event import CalendarEventAdapter
from app.actions.mail_draft import MailDraftAdapter
from app.actions.reminders import RemindersAdapter
from app.model.embeddings import lexical_similarity
from app.orchestrator.schemas import (
    ChatMessage,
    DraftItem,
    GraphEdge,
    GraphNode,
    GraphOverlay,
    GraphResponse,
    IngestJobResponse,
    IngestSourceRequest,
    InspectorPayload,
    PendingAction,
    QueueItem,
    RetrievalPlan,
    SessionSnapshot,
    TimelineItem,
)
from app.policy.engine import PolicyEngine
from app.settings import Settings
from app.writeback.service import WritebackService


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class SearchResult:
    id: str
    score: float
    text: str
    title: str
    source_id: str
    kind: str


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA busy_timeout=5000;")
        self.conn.execute("PRAGMA foreign_keys=ON;")

    def init(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS app_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          active_entity_id TEXT,
          status TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          structured_json TEXT,
          created_at TEXT NOT NULL,
          trace_id TEXT,
          FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS source_events (
          id TEXT PRIMARY KEY,
          source_type TEXT NOT NULL,
          source_ref TEXT NOT NULL,
          timestamp TEXT NOT NULL,
          title TEXT NOT NULL,
          text_path TEXT,
          raw_text TEXT NOT NULL,
          metadata_json TEXT NOT NULL,
          checksum TEXT NOT NULL,
          ingest_status TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS source_chunks (
          id TEXT PRIMARY KEY,
          source_event_id TEXT NOT NULL,
          chunk_index INTEGER NOT NULL,
          text TEXT NOT NULL,
          checksum TEXT NOT NULL,
          mempalace_drawer_id TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(source_event_id) REFERENCES source_events(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS entities (
          id TEXT PRIMARY KEY,
          display_name TEXT NOT NULL,
          entity_type TEXT NOT NULL,
          aliases_json TEXT NOT NULL,
          metadata_json TEXT NOT NULL,
          summary TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'active',
          confidence REAL NOT NULL DEFAULT 0.8,
          cluster_id TEXT,
          last_seen_at TEXT
        );

        CREATE TABLE IF NOT EXISTS profile_memories (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          text TEXT NOT NULL,
          scope TEXT NOT NULL,
          entity_id TEXT,
          approved INTEGER NOT NULL DEFAULT 1,
          confidence REAL NOT NULL DEFAULT 0.8,
          source_event_ids_json TEXT NOT NULL,
          last_used_at TEXT,
          FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS style_profiles (
          id TEXT PRIMARY KEY,
          user_or_entity_scope TEXT NOT NULL,
          avg_sentence_length REAL NOT NULL,
          greeting_patterns_json TEXT NOT NULL,
          signoff_patterns_json TEXT NOT NULL,
          verbosity TEXT NOT NULL,
          formality TEXT NOT NULL,
          notes_json TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS draft_artifacts (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          title TEXT NOT NULL,
          summary TEXT NOT NULL,
          body TEXT NOT NULL,
          status TEXT NOT NULL,
          citations_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS graph_edges (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          source TEXT NOT NULL,
          target TEXT NOT NULL,
          weight REAL NOT NULL,
          status TEXT NOT NULL,
          evidence_ids_json TEXT NOT NULL,
          last_updated_at TEXT NOT NULL,
          metadata_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS action_plans (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          tool_name TEXT NOT NULL,
          intent TEXT NOT NULL,
          risk_class INTEGER NOT NULL,
          status TEXT NOT NULL,
          prepared_args_json TEXT NOT NULL,
          prepared_hash TEXT NOT NULL,
          memory_refs_json TEXT NOT NULL,
          reason TEXT NOT NULL,
          expires_at TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS action_approvals (
          id TEXT PRIMARY KEY,
          action_plan_id TEXT NOT NULL,
          decision TEXT NOT NULL,
          decided_at TEXT NOT NULL,
          decider TEXT NOT NULL,
          notes TEXT,
          FOREIGN KEY(action_plan_id) REFERENCES action_plans(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS action_runs (
          id TEXT PRIMARY KEY,
          action_plan_id TEXT NOT NULL,
          adapter_name TEXT NOT NULL,
          request_json TEXT NOT NULL,
          result_json TEXT NOT NULL,
          rollback_json TEXT,
          started_at TEXT NOT NULL,
          finished_at TEXT NOT NULL,
          status TEXT NOT NULL,
          FOREIGN KEY(action_plan_id) REFERENCES action_plans(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY,
          job_type TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          status TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0,
          scheduled_at TEXT NOT NULL,
          started_at TEXT,
          finished_at TEXT,
          error_text TEXT
        );

        CREATE TABLE IF NOT EXISTS audit_events (
          id TEXT PRIMARY KEY,
          trace_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          subject_id TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        """
        with self.lock:
            self.conn.executescript(schema)
            self.conn.commit()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self.lock:
            self.conn.execute(sql, params)
            self.conn.commit()

    def executemany(self, sql: str, params: list[tuple[Any, ...]]) -> None:
        with self.lock:
            self.conn.executemany(sql, params)
            self.conn.commit()

    def query_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return list(self.conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def json_dumps(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=True)

    def json_loads(self, value: str | None, default: Any) -> Any:
        if not value:
            return default
        return json.loads(value)

    def make_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:10]}"

    def set_meta(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def get_meta(self, key: str) -> str | None:
        row = self.query_one("SELECT value FROM app_meta WHERE key = ?", (key,))
        return row["value"] if row else None

    def upsert_entity(
        self,
        entity_id: str,
        display_name: str,
        entity_type: str,
        summary: str,
        aliases: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        cluster_id: str | None = None,
        confidence: float = 0.8,
    ) -> None:
        existing = self.query_one("SELECT * FROM entities WHERE id = ?", (entity_id,))
        existing_aliases = self.json_loads(existing["aliases_json"], []) if existing else []
        merged_aliases = list(dict.fromkeys([*(aliases or []), *existing_aliases]))
        existing_metadata = self.json_loads(existing["metadata_json"], {}) if existing else {}
        merged_metadata = {**(metadata or {}), **existing_metadata}
        merged_summary = existing["summary"] if existing and existing["summary"] else summary
        merged_confidence = max(float(existing["confidence"]), confidence) if existing else confidence
        merged_cluster_id = existing["cluster_id"] if existing and existing["cluster_id"] else cluster_id
        self.execute(
            """
            INSERT INTO entities (
              id, display_name, entity_type, aliases_json, metadata_json, summary,
              status, confidence, cluster_id, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              display_name=excluded.display_name,
              entity_type=excluded.entity_type,
              aliases_json=excluded.aliases_json,
              metadata_json=excluded.metadata_json,
              summary=excluded.summary,
              confidence=excluded.confidence,
              cluster_id=excluded.cluster_id,
              last_seen_at=excluded.last_seen_at
            """,
            (
                entity_id,
                display_name,
                entity_type,
                self.json_dumps(merged_aliases),
                self.json_dumps(merged_metadata),
                merged_summary,
                merged_confidence,
                merged_cluster_id,
                isoformat(utcnow()),
            ),
        )

    def upsert_edge(
        self,
        edge_id: str,
        kind: str,
        source: str,
        target: str,
        weight: float,
        evidence_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "active",
    ) -> None:
        self.execute(
            """
            INSERT INTO graph_edges (
              id, kind, source, target, weight, status, evidence_ids_json, last_updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              kind=excluded.kind,
              source=excluded.source,
              target=excluded.target,
              weight=excluded.weight,
              status=excluded.status,
              evidence_ids_json=excluded.evidence_ids_json,
              last_updated_at=excluded.last_updated_at,
              metadata_json=excluded.metadata_json
            """,
            (
                edge_id,
                kind,
                source,
                target,
                weight,
                status,
                self.json_dumps(evidence_ids or []),
                isoformat(utcnow()),
                self.json_dumps(metadata or {}),
            ),
        )

    def create_action_plan(
        self,
        session_id: str,
        tool_name: str,
        intent: str,
        risk_class: int,
        prepared_args: dict[str, Any],
        memory_refs: list[str],
        reason: str,
        status: str,
        expires_at: datetime | None = None,
    ) -> sqlite3.Row:
        canonical = self.json_dumps(prepared_args)
        prepared_hash = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        plan_id = self.make_id("plan")
        now = isoformat(utcnow())
        self.execute(
            """
            INSERT INTO action_plans (
              id, session_id, tool_name, intent, risk_class, status, prepared_args_json,
              prepared_hash, memory_refs_json, reason, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                session_id,
                tool_name,
                intent,
                risk_class,
                status,
                canonical,
                prepared_hash,
                self.json_dumps(memory_refs),
                reason,
                isoformat(expires_at) if expires_at else None,
                now,
            ),
        )
        return self.query_one("SELECT * FROM action_plans WHERE id = ?", (plan_id,))

    def create_message(
        self,
        session_id: str,
        role: str,
        content: str,
        structured: dict[str, Any] | None,
        trace_id: str | None = None,
    ) -> str:
        message_id = self.make_id("msg")
        self.execute(
            """
            INSERT INTO messages (id, session_id, role, content, structured_json, created_at, trace_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                session_id,
                role,
                content,
                self.json_dumps(structured) if structured is not None else None,
                isoformat(utcnow()),
                trace_id,
            ),
        )
        return message_id

    def create_draft(
        self,
        session_id: str,
        kind: str,
        title: str,
        summary: str,
        body: str,
        status: str,
        citations: list[str],
    ) -> str:
        draft_id = self.make_id("draft")
        now = isoformat(utcnow())
        self.execute(
            """
            INSERT INTO draft_artifacts (
              id, session_id, kind, title, summary, body, status, citations_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (draft_id, session_id, kind, title, summary, body, status, self.json_dumps(citations), now, now),
        )
        return draft_id


class MemoryService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _row_to_node(self, row: sqlite3.Row) -> GraphNode:
        edge_count_row = self.db.query_one(
            "SELECT COUNT(*) AS count FROM graph_edges WHERE source = ? OR target = ?",
            (row["id"], row["id"]),
        )
        evidence_count = len(self._related_source_ids(row["id"]))
        open_loops = self.db.query_one(
            "SELECT COUNT(*) AS count FROM graph_edges WHERE source = ? AND kind IN ('waiting_on', 'promised')",
            (row["id"],),
        )
        metadata = self.db.json_loads(row["metadata_json"], {})
        timestamps = metadata.get("timestamps", {})
        return GraphNode(
            id=row["id"],
            kind=row["entity_type"],
            label=row["display_name"],
            summary=row["summary"],
            status=row["status"],
            confidence=float(row["confidence"]),
            cluster_id=row["cluster_id"],
            cluster_label=metadata.get("cluster_label"),
            cluster_kind=metadata.get("cluster_kind"),
            counts={
                "edges": int(edge_count_row["count"]) if edge_count_row else 0,
                "evidence": evidence_count,
                "open_loops": int(open_loops["count"]) if open_loops else 0,
            },
            timestamps={
                "first_seen_at": timestamps.get("first_seen_at"),
                "last_seen_at": row["last_seen_at"],
            },
            metadata=metadata,
        )

    def _row_to_edge(self, row: sqlite3.Row) -> GraphEdge:
        return GraphEdge(
            id=row["id"],
            kind=row["kind"],
            source=row["source"],
            target=row["target"],
            weight=float(row["weight"]),
            status=row["status"],
            evidence_ids=self.db.json_loads(row["evidence_ids_json"], []),
            last_updated_at=row["last_updated_at"],
            metadata=self.db.json_loads(row["metadata_json"], {}),
        )

    def _related_source_ids(self, entity_id: str) -> list[str]:
        rows = self.db.query_all(
            """
            SELECT DISTINCT source_event_id
            FROM source_chunks
            WHERE lower(text) LIKE '%' || lower(?) || '%'
            """,
            (entity_id.replace("ent_", "").replace("_", " "),),
        )
        return [row["source_event_id"] for row in rows]

    def resolve_focus_entities(self, message: str) -> list[str]:
        lowered = message.lower()
        matches: list[str] = []
        rows = self.db.query_all("SELECT id, display_name, aliases_json FROM entities")
        for row in rows:
            aliases = self.db.json_loads(row["aliases_json"], [])
            haystack = [row["display_name"].lower(), row["id"].lower(), *[alias.lower() for alias in aliases]]
            if any(token and token in lowered for token in haystack):
                matches.append(row["id"])
        if not matches:
            session = self.db.query_one("SELECT active_entity_id FROM sessions WHERE id = 'sess_demo'")
            if session and session["active_entity_id"]:
                matches.append(session["active_entity_id"])
        return matches[:3]

    def build_retrieval_plan(self, message: str, intent: str) -> RetrievalPlan:
        needs = {
            "draft_text": ["recent_thread", "relationship_state", "style_examples", "procedural_rules", "source_evidence"],
            "memory_lookup": ["relationship_state", "episodic_events", "source_evidence"],
            "propose_action": ["relationship_state", "procedural_rules", "source_evidence"],
        }.get(intent, ["source_evidence", "relationship_state"])
        return RetrievalPlan(
            intent=intent,
            target_entities=self.resolve_focus_entities(message),
            needs=needs,
            deep_search="deep" in message.lower() or "full" in message.lower(),
            query=message,
        )

    def search_evidence(self, query: str, limit: int = 8, entity_ids: list[str] | None = None) -> list[SearchResult]:
        rows = self.db.query_all(
            """
            SELECT source_chunks.id, source_chunks.text, source_chunks.source_event_id, source_events.title
            FROM source_chunks
            JOIN source_events ON source_events.id = source_chunks.source_event_id
            ORDER BY source_events.timestamp DESC, source_chunks.chunk_index ASC
            """
        )
        results: list[SearchResult] = []
        for row in rows:
            score = lexical_similarity(query, row["text"])
            if entity_ids:
                boost = 0.0
                entity_rows = self.db.query_all(
                    "SELECT display_name, aliases_json FROM entities WHERE id IN ({})".format(",".join(["?"] * len(entity_ids))),
                    tuple(entity_ids),
                )
                text_lower = row["text"].lower()
                for entity_row in entity_rows:
                    aliases = self.db.json_loads(entity_row["aliases_json"], [])
                    if entity_row["display_name"].lower() in text_lower:
                        boost += 0.25
                    if any(alias.lower() in text_lower for alias in aliases):
                        boost += 0.1
                score += boost
            if score > 0.02:
                results.append(
                    SearchResult(
                        id=row["id"],
                        score=score,
                        text=row["text"],
                        title=row["title"],
                        source_id=row["source_event_id"],
                        kind="evidence",
                    )
                )
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:limit]

    def build_bundle(self, plan: RetrievalPlan) -> dict[str, Any]:
        entity_rows = []
        if plan.target_entities:
            entity_rows = self.db.query_all(
                "SELECT * FROM entities WHERE id IN ({})".format(",".join(["?"] * len(plan.target_entities))),
                tuple(plan.target_entities),
            )
        profile_rows = self.db.query_all(
            "SELECT * FROM profile_memories ORDER BY approved DESC, confidence DESC LIMIT 8"
        )
        evidence_rows = self.search_evidence(plan.query, limit=8, entity_ids=plan.target_entities)
        graph = self.graph_root("cluster", "sess_demo", plan.target_entities[0] if plan.target_entities else None, limit=12)
        citations = [
            {
                "id": result.id,
                "label": f"{result.title}",
                "kind": result.kind,
                "source_id": result.source_id,
            }
            for result in evidence_rows
        ]
        fact_rows = self.db.query_all(
            """
            SELECT graph_edges.*, source_entity.display_name AS source_label, target_entity.display_name AS target_label
            FROM graph_edges
            JOIN entities AS source_entity ON source_entity.id = graph_edges.source
            JOIN entities AS target_entity ON target_entity.id = graph_edges.target
            WHERE graph_edges.source IN ({ids}) OR graph_edges.target IN ({ids})
            ORDER BY graph_edges.weight DESC
            LIMIT 8
            """.format(ids=",".join(["?"] * max(1, len(plan.target_entities)))),
            tuple(plan.target_entities or ["ent_user"]) * 2,
        )
        return {
            "bundle_id": self.db.make_id("mb"),
            "intent": plan.intent,
            "entities": [
                {"id": row["id"], "name": row["display_name"], "type": row["entity_type"]} for row in entity_rows
            ],
            "profile_memories": [
                {"id": row["id"], "kind": row["kind"], "text": row["text"], "scope": row["scope"]} for row in profile_rows
            ],
            "procedural_rules": [
                {"id": row["id"], "text": row["text"]} for row in profile_rows if row["kind"] == "procedural"
            ],
            "style_examples": [
                {"id": row["id"], "text": row["text"]} for row in profile_rows if row["kind"] == "style"
            ],
            "kg_facts": [
                {
                    "id": row["id"],
                    "predicate": row["kind"],
                    "predicate_label": row["kind"].replace("_", " "),
                    "source": row["source"],
                    "target": row["target"],
                    "source_label": row["source_label"],
                    "target_label": row["target_label"],
                }
                for row in fact_rows
            ],
            "episodic_memories": [
                {"id": row["id"], "time": row["created_at"], "text": row["content"]}
                for row in self.db.query_all(
                    "SELECT * FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 4"
                )
            ],
            "evidence_snippets": [
                {
                    "id": result.id,
                    "text": result.text,
                    "title": result.title,
                    "source_id": result.source_id,
                    "score": result.score,
                }
                for result in evidence_rows
            ],
            "citations": citations,
            "graph_nodes": [node.model_dump() for node in graph.nodes],
            "graph_edges": [edge.model_dump() for edge in graph.edges],
        }

    def graph_root(
        self,
        mode: str,
        session_id: str,
        focus_entity_id: str | None = None,
        limit: int = 20,
    ) -> GraphResponse:
        overlays: list[GraphOverlay] = []
        if mode == "macro":
            node_rows = self.db.query_all(
                """
                SELECT * FROM entities
                WHERE entity_type IN ('person', 'organization', 'project', 'task', 'memory_rule')
                ORDER BY confidence DESC, last_seen_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        else:
            focus_entity_id = focus_entity_id or self.db.query_one(
                "SELECT active_entity_id FROM sessions WHERE id = ?", (session_id,)
            )["active_entity_id"]
            related_edge_rows = self.db.query_all(
                """
                SELECT * FROM graph_edges
                WHERE source = ? OR target = ?
                ORDER BY weight DESC, last_updated_at DESC
                LIMIT ?
                """,
                (focus_entity_id, focus_entity_id, limit),
            )
            entity_ids = {focus_entity_id}
            for row in related_edge_rows:
                entity_ids.add(row["source"])
                entity_ids.add(row["target"])
            node_rows = self.db.query_all(
                "SELECT * FROM entities WHERE id IN ({})".format(",".join(["?"] * len(entity_ids))),
                tuple(entity_ids),
            )

        nodes = [self._row_to_node(row) for row in node_rows]
        node_ids = tuple(node.id for node in nodes) or ("__none__",)
        edge_rows = self.db.query_all(
            """
            SELECT * FROM graph_edges
            WHERE source IN ({ids}) AND target IN ({ids})
            ORDER BY weight DESC, last_updated_at DESC
            LIMIT ?
            """.format(ids=",".join(["?"] * len(node_ids))),
            node_ids + node_ids + (limit,),
        )
        edges = [self._row_to_edge(row) for row in edge_rows]

        plan_rows = self.db.query_all(
            "SELECT * FROM action_plans WHERE status IN ('pending-approval', 'ready') ORDER BY created_at DESC LIMIT 10"
        )
        for row in plan_rows:
            args = self.db.json_loads(row["prepared_args_json"], {})
            target = args.get("entity_id") or focus_entity_id or "ent_user"
            overlays.append(
                GraphOverlay(
                    node_id=target,
                    overlay_kind="pending_action",
                    label=row["tool_name"].replace(".", " "),
                    severity="high" if row["risk_class"] >= 2 else "medium",
                )
            )

        cluster_groups: dict[str, dict[str, Any]] = {}
        for node in nodes:
            cluster_id = node.cluster_id or node.kind
            group = cluster_groups.setdefault(
                cluster_id,
                {"cluster_id": cluster_id, "cluster_label": node.cluster_label or cluster_id.title(), "count": 0},
            )
            group["count"] += 1

        return GraphResponse(
            graph_id=f"graph_{mode}_{session_id}",
            mode=mode,  # type: ignore[arg-type]
            nodes=nodes,
            edges=edges,
            clusters=list(cluster_groups.values()),
            overlays={
                "active_entity_id": focus_entity_id,
                "pending_action_ids": [row["id"] for row in plan_rows],
                "items": [overlay.model_dump() for overlay in overlays],
            },
        )

    def graph_node(self, node_id: str) -> InspectorPayload:
        row = self.db.query_one("SELECT * FROM entities WHERE id = ?", (node_id,))
        if row is None:
            raise KeyError(node_id)
        node = self._row_to_node(row)
        edge_rows = self.db.query_all(
            "SELECT * FROM graph_edges WHERE source = ? OR target = ? ORDER BY weight DESC LIMIT 12",
            (node_id, node_id),
        )
        related_ids = {node_id}
        for edge_row in edge_rows:
            related_ids.add(edge_row["source"])
            related_ids.add(edge_row["target"])
        related_rows = self.db.query_all(
            "SELECT * FROM entities WHERE id IN ({})".format(",".join(["?"] * len(related_ids))),
            tuple(related_ids),
        )
        evidence = [
            {
                "id": result.id,
                "title": result.title,
                "text": result.text,
                "source_id": result.source_id,
                "score": round(result.score, 3),
            }
            for result in self.search_evidence(node.label, limit=5, entity_ids=[node_id])
        ]
        draft_rows = self.db.query_all(
            "SELECT * FROM draft_artifacts ORDER BY updated_at DESC LIMIT 5"
        )
        action_rows = self.db.query_all(
            "SELECT * FROM action_plans WHERE status IN ('pending-approval', 'ready', 'executed') ORDER BY created_at DESC LIMIT 5"
        )
        citations = [
            {"id": item["id"], "label": item["title"], "kind": "evidence", "source_id": item["source_id"]}
            for item in evidence
        ]
        return InspectorPayload(
            node=node,
            summary=node.summary,
            evidence=evidence,
            related_nodes=[self._row_to_node(related_row) for related_row in related_rows if related_row["id"] != node_id],
            related_edges=[self._row_to_edge(edge_row) for edge_row in edge_rows],
            actions=[self._plan_to_pending_action(row) for row in action_rows],
            drafts=[
                {
                    "id": row["id"],
                    "title": row["title"],
                    "summary": row["summary"],
                    "status": row["status"],
                }
                for row in draft_rows
            ],
            rules=[
                {"id": row["id"], "text": row["text"]}
                for row in self.db.query_all("SELECT * FROM profile_memories WHERE kind = 'procedural' ORDER BY confidence DESC LIMIT 5")
            ],
            citations=citations,
            history=[
                {"id": row["id"], "time": row["created_at"], "text": row["content"]}
                for row in self.db.query_all(
                    "SELECT * FROM messages ORDER BY created_at DESC LIMIT 6"
                )
            ],
        )

    def graph_expand(
        self,
        node_ids: list[str],
        depth: int,
        include_kinds: list[str],
        mode: str,
    ) -> GraphResponse:
        del depth, include_kinds
        focus = node_ids[0] if node_ids else None
        return self.graph_root(mode, "sess_demo", focus_entity_id=focus, limit=18)

    def graph_path(self, from_id: str, to_id: str) -> dict[str, Any]:
        direct = self.db.query_one(
            "SELECT * FROM graph_edges WHERE source = ? AND target = ?",
            (from_id, to_id),
        )
        reverse = self.db.query_one(
            "SELECT * FROM graph_edges WHERE source = ? AND target = ?",
            (to_id, from_id),
        )
        path = []
        if direct:
            path = [direct["source"], direct["target"]]
        elif reverse:
            path = [reverse["target"], reverse["source"]]
        else:
            via = self.db.query_one(
                """
                SELECT first.target AS via
                FROM graph_edges AS first
                JOIN graph_edges AS second ON second.source = first.target
                WHERE first.source = ? AND second.target = ?
                LIMIT 1
                """,
                (from_id, to_id),
            )
            if via:
                path = [from_id, via["via"], to_id]
        return {"from_id": from_id, "to_id": to_id, "path": path}

    def timeline_overlay(self) -> list[TimelineItem]:
        rows = self.db.query_all(
            "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 8"
        )
        return [
            TimelineItem(
                time=row["created_at"][11:16] if len(row["created_at"]) >= 16 else row["created_at"],
                text=f"{row['event_type'].replace('_', ' ')} · {row['subject_id']}",
            )
            for row in rows
        ]

    def open_loops(self) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT graph_edges.*, source_entity.display_name AS source_label, target_entity.display_name AS target_label
            FROM graph_edges
            JOIN entities AS source_entity ON source_entity.id = graph_edges.source
            JOIN entities AS target_entity ON target_entity.id = graph_edges.target
            WHERE graph_edges.kind IN ('waiting_on', 'promised')
            ORDER BY graph_edges.weight DESC, graph_edges.last_updated_at DESC
            LIMIT 10
            """
        )
        return [
            {
                "id": row["id"],
                "kind": row["kind"],
                "source": row["source_label"],
                "target": row["target_label"],
                "weight": row["weight"],
            }
            for row in rows
        ]

    def snapshot(self, session_id: str) -> SessionSnapshot:
        session = self.db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
        if session is None:
            raise KeyError(session_id)

        queue_rows = self.db.query_all(
            """
            SELECT * FROM entities
            WHERE json_extract(metadata_json, '$.queue') = 1
            ORDER BY confidence DESC, last_seen_at DESC
            LIMIT 8
            """
        )
        queue = []
        for row in queue_rows:
            metadata = self.db.json_loads(row["metadata_json"], {})
            queue.append(
                QueueItem(
                    id=row["id"],
                    kind=metadata.get("queue_kind", row["entity_type"]),
                    time=metadata.get("time", "Now"),
                    title=metadata.get("queue_title", row["display_name"]),
                    summary=metadata.get("queue_summary", row["summary"]),
                    tags=metadata.get("tags", []),
                    prompt=metadata.get("prompt", f"Tell me about {row['display_name']}"),
                    entity_id=row["id"],
                    context=metadata.get("context", {}),
                )
            )

        timeline_rows = self.db.query_all(
            "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 6"
        )
        timeline = [
            TimelineItem(
                time=row["created_at"][11:16] if len(row["created_at"]) >= 16 else row["created_at"],
                text=self.db.json_loads(row["payload_json"], {}).get("summary", row["event_type"].replace("_", " ")),
            )
            for row in timeline_rows
        ]
        message_rows = self.db.query_all(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC LIMIT 20",
            (session_id,),
        )
        chat_messages = [
            ChatMessage(
                id=row["id"],
                role=row["role"],
                label="Palora" if row["role"] == "assistant" else "You",
                body=row["content"],
                created_at=row["created_at"],
                tool=self.db.json_loads(row["structured_json"], {}).get("tool") if row["structured_json"] else None,
            )
            for row in message_rows
        ]
        draft_rows = self.db.query_all(
            "SELECT * FROM draft_artifacts WHERE session_id = ? ORDER BY updated_at DESC",
            (session_id,),
        )
        drafts = [
            DraftItem(
                id=row["id"],
                kind=row["kind"],
                title=row["title"],
                summary=row["summary"],
                body=row["body"],
                status=row["status"],
                tags=self.db.json_loads(row["citations_json"], []),
                citations=self.db.json_loads(row["citations_json"], []),
            )
            for row in draft_rows
        ]
        action_rows = self.db.query_all(
            "SELECT * FROM action_plans WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        )
        graph = self.graph_root("macro", session_id, session["active_entity_id"], limit=18)
        open_loops = self.open_loops()
        return SessionSnapshot(
            session_id=session_id,
            active_focus_id=session["active_entity_id"] or "ent_recruiter_x",
            queue=queue,
            timeline=timeline,
            chat_messages=chat_messages,
            drafts=drafts,
            actions=[self._plan_to_pending_action(row) for row in action_rows],
            stats={
                "open_loops": len(open_loops),
                "pending_approvals": sum(1 for row in action_rows if row["status"] == "pending-approval"),
                "drafts": len(drafts),
                "next_deadline": queue[0].time if queue else "Later",
            },
            graph=graph,
        )

    def _plan_to_pending_action(self, row: sqlite3.Row) -> PendingAction:
        return PendingAction(
            id=row["id"],
            tool_name=row["tool_name"],
            intent=row["intent"],
            risk_class=int(row["risk_class"]),
            status=row["status"],
            reason=row["reason"],
            prepared_hash=row["prepared_hash"],
            prepared_args=self.db.json_loads(row["prepared_args_json"], {}),
            requires_approval=row["status"] == "pending-approval",
            expires_at=datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")) if row["expires_at"] else None,
        )


class IngestService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def _split_chunks(self, text: str, chunk_size: int = 800) -> list[str]:
        normalized = text.replace("\r\n", "\n").strip()
        if len(normalized) <= chunk_size:
            return [normalized]
        chunks = []
        start = 0
        while start < len(normalized):
            end = min(len(normalized), start + chunk_size)
            chunk = normalized[start:end]
            if end < len(normalized):
                split = chunk.rfind("\n")
                if split > chunk_size // 3:
                    end = start + split
                    chunk = normalized[start:end]
            chunks.append(chunk.strip())
            start = end
        return [chunk for chunk in chunks if chunk]

    def _extract_aliases(self, title: str, text: str) -> list[tuple[str, str, list[str], str]]:
        candidates = [
            ("ent_recruiter_x", "Recruiter X", ["recruiter", "company y recruiter"], "person"),
            ("org_company_y", "Company Y", ["company y"], "organization"),
            ("ent_priya_m", "Priya M.", ["priya"], "person"),
            ("proj_palora", "Palora Build", ["palora", "build"], "project"),
        ]
        lowered = f"{title}\n{text}".lower()
        matches = []
        for entity_id, display_name, aliases, kind in candidates:
            if display_name.lower() in lowered or any(alias.lower() in lowered for alias in aliases):
                matches.append((entity_id, display_name, aliases, kind))
        return matches

    def _extract_facts(self, source_event_id: str, text: str) -> list[tuple[str, str, str, str, float, list[str]]]:
        lowered = text.lower()
        facts: list[tuple[str, str, str, str, float, list[str]]] = []
        if "follow up" in lowered or "follow-up" in lowered:
            facts.append(("edge_waiting_recruiter", "waiting_on", "ent_user", "ent_recruiter_x", 0.9, [source_event_id]))
        if "priya" in lowered and "spec" in lowered:
            facts.append(("edge_priya_palora", "works_with", "ent_priya_m", "proj_palora", 0.85, [source_event_id]))
        return facts

    def ingest_source(self, request: IngestSourceRequest) -> IngestJobResponse:
        checksum = hashlib.sha256(request.text.encode("utf-8")).hexdigest()
        existing = self.db.query_one("SELECT id FROM source_events WHERE checksum = ?", (checksum,))
        if existing:
            return IngestJobResponse(
                job_id=self.db.make_id("job"),
                status="deduped",
                source_event_id=existing["id"],
                chunks_written=0,
                entities_written=0,
                facts_written=0,
            )

        source_event_id = self.db.make_id("src")
        raw_path = self.settings.blob_dir / "sources" / f"{source_event_id}.txt"
        raw_path.write_text(request.text, encoding="utf-8")
        timestamp = isoformat(request.timestamp or utcnow()) or isoformat(utcnow())
        self.db.execute(
            """
            INSERT INTO source_events (
              id, source_type, source_ref, timestamp, title, text_path, raw_text, metadata_json, checksum, ingest_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'indexed')
            """,
            (
                source_event_id,
                request.source_type,
                request.source_ref,
                timestamp,
                request.title,
                str(raw_path),
                request.text,
                self.db.json_dumps(request.metadata),
                checksum,
            ),
        )
        chunks = self._split_chunks(request.text)
        params = []
        for index, chunk in enumerate(chunks):
            params.append(
                (
                    self.db.make_id("chk"),
                    source_event_id,
                    index,
                    chunk,
                    hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                    None,
                    isoformat(utcnow()),
                )
            )
        if params:
            self.db.executemany(
                """
                INSERT INTO source_chunks (
                  id, source_event_id, chunk_index, text, checksum, mempalace_drawer_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )

        entities_written = 0
        for entity_id, display_name, aliases, kind in self._extract_aliases(request.title, request.text):
            self.db.upsert_entity(
                entity_id=entity_id,
                display_name=display_name,
                entity_type=kind,
                summary=f"Derived from {request.title}",
                aliases=aliases,
                metadata={"derived_from": source_event_id},
                cluster_id="cluster_build" if kind == "project" else "cluster_people",
                confidence=0.84,
            )
            entities_written += 1

        facts_written = 0
        for edge_id, kind, source, target, weight, evidence_ids in self._extract_facts(source_event_id, request.text):
            self.db.upsert_edge(
                edge_id=edge_id,
                kind=kind,
                source=source,
                target=target,
                weight=weight,
                evidence_ids=evidence_ids,
                metadata={"source_event_id": source_event_id},
            )
            facts_written += 1

        return IngestJobResponse(
            job_id=self.db.make_id("job"),
            status="indexed",
            source_event_id=source_event_id,
            chunks_written=len(chunks),
            entities_written=entities_written,
            facts_written=facts_written,
        )


class ActionService:
    def __init__(self, db: Database, writer: WritebackService) -> None:
        self.db = db
        self.writer = writer
        self.adapters = {
            "mail.create_draft": MailDraftAdapter(),
            "calendar.create_event": CalendarEventAdapter(),
            "reminders.create": RemindersAdapter(),
            "browser.read": BrowserManagedAdapter(),
        }

    def list_actions(self, session_id: str) -> list[PendingAction]:
        rows = self.db.query_all(
            "SELECT * FROM action_plans WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        )
        memory = MemoryService(self.db)
        return [memory._plan_to_pending_action(row) for row in rows]

    async def approve(self, action_id: str, prepared_hash: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM action_plans WHERE id = ?", (action_id,))
        if row is None:
            raise KeyError(action_id)
        if row["prepared_hash"] != prepared_hash:
            raise ValueError("prepared hash mismatch")
        adapter = self.adapters[row["tool_name"]]
        args = self.db.json_loads(row["prepared_args_json"], {})
        await adapter.validate(args)
        result = await adapter.execute(args)
        self.db.execute(
            "UPDATE action_plans SET status = 'executed' WHERE id = ?",
            (action_id,),
        )
        self.writer.record_action_run(action_id, adapter.name, args, result)
        self.db.execute(
            """
            INSERT INTO action_approvals (id, action_plan_id, decision, decided_at, decider, notes)
            VALUES (?, ?, 'approved', ?, 'user', ?)
            """,
            (self.db.make_id("approval"), action_id, isoformat(utcnow()), "Approved in desktop UI"),
        )
        return result

    def reject(self, action_id: str) -> None:
        self.db.execute(
            "UPDATE action_plans SET status = 'rejected' WHERE id = ?",
            (action_id,),
        )
        self.db.execute(
            """
            INSERT INTO action_approvals (id, action_plan_id, decision, decided_at, decider, notes)
            VALUES (?, ?, 'rejected', ?, 'user', ?)
            """,
            (self.db.make_id("approval"), action_id, isoformat(utcnow()), "Rejected in desktop UI"),
        )


class AppServices:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.db_path)
        self.db.init()
        self.memory = MemoryService(self.db)
        self.ingest = IngestService(self.db, settings)
        self.policy = PolicyEngine()
        self.writer = WritebackService(self.db)
        self.actions = ActionService(self.db, self.writer)
        self.seed_demo_data()

    def seed_demo_data(self) -> None:
        seed_version = "v3"
        if self.db.get_meta("seed_version") == seed_version:
            return

        self.db.execute("DELETE FROM action_runs")
        self.db.execute("DELETE FROM action_approvals")
        self.db.execute("DELETE FROM action_plans")
        self.db.execute("DELETE FROM graph_edges")
        self.db.execute("DELETE FROM draft_artifacts")
        self.db.execute("DELETE FROM style_profiles")
        self.db.execute("DELETE FROM profile_memories")
        self.db.execute("DELETE FROM source_chunks")
        self.db.execute("DELETE FROM source_events")
        self.db.execute("DELETE FROM messages")
        self.db.execute("DELETE FROM sessions")
        self.db.execute("DELETE FROM entities")
        self.db.execute("DELETE FROM audit_events")

        created = isoformat(utcnow()) or ""
        self.db.execute(
            """
            INSERT INTO sessions (id, title, created_at, updated_at, active_entity_id, status)
            VALUES ('sess_demo', 'Palora Demo', ?, ?, 'ent_recruiter_x', 'active')
            """,
            (created, created),
        )

        self.db.upsert_entity(
            "ent_user",
            "You",
            "person",
            "Primary operator inside Palora.",
            aliases=["avi", "me", "user"],
            metadata={"cluster_label": "Career", "cluster_kind": "people"},
            cluster_id="cluster_people",
            confidence=1.0,
        )
        self.db.upsert_entity(
            "ent_recruiter_x",
            "Recruiter X",
            "person",
            "Recruiter for Company Y role. Active follow-up loop.",
            aliases=["recruiter", "company y recruiter"],
            metadata={
                "queue": 1,
                "queue_kind": "follow-up",
                "queue_title": "Send Recruiter X follow-up",
                "queue_summary": "Draft ready. Best unblock right now. Last reply was 3 days ago.",
                "time": "Today",
                "tags": ["career", "waiting on", "draft ready"],
                "prompt": "Draft follow-up to Recruiter X in my tone and ask me before sending.",
                "context": {
                    "eyebrow": "Senior engineering role at Company Y",
                    "name": "Recruiter X",
                    "summary": "Two-thread relationship. Positive tone so far. Best move is gentle follow-up today while timing still warm.",
                    "stats": [{"v": "2", "l": "open threads"}, {"v": "3d", "l": "since reply"}, {"v": "91%", "l": "confidence"}],
                    "tags": ["Warm-formal", "Never auto-send", "Approval required"],
                    "actions": ["Open full chat for draft", "Open recall graph", "Create reminder"],
                },
                "cluster_label": "Career",
                "cluster_kind": "people",
            },
            cluster_id="cluster_people",
            confidence=0.93,
        )
        self.db.upsert_entity(
            "org_company_y",
            "Company Y",
            "organization",
            "Target company behind active recruiter loop.",
            aliases=["company y"],
            metadata={"cluster_label": "Career", "cluster_kind": "organization"},
            cluster_id="cluster_people",
            confidence=0.9,
        )
        self.db.upsert_entity(
            "task_followup",
            "Send Follow-up",
            "task",
            "Open loop for recruiter email.",
            aliases=["follow-up"],
            metadata={"cluster_label": "Career", "cluster_kind": "task"},
            cluster_id="cluster_people",
            confidence=0.88,
        )
        self.db.upsert_entity(
            "proj_palora",
            "Palora Build",
            "project",
            "Core build project spanning backend orchestration and desktop UI.",
            aliases=["palora", "palora build"],
            metadata={
                "queue": 1,
                "queue_kind": "review",
                "queue_title": "Review Priya backend spec",
                "queue_summary": "Palora backend architecture v1 shared yesterday. Need comments before sync.",
                "time": "4:00 PM",
                "tags": ["build", "teammate", "today"],
                "prompt": "Summarize Priya backend spec in 5 bullets and draft my review comments.",
                "context": {
                    "eyebrow": "Teammate on Palora build",
                    "name": "Priya M.",
                    "summary": "Strong collaborator. Shared backend spec yesterday. Best move is fast synthesis before meeting window closes.",
                    "stats": [{"v": "8", "l": "new chunks"}, {"v": "1", "l": "doc pending"}, {"v": "87%", "l": "confidence"}],
                    "tags": ["Thursday sync", "Backend scaffold", "Spec pending"],
                    "actions": ["Open full chat for summary", "Search memory", "Draft review"],
                },
                "cluster_label": "Build",
                "cluster_kind": "project",
            },
            cluster_id="cluster_build",
            confidence=0.95,
        )
        self.db.upsert_entity(
            "ent_priya_m",
            "Priya M.",
            "person",
            "Teammate driving backend architecture work.",
            aliases=["priya"],
            metadata={"cluster_label": "Build", "cluster_kind": "people"},
            cluster_id="cluster_build",
            confidence=0.9,
        )
        self.db.upsert_entity(
            "rule_never_autosend",
            "Never auto-send",
            "memory_rule",
            "Assistant drafts and stages. Human approves before anything leaves machine.",
            aliases=["rule", "approval rule"],
            metadata={"cluster_label": "Build", "cluster_kind": "rule"},
            cluster_id="cluster_build",
            confidence=1.0,
        )
        self.db.upsert_entity(
            "draft_intro",
            "Intro Email Draft",
            "draft",
            "Reusable networking draft that needs one more polish pass.",
            aliases=["intro draft"],
            metadata={
                "queue": 1,
                "queue_kind": "approval",
                "queue_title": "Approve intro draft",
                "queue_summary": "Intro template for new engineering contacts. Tone already matched from past examples.",
                "time": "Whenever",
                "tags": ["draft", "approval", "networking"],
                "prompt": "Show intro draft and highlight anything too formal or too long.",
                "context": {
                    "eyebrow": "Reusable networking draft",
                    "name": "Intro Email Draft",
                    "summary": "Draft nearly ready. Main question is whether opener feels sharp enough and ask feels concrete.",
                    "stats": [{"v": "1", "l": "draft"}, {"v": "14w", "l": "avg sentence"}, {"v": "76%", "l": "match score"}],
                    "tags": ["Reusable pattern", "Warm but concise", "Pending approval"],
                    "actions": ["Open full chat for rewrite", "Move to review mode", "Send to act lane"],
                },
                "cluster_label": "Career",
                "cluster_kind": "draft",
            },
            cluster_id="cluster_people",
            confidence=0.76,
        )

        repo_spec = self.settings.repo_root / "project_spec.md"
        prototype = self.settings.repo_root / "prototypes" / "palora_chat_first_preview.html"
        spec_text = repo_spec.read_text(encoding="utf-8")
        prototype_text = prototype.read_text(encoding="utf-8")
        recruiter_thread = (
            "Apr 20 outbound: Thanks again for the conversation. I am excited about the role.\n"
            "Apr 21 inbound from Recruiter X: Team is reviewing, should have update early next week.\n"
            "Apr 23 note: No reply yet. Good timing for polite follow-up."
        )
        priya_note = (
            "Priya shared backend architecture draft for Palora. Need comments before 4 PM sync. "
            "Focus on orchestrator, graph serving layer, approvals, and managed browser profile."
        )

        spec_ingest = self.ingest.ingest_source(
            IngestSourceRequest(
                source_type="document",
                source_ref="project_spec.md",
                title="Palora Backend + Agentic Layer Spec",
                text=spec_text,
                metadata={"kind": "repo_spec"},
            )
        )
        preview_ingest = self.ingest.ingest_source(
            IngestSourceRequest(
                source_type="prototype",
                source_ref="prototypes/palora_chat_first_preview.html",
                title="Palora Chat First Preview",
                text=prototype_text,
                metadata={"kind": "repo_preview"},
            )
        )
        recruiter_ingest = self.ingest.ingest_source(
            IngestSourceRequest(
                source_type="email_thread",
                source_ref="gmail_thread_recruiter",
                title="Recruiter Follow-up",
                text=recruiter_thread,
                metadata={"participants": ["Recruiter X"], "direction": "mixed"},
            )
        )
        priya_ingest = self.ingest.ingest_source(
            IngestSourceRequest(
                source_type="note",
                source_ref="priya_note",
                title="Priya backend review",
                text=priya_note,
                metadata={"participants": ["Priya M."]},
            )
        )

        self.db.upsert_edge("edge_user_recruiter", "waiting_on", "ent_user", "ent_recruiter_x", 0.88, [recruiter_ingest.source_event_id])
        self.db.upsert_edge("edge_recruiter_company", "recruiter_for", "ent_recruiter_x", "org_company_y", 0.82, [recruiter_ingest.source_event_id])
        self.db.upsert_edge("edge_task_recruiter", "mentions", "task_followup", "ent_recruiter_x", 0.74, [recruiter_ingest.source_event_id])
        self.db.upsert_edge("edge_user_palora", "related_to", "ent_user", "proj_palora", 0.92, [spec_ingest.source_event_id])
        self.db.upsert_edge("edge_priya_palora", "works_with", "ent_priya_m", "proj_palora", 0.86, [priya_ingest.source_event_id])
        self.db.upsert_edge("edge_rule_user", "used_in", "rule_never_autosend", "ent_user", 0.83, [spec_ingest.source_event_id])
        self.db.upsert_edge("edge_draft_recruiter", "derived_from", "draft_intro", "ent_recruiter_x", 0.63, [recruiter_ingest.source_event_id])

        self.db.executemany(
            """
            INSERT INTO profile_memories (
              id, kind, text, scope, entity_id, approved, confidence, source_event_ids_json, last_used_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "pm_style_general",
                    "style",
                    "Warm-formal tone. Clear asks. Short paragraphs. Avoid over-selling.",
                    "user",
                    "ent_user",
                    1,
                    0.92,
                    self.db.json_dumps([recruiter_ingest.source_event_id]),
                    created,
                ),
                (
                    "pm_proc_approval",
                    "procedural",
                    "Never auto-send external mail. Stage draft first and ask before any side effect.",
                    "global",
                    "ent_user",
                    1,
                    0.99,
                    self.db.json_dumps([spec_ingest.source_event_id]),
                    created,
                ),
                (
                    "pm_profile_focus",
                    "profile",
                    "Career follow-ups should feel warm, direct, and not needy.",
                    "career",
                    "ent_user",
                    1,
                    0.9,
                    self.db.json_dumps([recruiter_ingest.source_event_id]),
                    created,
                ),
            ],
        )

        self.db.execute(
            """
            INSERT INTO style_profiles (
              id, user_or_entity_scope, avg_sentence_length, greeting_patterns_json,
              signoff_patterns_json, verbosity, formality, notes_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "style_user",
                "ent_user",
                14.0,
                self.db.json_dumps(["Hope your week is going smoothly.", "Thanks again for the update."]),
                self.db.json_dumps(["Best,", "Thanks,"]),
                "concise",
                "warm-formal",
                self.db.json_dumps({"learned_from": ["Recruiter Follow-up", "Priya backend review", "Palora Chat First Preview"]}),
                created,
            ),
        )

        self.db.create_draft(
            "sess_demo",
            "ready now",
            "RE: Senior Engineering Role",
            "Warm-formal follow-up to Recruiter X. Balanced interest and timeline ask.",
            "Hope your week is going smoothly.\n\nI wanted to follow up on the Senior Engineering Role. I'm still very interested and would love any update on timing or next steps.\n\nBest,\nAvi",
            "needs approval",
            [recruiter_ingest.source_event_id],
        )
        self.db.create_draft(
            "sess_demo",
            "needs polish",
            "Intro Email Template",
            "Reusable intro for engineering contacts. Good skeleton, opener still broad.",
            "Hi there,\n\nWanted to reach out and introduce myself...\n\nBest,\nAvi",
            "draft",
            [recruiter_ingest.source_event_id],
        )

        reminder_plan = self.db.create_action_plan(
            session_id="sess_demo",
            tool_name="reminders.create",
            intent="propose_action",
            risk_class=2,
            prepared_args={
                "title": "Check Priya review by 4:00 PM",
                "due_at": "2026-04-23T15:15:00Z",
                "notes": "If no review started by 3:15 PM, resurface and prep summary.",
                "entity_id": "proj_palora",
            },
            memory_refs=[spec_ingest.source_event_id, priya_ingest.source_event_id],
            reason="Keep build sync from slipping.",
            status="pending-approval",
            expires_at=utcnow() + timedelta(hours=4),
        )
        self.db.create_action_plan(
            session_id="sess_demo",
            tool_name="mail.create_draft",
            intent="draft_text",
            risk_class=1,
            prepared_args={
                "to": ["recruiter@example.com"],
                "subject": "Following up on Company Y role",
                "body": "Hope your week is going smoothly...",
                "entity_id": "ent_recruiter_x",
            },
            memory_refs=[recruiter_ingest.source_event_id],
            reason="Warm recruiter loop still active.",
            status="ready",
            expires_at=utcnow() + timedelta(hours=2),
        )

        self.db.create_message(
            "sess_demo",
            "assistant",
            "Morning sweep complete. Biggest unblock is Recruiter X. Draft already exists and timing window is still warm.",
            {"tool": None},
        )
        self.db.create_message(
            "sess_demo",
            "user",
            "Can you tighten the opener and show me what changed?",
            None,
        )
        self.db.create_message(
            "sess_demo",
            "assistant",
            "Yes. I'd shorten the first line, keep interest explicit, and move the timeline ask to sentence two.",
            {
                "tool": {
                    "title": "Prepared next step",
                    "summary": "Open draft in review mode with one proposed revision and approval gate preserved.",
                    "actions": ["Open draft review", "Open recall", "Set reminder instead"],
                }
            },
        )

        self.writer.record_turn(
            trace_id="seed_01",
            event_type="draft_created",
            subject_id="ent_recruiter_x",
            payload={"summary": "Draft created for Recruiter X follow-up."},
        )
        self.writer.record_turn(
            trace_id="seed_02",
            event_type="source_ingested",
            subject_id="proj_palora",
            payload={"summary": f"Priya backend spec indexed from {repo_spec.name}."},
        )
        self.writer.record_turn(
            trace_id="seed_03",
            event_type="action_pending",
            subject_id=reminder_plan["id"],
            payload={"summary": "Reminder approval waiting for Priya review fallback."},
        )

        self.db.set_meta("seed_version", seed_version)
