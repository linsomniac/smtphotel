"""Background tasks for smtphotel.

AIDEV-NOTE: This module contains async background tasks that run
throughout the application lifecycle.
"""

from smtphotel.tasks.pruning import PruneTask, start_prune_task, stop_prune_task

__all__ = ["PruneTask", "start_prune_task", "stop_prune_task"]
