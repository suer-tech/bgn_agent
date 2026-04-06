import os
import sys
import json
from dotenv import load_dotenv
from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import (
    GetBenchmarkRequest,
    StartPlaygroundRequest,
    EndTrialRequest,
)
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import AnswerRequest, Outcome
from agents.context_extractor import create_context_extractor
from llm_provider import create_provider

# Load environment variables
load_dotenv()

BITGN_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"
BENCHMARK_ID = os.getenv("BENCHMARK_ID") or "bitgn/pac1-dev"

def write_reports(tasks_data, benchmark_id, benchmark_description):
    """Writes both JSON and Markdown reports from the collected tasks data."""
    # Ensure tasks are sorted by ID for the report
    sorted_data = sorted(tasks_data, key=lambda x: x["task_id"])

    # Write data to JSON
    json_file = "tasks_context_overview.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(sorted_data, f, indent=2, ensure_ascii=False)
    
    # Create a human-friendly Markdown report
    md_file = "tasks_context_overview.md"
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(f"# Deep Task Overview: {benchmark_id}\n\n")
        f.write(f"> {benchmark_description}\n\n")
        f.write("## Table of Contents\n")
        for t in sorted_data:
            f.write(f"- [{t['task_id']}](#{t['task_id'].lower()})\n")
        f.write("\n---\n\n")
        
        for t in sorted_data:
            f.write(f"## {t['task_id']}\n\n")
            f.write(f"### Instruction\n```text\n{t['instruction']}\n```\n")
            if t.get('hint'):
                f.write(f"\n**Hint**: {t['hint']}\n")
                
            if t.get('eval_feedback'):
                f.write(f"\n**Benchmark Evaluation Feedback**:\n```text\n{t['eval_feedback']}\n```\n")
            
            if "error" in t:
                f.write(f"\n> [!CAUTION]\n> Extraction Failed: {t['error']}\n")
                f.write("\n---\n\n")
                continue
            
            f.write("\n### Workspace Context\n")
            f.write("<details>\n<summary>Directory Tree</summary>\n\n")
            f.write(f"```text\n{t['tree']}\n```\n")
            f.write("</details>\n\n")
            
            # AGENTS.md
            agents_md = t.get('agents_md', {})
            f.write("<details>\n<summary>AGENTS.md</summary>\n\n")
            if agents_md.get('content'):
                f.write(f"```markdown\n{agents_md['content']}\n```\n")
            else:
                f.write("*Not found*\n")
            f.write("</details>\n\n")
            
            # Context Docs
            docs = t.get('context_docs', {})
            if docs:
                f.write("<details>\n<summary>Related Documentation (Instruction Graph)</summary>\n\n")
                for path, content in docs.items():
                    if path.lower() in ["agents.md", "agents.md"]: continue 
                    f.write(f"#### {path}\n")
                    f.write(f"```markdown\n{content}\n```\n\n")
                f.write("</details>\n")
            
            f.write("\n---\n\n")

def main():
    # Allow filtering tasks from command line (e.g. python get_task_info.py t01 t04)
    task_filter = sys.argv[1:]
    
    try:
        # Initialize client, provider, and extractor
        client = HarnessServiceClientSync(BITGN_URL)
        provider = create_provider()
        extractor = create_context_extractor(provider=provider)
        
        print(f"Connecting to {BITGN_URL}...")
        
        # Get benchmark metadata
        res = client.get_benchmark(GetBenchmarkRequest(benchmark_id=BENCHMARK_ID))
        
        # Try to load existing data to support resuming
        json_file = "tasks_context_overview.json"
        tasks_data = []
        processed_ids = set()
        
        if os.path.exists(json_file):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    tasks_data = json.load(f)
                    processed_ids = {t["task_id"] for t in tasks_data if "error" not in t}
                print(f"Loaded {len(processed_ids)} already processed tasks from {json_file}")
            except Exception as e:
                print(f"Warning: Could not load existing reports: {e}")
        
        # Filter tasks to process
        target_tasks = [t for t in res.tasks if not task_filter or t.task_id in task_filter]
        
        print(f"\nProcessing {len(target_tasks)} tasks with Incremental FULL LLM extraction...\n")
        
        for task in target_tasks:
            # Skip if already processed and not in manual filter
            if task.task_id in processed_ids and not task_filter:
                print(f"[{task.task_id}] Already processed, skipping.")
                continue

            print(f"[{task.task_id}] Starting deep extraction...", flush=True)
            try:
                # Start playground to access the task's VM
                trial = client.start_playground(
                    StartPlaygroundRequest(
                        benchmark_id=BENCHMARK_ID,
                        task_id=task.task_id,
                    )
                )
                
                # Perform deep extraction (tree, AGENTS.md, linked docs)
                payload = extractor.extract_task_graph(
                    harness_url=trial.harness_url,
                    task_text=trial.instruction
                )
                
                # Connect to PCM runtime and send OUTCOME_ERR_INTERNAL to trigger hints
                vm = PcmRuntimeClientSync(trial.harness_url)
                vm.answer(AnswerRequest(
                    message="Retrieving task context - extraction agent skip",
                    outcome=Outcome.OUTCOME_ERR_INTERNAL
                ))

                # Immediately end the trial to clean up the environment and get evaluation feedback
                end_res = client.end_trial(EndTrialRequest(trial_id=trial.trial_id))
                eval_feedback = "\n".join(end_res.score_detail) if end_res.score_detail else ""

                # Aggregate data
                task_entry = {
                    "task_id": task.task_id,
                    "instruction": trial.instruction,
                    "hint": task.hint,
                    "eval_feedback": eval_feedback,
                    "tree": payload.get("directory_tree_formatted", ""),
                    "agents_md": payload.get("graph", {}).get("agents_md", {}),
                    "context_docs": payload.get("context_docs", {})
                }
                
                # Update or append
                existing_idx = next((i for i, t in enumerate(tasks_data) if t["task_id"] == task.task_id), -1)
                if existing_idx >= 0:
                    tasks_data[existing_idx] = task_entry
                else:
                    tasks_data.append(task_entry)
                
                # Write reports incrementally
                write_reports(tasks_data, BENCHMARK_ID, res.description)
                
                print(f"[{task.task_id}] Successfully extracted context and feedback.", flush=True)
                
            except Exception as e:
                print(f"[{task.task_id}] ERROR: {e}")
                error_entry = {
                    "task_id": task.task_id,
                    "instruction": task.preview,
                    "hint": task.hint,
                    "error": str(e)
                }
                # Update or append error
                existing_idx = next((i for i, t in enumerate(tasks_data) if t["task_id"] == task.task_id), -1)
                if existing_idx >= 0:
                    tasks_data[existing_idx] = error_entry
                else:
                    tasks_data.append(error_entry)
                write_reports(tasks_data, BENCHMARK_ID, res.description)

        print(f"\nSUCCESS: Reports updated for all target tasks.")

    except Exception as e:
        print(f"FATAL ERROR: {e}")

if __name__ == "__main__":
    main()
