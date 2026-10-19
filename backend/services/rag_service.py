"""Semantic retrieval over curated source-to-Python migration rules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = PROJECT_ROOT / "backend" / "data" / "migration_rules.json"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class RAGMigrationEngine:
    def __init__(self, persist_directory: str | Path | None = None) -> None:
        # Chroma 0.4's default Client is in-memory. Supply a path to persist between runs.
        self.client = (
            chromadb.PersistentClient(path=str(persist_directory))
            if persist_directory
            else chromadb.Client()
        )
        self.collection = self.client.get_or_create_collection(
            name="migration_rules",
            metadata={"hnsw:space": "cosine"},
        )
        self.embedding_model = SentenceTransformer(EMBEDDING_MODEL)

    @property
    def collection_name(self) -> str:
        return self.collection.name

    def seed_rules_if_empty(self) -> int:
        """Seed the collection once and return its resulting rule count."""
        if self.collection.count() > 0:
            return self.collection.count()
        with RULES_PATH.open("r", encoding="utf-8") as rules_file:
            rules: list[dict[str, Any]] = json.load(rules_file)
        if not rules:
            return 0

        documents = [
            " ".join(
                [
                    rule["description"],
                    f"Construct: {rule['construct_type']}.",
                    f"Source: {rule['source_pattern']}.",
                    f"Target: {rule['target_pattern']}.",
                ]
            )
            for rule in rules
        ]
        embeddings = self.embedding_model.encode(documents, convert_to_numpy=True).tolist()
        self.collection.add(
            ids=[rule["rule_id"] for rule in rules],
            documents=documents,
            embeddings=embeddings,
            metadatas=[
                {
                    "rule_id": rule["rule_id"],
                    "source_lang": rule["source_lang"],
                    "target_lang": rule["target_lang"],
                    "construct_type": rule["construct_type"],
                    "description": rule["description"],
                    "source_pattern": rule["source_pattern"],
                    "target_pattern": rule["target_pattern"],
                }
                for rule in rules
            ],
        )
        return self.collection.count()

    def retrieve_migration_rules(
        self,
        ast_context_summary: str,
        source_lang: str,
        target_lang: str,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        if top_k <= 0 or not ast_context_summary.strip():
            return []
        available = self.collection.count()
        if available == 0:
            return []
        query_embedding = self.embedding_model.encode(
            [ast_context_summary], convert_to_numpy=True
        ).tolist()
        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=min(top_k, available),
            where={"$and": [
                {"source_lang": {"$eq": source_lang}},
                {"target_lang": {"$eq": target_lang}},
            ]},
            include=["documents", "metadatas", "distances"],
        )
        matches: list[dict[str, Any]] = []
        for metadata, distance in zip(
            results["metadatas"][0], results["distances"][0]
        ):
            matches.append(
                {
                    **metadata,
                    "distance": distance,
                }
            )
        return matches
