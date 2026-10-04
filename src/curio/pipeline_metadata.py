"""Final persistence boundary for completed generation metadata."""

from __future__ import annotations

import time


def persist_run_metadata(metadata: dict, metadata_path: str, metrics,
                         stage_times: dict, metrics_dir: str, write_json,
                         finalize_started: float, run_started: float) -> dict:
    """Persist one consistent project/metrics view after output artifacts exist.

    The finalization duration covers metadata/report assembly before this
    boundary. Metrics and project metadata share the same stage-time snapshot;
    the project file also records the generated metrics path.
    """
    stage_times["finalize"] = round(max(0.0, time.monotonic() - finalize_started), 2)
    metadata["processing_time_seconds"] = round(
        max(0.0, time.monotonic() - run_started), 2)
    metadata["stage_times"] = dict(stage_times)
    metadata["metrics_file"] = metrics.save(metadata, stage_times, metrics_dir)
    write_json(metadata_path, metadata)
    return metadata
