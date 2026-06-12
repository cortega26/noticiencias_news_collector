"""ValidationCoordinator — orchestrates the validation phase of the pipeline.

Extracted from NewsCollectorSystem._execute_validation to give the validation
phase its own class with explicit dependencies.
"""

from __future__ import annotations

from typing import Any, Dict, List


class ValidationCoordinator:
    """Owns the batch validation loop.

    Dependencies (all injected):
        db_manager  – persistence layer (get_pending_articles, update_validation_status_bulk)
        validator   – validation engine (validate_batch)
        logger      – logging facade (create_module_logger)
    """

    def __init__(self, db_manager: Any, validator: Any, logger: Any) -> None:
        self.db_manager = db_manager
        self.validator = validator
        self.logger = logger

    # ------------------------------------------------------------------
    # Batch constants
    # ------------------------------------------------------------------
    BATCH_SIZE = 100
    MAX_BATCHES = 10_000

    def execute(  # noqa: C901
        self, collection_results: Dict[str, Any], dry_run: bool
    ) -> Dict[str, Any]:
        """Run the validation phase — same logic as the extracted method."""
        if dry_run:
            return {"success": True, "validated_count": 0, "rejected_count": 0}

        total_validated = 0
        total_rejected = 0
        batch_count = 0
        run_failed = False
        validation_results: Dict[str, List[Any]] = {"invalid": [], "valid": []}

        while True:
            if batch_count >= self.MAX_BATCHES:
                self.logger.create_module_logger("validation").error(
                    f"Validation halted: Max batches ({self.MAX_BATCHES}) reached. "
                    "Possible infinite loop."
                )
                break

            pending_articles = self.db_manager.get_pending_articles(
                limit=self.BATCH_SIZE
            )
            if not pending_articles:
                break

            batch_count += 1

            from news_collector.contracts.adapters import adapt_to_validation_payload

            validation_payload = adapt_to_validation_payload(pending_articles)
            articles_to_validate = [
                item.model_dump() for item in validation_payload.articles
            ]

            batch_results = self.validator.validate_batch(articles_to_validate)

            invalid_mappings: List[Dict[str, Any]] = []
            batch_rejected = 0
            if batch_results["invalid"]:
                for invalid_item in batch_results["invalid"]:
                    batch_rejected += 1
                    article_data = invalid_item["article"]
                    reason = invalid_item["reason"]
                    rule_name = invalid_item["rule"]
                    article_id = article_data["id"]
                    invalid_mappings.append(
                        {
                            "id": article_id,
                            "processing_status": "rejected",
                            "error_message": (
                                f"Validation failed: {rule_name} - {reason}"
                            ),
                        }
                    )
                validation_results["invalid"].extend(batch_results["invalid"])

            valid_mappings: List[Dict[str, Any]] = []
            if batch_results.get("valid"):
                if "valid" not in validation_results:
                    validation_results["valid"] = []
                validation_results["valid"].extend(batch_results.get("valid", []))
                for valid_item in batch_results.get("valid", []):
                    article_id = valid_item.get("id")
                    if article_id:
                        valid_mappings.append(
                            {"id": article_id, "processing_status": "validated"}
                        )

            all_mappings = invalid_mappings + valid_mappings
            if all_mappings:
                persisted = self.db_manager.update_validation_status_bulk(all_mappings)
                if persisted is False:
                    run_failed = True
                    self.logger.create_module_logger("validation").error(
                        {
                            "event": "validation.persist_failed",
                            "batch": batch_count,
                            "mappings": len(all_mappings),
                        }
                    )
                    break

            total_validated += len(pending_articles)
            total_rejected += batch_rejected

        self.logger.create_module_logger("validation").info(
            {
                "event": "validation.completed",
                "total": total_validated,
                "rejected": total_rejected,
                "valid": total_validated - total_rejected,
                "batches": batch_count,
            }
        )

        return {
            "success": not run_failed,
            "validated_count": total_validated,
            "rejected_count": total_rejected,
            "details": validation_results,
        }
