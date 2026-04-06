import sys
import time

# Force immediate output
def log(msg):
    print(f">>> {msg}", flush=True)

log("DIAGNOSTIC ALIVE. Python version: " + sys.version)

log("Importing os...")
import os
log("OS OK")

log("Importing json...")
import json
log("JSON OK")

log("Importing dotenv...")
import dotenv
dotenv.load_dotenv()
log("DOTENV OK")

log("Importing pydantic...")
import pydantic
log("PYDANTIC OK")

log("Importing bitgn.vm.pcm_connect...")
try:
    import bitgn.vm.pcm_connect
    log("BITGN PCM OK")
except Exception as e:
    log(f"BITGN PCM FAILED: {e}")

log("Importing agents.types...")
import agents.types
log("TYPES OK")

log("Importing agents.pcm_helpers...")
import agents.pcm_helpers
log("PCM HELPERS OK")

log("Importing agents.triage_node...")
import agents.triage_node
log("TRIAGE OK")

log("Importing agents.bootstrap_node...")
import agents.bootstrap_node
log("BOOTSTRAP OK")

log("Importing agents.execution_agent...")
import agents.execution_agent
log("EXECUTION OK")

log("Importing orchestrator...")
import orchestrator
log("ORCHESTRATOR OK")

log("Importing main (this might trigger BitGN connection)...")
import main
log("MAIN OK")

log("=== DIAGNOSTIC FINISHED SUCCESSFULLY ===")
