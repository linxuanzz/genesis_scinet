"""Read a WfCommons workflow trace (WfFormat 1.x) and turn it into what a network agent sees.

A trace records one run on one machine: tasks, the files they read and write, their sizes and runtimes.
It says nothing about sites or the network. ``place`` supplies that: each program runs at a site, and the
workflow's external inputs (read but produced by no task) sit at a data site. Every file a task needs at
a site other than where the file is becomes a cross-site transfer, once per (file, destination site).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Task:
    task_id: str
    program: str                                      # e.g. "individuals"; the task id minus its "_ID..." suffix
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    runtime_seconds: float                            # as measured in the traced run


@dataclass(frozen=True)
class Workflow:
    name: str
    tasks: dict[str, Task]
    file_bytes: dict[str, int]
    producer: dict[str, str]                          # file → the task that writes it

    @property
    def external_inputs(self) -> list[str]:
        """Files read by some task but written by none: they exist before the workflow starts."""
        read = {file for task in self.tasks.values() for file in task.inputs}
        return sorted(read - set(self.producer))


@dataclass(frozen=True)
class FileTransfer:
    """One file that must move to a site before the tasks there can read it."""

    file: str
    src_site: str
    dst_site: str
    nbytes: int
    producer: str | None                              # the task that writes it; None for an external input
    consumers: tuple[str, ...]                        # the tasks at dst_site that read it


@dataclass
class Placement:
    """Where each task runs and where the external inputs are."""

    task_site: dict[str, str]
    data_site: str
    transfers: list[FileTransfer] = field(default_factory=list)


def load_workflow(path: str | Path) -> Workflow:
    trace = json.loads(Path(path).read_text())
    spec, execution = trace["workflow"]["specification"], trace["workflow"]["execution"]
    runtimes = {task["id"]: task["runtimeInSeconds"] for task in execution["tasks"]}
    tasks = {task["id"]: Task(task["id"], task["name"].rsplit("_ID", 1)[0], tuple(task["inputFiles"]),
                              tuple(task["outputFiles"]), runtimes[task["id"]])
             for task in spec["tasks"]}
    producer = {file: task.task_id for task in tasks.values() for file in task.outputs}
    return Workflow(trace["name"], tasks, {f["id"]: f["sizeInBytes"] for f in spec["files"]}, producer)


def place(workflow: Workflow, program_sites: dict[str, str], data_site: str) -> Placement:
    """Run every task at its program's site; list the cross-site transfers this implies."""
    missing = {task.program for task in workflow.tasks.values()} - set(program_sites)
    if missing:
        raise KeyError(f"no site for programs {sorted(missing)}")
    task_site = {task_id: program_sites[task.program] for task_id, task in workflow.tasks.items()}
    readers: dict[tuple[str, str], list[str]] = {}    # (file, site) → tasks there that read it
    for task in workflow.tasks.values():
        for file in task.inputs:
            readers.setdefault((file, task_site[task.task_id]), []).append(task.task_id)
    transfers = []
    for (file, site), consumers in sorted(readers.items()):
        producer = workflow.producer.get(file)
        src = task_site[producer] if producer else data_site
        if src != site:
            transfers.append(FileTransfer(file, src, site, workflow.file_bytes[file], producer, tuple(consumers)))
    return Placement(task_site, data_site, transfers)
