"""
Workflow Automation Engine — Named workflow creation, storage, and execution.
Bridges NL intent → workflow plan → parallel execution.
"""
import json
from typing import Callable, Optional
from aios.llm_engine import generate_workflow_plan
from aios.task_executor import WorkflowExecutor
from aios.context_memory import memory


# Built-in preset workflows (override with custom ones)
PRESET_WORKFLOWS = {
    "ai_research": {
        "workflow_name": "ai_research",
        "description": "Setup AI research environment",
        "steps": [
            {"step_id": 1, "action": "open_app", "target": "vscode", "description": "Open VS Code", "parallel_group": 1},
            {"step_id": 2, "action": "open_app", "target": "chrome", "description": "Open Chrome browser", "parallel_group": 1},
            {"step_id": 3, "action": "open_app", "target": "terminal", "description": "Open Windows Terminal", "parallel_group": 1},
            {"step_id": 4, "action": "run_command", "target": "ollama serve", "description": "Start Ollama server", "parallel_group": 0},
        ]
    },
    "dev_mode": {
        "workflow_name": "dev_mode",
        "description": "Developer workspace setup",
        "steps": [
            {"step_id": 1, "action": "open_app", "target": "vscode", "description": "Open VS Code", "parallel_group": 1},
            {"step_id": 2, "action": "open_app", "target": "terminal", "description": "Open Terminal", "parallel_group": 1},
            {"step_id": 3, "action": "open_app", "target": "chrome", "description": "Open Chrome", "parallel_group": 1},
        ]
    },
    "presentation_mode": {
        "workflow_name": "presentation_mode",
        "description": "Setup presentation environment",
        "steps": [
            {"step_id": 1, "action": "open_app", "target": "powerpoint", "description": "Open PowerPoint", "parallel_group": 1},
            {"step_id": 2, "action": "open_app", "target": "chrome", "description": "Open Chrome for references", "parallel_group": 1},
            {"step_id": 3, "action": "notify", "target": "Presentation mode ready!", "description": "Notify user", "parallel_group": 0},
        ]
    },
    "focus_mode": {
        "workflow_name": "focus_mode",
        "description": "Deep work — minimal distractions",
        "steps": [
            {"step_id": 1, "action": "open_app", "target": "vscode", "description": "Open VS Code", "parallel_group": 1},
            {"step_id": 2, "action": "open_app", "target": "notepad", "description": "Open Notepad for notes", "parallel_group": 1},
            {"step_id": 3, "action": "notify", "target": "Focus mode active. Stay in flow.", "description": "Focus reminder", "parallel_group": 0},
        ]
    },
    "morning_setup": {
        "workflow_name": "morning_setup",
        "description": "Daily morning workspace initialization",
        "steps": [
            {"step_id": 1, "action": "open_app", "target": "chrome", "description": "Open browser", "parallel_group": 1},
            {"step_id": 2, "action": "open_app", "target": "vscode", "description": "Open VS Code", "parallel_group": 1},
            {"step_id": 3, "action": "open_app", "target": "terminal", "description": "Open Terminal", "parallel_group": 1},
            {"step_id": 4, "action": "notify", "target": "Good morning! Workspace initialized.", "description": "Morning greeting", "parallel_group": 0},
        ]
    },
}


class WorkflowEngine:
    """
    High-level workflow orchestration engine.
    Combines LLM planning + execution + memory.
    """

    def __init__(self, progress_callback: Callable = None):
        self.progress = progress_callback or print
        self.executor = WorkflowExecutor(progress_callback=self.progress)

    def run_by_name(self, name: str) -> Optional[dict]:
        """Run a preset or saved workflow by name."""
        name_lower = name.lower().strip()
        
        # Check presets first
        if name_lower in PRESET_WORKFLOWS:
            workflow = PRESET_WORKFLOWS[name_lower]
            self.progress(f"[Workflow] Loading preset: {name}")
            return self.executor.execute(workflow)
        
        # Check memory for saved workflows
        saved = memory.get_workflow(name_lower)
        if saved:
            self.progress(f"[Workflow] Loading from memory: {name}")
            return self.executor.execute(saved)
        
        return None

    def run_from_goal(self, goal: str, context: dict = None) -> dict:
        """
        Generate and execute a workflow from a natural language goal.
        Uses LLM to create execution plan.
        """
        self.progress(f"[Workflow] Planning: '{goal}'...")
        ctx = context or memory.get_context_summary()
        
        plan = generate_workflow_plan(goal, context=ctx)
        
        if not plan.get("steps"):
            self.progress("[Workflow] LLM couldn't generate steps. Using basic app open.")
            # Fallback: try to extract apps from goal
            return {"error": "Could not generate workflow plan", "goal": goal}
        
        self.progress(f"[Workflow] Plan: {plan.get('description', 'N/A')}")
        return self.executor.execute(plan)

    def list_available(self) -> list:
        """List all available workflows (presets + saved)."""
        available = []
        
        for name, wf in PRESET_WORKFLOWS.items():
            available.append({
                "name": name,
                "description": wf.get("description", ""),
                "source": "preset",
                "steps": len(wf.get("steps", [])),
            })
        
        for wf in memory.list_workflows():
            if wf["name"] not in PRESET_WORKFLOWS:
                available.append({
                    "name": wf["name"],
                    "description": wf.get("description", ""),
                    "source": "saved",
                    "steps": "?",
                    "run_count": wf.get("run_count", 0),
                })
        
        return available

    def save_custom(self, name: str, apps: list = None, commands: list = None, description: str = ""):
        """Save a custom workflow with given apps and commands."""
        steps = []
        step_id = 1
        
        if apps:
            for app in apps:
                steps.append({
                    "step_id": step_id,
                    "action": "open_app",
                    "target": app,
                    "description": f"Open {app}",
                    "parallel_group": 1  # All apps open in parallel
                })
                step_id += 1
        
        if commands:
            for cmd in commands:
                steps.append({
                    "step_id": step_id,
                    "action": "run_command",
                    "target": cmd,
                    "description": cmd,
                    "parallel_group": 0  # Commands run sequentially
                })
                step_id += 1
        
        workflow = {
            "workflow_name": name,
            "description": description or f"Custom workflow: {name}",
            "steps": steps
        }
        memory.save_workflow(name, workflow)
        return workflow
