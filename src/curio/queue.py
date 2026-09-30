"""Fila de processamento de vídeos (§Queue).

Permite processar múltiplas ideias de vídeos sequencialmente,
cada uma gerando seu projeto independente com pipeline completo.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from .config import CurioConfig
from .pipeline import MediaStandby, run_pipeline
from .slug import slugify


class QueueItemStatus(str, Enum):
    WAITING = "waiting"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"
    PAUSED = "paused"
    CANCELLED = "cancelled"


@dataclass
class QueueItem:
    """Um item na fila de processamento."""
    idea: str
    status: QueueItemStatus = QueueItemStatus.WAITING
    slug: str = ""
    project_dir: str = ""
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    video_path: str = ""
    metadata_path: str = ""
    retry_count: int = 0
    config_overrides: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.slug:
            self.slug = slugify(self.idea[:60]) or f"video-{int(time.time())}"


@dataclass
class VideoQueue:
    """Fila de vídeos para processamento sequencial."""
    items: list[QueueItem] = field(default_factory=list)
    current_index: int = -1
    paused: bool = False
    cancelled: bool = False
    queue_file: str = ""

    def add(self, idea: str, config_overrides: dict | None = None) -> QueueItem:
        item = QueueItem(idea=idea, config_overrides=config_overrides or {})
        self.items.append(item)
        return item

    def add_from_list(self, ideas: list[str], config_overrides: dict | None = None) -> list[QueueItem]:
        return [self.add(idea, config_overrides) for idea in ideas if idea.strip()]

    def add_from_file(self, path: str, config_overrides: dict | None = None) -> list[QueueItem]:
        with open(path, encoding="utf-8") as f:
            ideas = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
        return self.add_from_list(ideas, config_overrides)

    def get_next_waiting(self) -> Optional[QueueItem]:
        for i, item in enumerate(self.items):
            if item.status == QueueItemStatus.WAITING:
                self.current_index = i
                return item
        return None

    def get_current(self) -> Optional[QueueItem]:
        if 0 <= self.current_index < len(self.items):
            return self.items[self.current_index]
        return None

    def progress_str(self) -> str:
        total = len(self.items)
        completed = sum(1 for i in self.items if i.status == QueueItemStatus.COMPLETED)
        processing = sum(1 for i in self.items if i.status == QueueItemStatus.PROCESSING)
        errors = sum(1 for i in self.items if i.status == QueueItemStatus.ERROR)
        waiting = sum(1 for i in self.items if i.status == QueueItemStatus.WAITING)
        return f"Fila: {completed + processing + errors} / {total} (✓{completed} ▶{processing} ✗{errors} ○{waiting})"

    def status_lines(self) -> list[str]:
        lines = [self.progress_str(), ""]
        for i, item in enumerate(self.items):
            icon = {
                QueueItemStatus.WAITING: "○",
                QueueItemStatus.PROCESSING: "▶",
                QueueItemStatus.COMPLETED: "✓",
                QueueItemStatus.ERROR: "✗",
                QueueItemStatus.PAUSED: "⏸",
                QueueItemStatus.CANCELLED: "⊘",
            }.get(item.status, "?")
            error_info = f" ({item.error[:50]}...)" if item.error else ""
            lines.append(f"{icon} {item.idea}{error_info}")
        return lines

    def print_status(self) -> None:
        for line in self.status_lines():
            print(line)

    def save(self, path: str) -> None:
        """Salva a fila. `.txt` = uma ideia por linha; `.json` = estado completo."""
        self.queue_file = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if path.lower().endswith(".txt"):
            with open(path, "w", encoding="utf-8") as f:
                for item in self.items:
                    if item.idea.strip():
                        f.write(item.idea.strip() + "\n")
            return
        data = {
            "items": [asdict(item) for item in self.items],
            "current_index": self.current_index,
            "paused": self.paused,
            "cancelled": self.cancelled,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, path: str) -> "VideoQueue":
        """Carrega `.json` (estado) ou `.txt` (uma ideia por linha)."""
        if path.lower().endswith(".txt"):
            queue = cls(queue_file=path)
            queue.add_from_file(path)
            return queue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        raw_items = data.get("items", [])
        items = []
        for raw in raw_items:
            raw = dict(raw)
            status = raw.get("status", QueueItemStatus.WAITING)
            if not isinstance(status, QueueItemStatus):
                try:
                    raw["status"] = QueueItemStatus(str(status))
                except ValueError:
                    raw["status"] = QueueItemStatus.WAITING
            items.append(QueueItem(**raw))
        queue = cls(
            items=items,
            current_index=data.get("current_index", -1),
            paused=data.get("paused", False),
            cancelled=data.get("cancelled", False),
            queue_file=path,
        )
        return queue

    def remove(self, index: int) -> bool:
        """Remove um item ainda não processado da fila."""
        if 0 <= index < len(self.items):
            if self.items[index].status in (QueueItemStatus.WAITING,
                                            QueueItemStatus.ERROR,
                                            QueueItemStatus.CANCELLED):
                del self.items[index]
                return True
        return False


def process_queue(
    queue: VideoQueue,
    cfg: CurioConfig,
    output_dir: str,
    on_item_start: Optional[Callable[[QueueItem], None]] = None,
    on_item_complete: Optional[Callable[[QueueItem, bool], None]] = None,
    on_progress: Optional[Callable[[VideoQueue], None]] = None,
) -> VideoQueue:
    """Processa a fila sequencialmente.

    Args:
        queue: Fila com itens a processar
        cfg: Configuração base do Curio
        output_dir: Diretório base para saída dos projetos
        on_item_start: Callback quando item inicia
        on_item_complete: Callback quando item termina (item, success)
        on_progress: Callback de progresso geral

    Returns:
        Fila atualizada com status dos itens
    """
    def signal_handler(signum, frame):
        queue.cancelled = True
        print("\nSinal de interrupção recebido. Finalizando item atual...")

    old_handler = signal.signal(signal.SIGINT, signal_handler)
    try:
        while not queue.cancelled:
            if queue.paused:
                time.sleep(1)
                continue

            item = queue.get_next_waiting()
            if not item:
                break  # Fila vazia ou tudo processado

            item.status = QueueItemStatus.PROCESSING
            item.started_at = datetime.now(timezone.utc).isoformat()
            start_time = time.monotonic()

            if on_item_start:
                on_item_start(item)
            if on_progress:
                on_progress(queue)

            # Cada ideia vira um projeto independente sob output_dir/<slug>.
            item_cfg = CurioConfig()
            for key, value in cfg.__dict__.items():
                setattr(item_cfg, key, value)
            for key, value in item.config_overrides.items():
                if hasattr(item_cfg, key):
                    setattr(item_cfg, key, value)
            item_cfg.out_dir = output_dir

            try:
                # Executa pipeline completo (mesmo pipeline do modo individual).
                try:
                    result = run_pipeline(item.idea, item_cfg, slug=item.slug)
                except MediaStandby as standby:
                    item.status = QueueItemStatus.PAUSED
                    item.error = (f"standby sem imagens — fotos em "
                                  f"{standby.manual_dir}")
                    item.finished_at = datetime.now(timezone.utc).isoformat()
                    item.duration_seconds = round(time.monotonic() - start_time, 2)
                    if on_item_complete:
                        on_item_complete(item, False)
                    print(f"STANDBY '{item.idea}': {standby}", file=sys.stderr)
                    if queue.queue_file:
                        queue.save(queue.queue_file)
                    if on_progress:
                        on_progress(queue)
                    continue
                artifacts = result.get("artifacts", {}) or {}
                video_path = str(artifacts.get("video", ""))
                project_root = os.path.dirname(os.path.dirname(video_path)) if video_path else os.path.join(output_dir, item.slug)
                item.project_dir = project_root
                item.video_path = video_path
                item.metadata_path = os.path.join(project_root, "metadata.json")

                item.status = QueueItemStatus.COMPLETED
                item.finished_at = datetime.now(timezone.utc).isoformat()
                item.duration_seconds = round(time.monotonic() - start_time, 2)
                
                if on_item_complete:
                    on_item_complete(item, True)
                    
            except Exception as exc:
                item.status = QueueItemStatus.ERROR
                item.error = str(exc)
                item.finished_at = datetime.now(timezone.utc).isoformat()
                item.duration_seconds = round(time.monotonic() - start_time, 2)
                
                if on_item_complete:
                    on_item_complete(item, False)
                
                print(f"ERRO no item '{item.idea}': {exc}", file=sys.stderr)

            # Salva progresso
            if queue.queue_file:
                queue.save(queue.queue_file)
            
            if on_progress:
                on_progress(queue)

    finally:
        signal.signal(signal.SIGINT, old_handler)

    return queue


def retry_failed(queue: VideoQueue) -> int:
    """Marca itens com erro ou em standby como aguardando (reprocessar)."""
    count = 0
    for item in queue.items:
        if item.status in (QueueItemStatus.ERROR, QueueItemStatus.PAUSED):
            item.status = QueueItemStatus.WAITING
            item.error = ""
            item.retry_count += 1
            count += 1
    return count


def cancel_item(queue: VideoQueue, index: int) -> bool:
    """Cancela um item específico (se aguardando ou em erro)."""
    if 0 <= index < len(queue.items):
        item = queue.items[index]
        if item.status in (QueueItemStatus.WAITING, QueueItemStatus.ERROR):
            item.status = QueueItemStatus.CANCELLED
            return True
    return False


def reorder_items(queue: VideoQueue, from_index: int, to_index: int) -> bool:
    """Reordena itens na fila (apenas itens aguardando)."""
    if not (0 <= from_index < len(queue.items) and 0 <= to_index < len(queue.items)):
        return False
    if queue.items[from_index].status != QueueItemStatus.WAITING:
        return False
    item = queue.items.pop(from_index)
    queue.items.insert(to_index, item)
    return True


def pause_queue(queue: VideoQueue) -> None:
    queue.paused = True


def resume_queue(queue: VideoQueue) -> None:
    queue.paused = False


def cancel_queue(queue: VideoQueue) -> None:
    queue.cancelled = True
    current = queue.get_current()
    if current and current.status == QueueItemStatus.PROCESSING:
        current.status = QueueItemStatus.CANCELLED


def default_queues_dir(cfg: CurioConfig) -> str:
    """Pasta padrão das filas, consistente com o restante da configuração."""
    return cfg.queues_dir or "queues"


def ensure_queues_dir(cfg: CurioConfig) -> str:
    path = default_queues_dir(cfg)
    os.makedirs(path, exist_ok=True)
    return path


def list_queue_files(queues_dir: str) -> list[str]:
    """Lista arquivos de fila (.txt e .json) na pasta padrão."""
    if not os.path.isdir(queues_dir):
        return []
    out = []
    for entry in sorted(os.listdir(queues_dir)):
        if entry.lower().endswith((".txt", ".json")):
            full = os.path.join(queues_dir, entry)
            if os.path.isfile(full):
                out.append(full)
    return out


def remove_item(queue: VideoQueue, index: int) -> bool:
    """Remove um item ainda não processado (atalho para VideoQueue.remove)."""
    return queue.remove(index)