# PAC1 Agent — Архитектура обработки задачи

## Pipeline

```
PCM: quick tree (/,level=2)          [0 LLM, ~1s]
         │
         ▼
┌─────────────────────────┐
│  1. TRIAGE              │  [1 LLM call, ~12-15s]
│  Input: task_text + tree│
│  Output: TriageDecision │
│  (is_safe, intent)      │
│  BLOCK if: ATTACK,      │
│  UNSUPPORTED, CLARIFY   │
└────────┬────────────────┘
         │ pass
         ▼
┌─────────────────────────┐
│  2. BOOTSTRAP           │  [0-1 LLM call, ~10-15s]
│  Phase 1 (код):         │
│   - read AGENTS.md      │
│   - regex: все ссылки   │
│   - read linked files   │
│  Phase 2 (1 LLM):       │
│   - context advisor     │
│   - "какие ещё файлы?"  │
│  Phase 3 (код):         │
│   - read доп. файлы     │
│  Output: workspace_rules│
│  + authority_map         │
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│  3. TASK EXTRACTION     │  [1 LLM call, ~12-15s]
│  Input: task + rules    │
│  Output: TaskModel      │
│  (domain, intent,       │
│   target_entities,      │
│   constraints)          │
└────────┬────────────────┘
         │
         ├── Decision Gate (код):
         │   ambiguity_high + MUTATION → CLARIFICATION
         │   security_risk_high + SECURITY_DENIAL → DENY
         │
         ▼
┌─────────────────────────┐
│  4. STRATEGIC ANALYSIS  │  [1 LLM call, ~15-20s]
│  Input: task + rules    │
│  + tree                 │
│  Output:                │
│   - predicted_entities  │
│   - verification_       │
│     checklist           │
│   - risks               │
│   - scope_boundary      │
│   - execution_approach  │
│                         │
│  Код-проверка после:    │
│  если risk содержит     │
│  "contradiction" →      │
│  BLOCK CLARIFICATION    │
└────────┬────────────────┘
         │
         ├── Entity graph init (код):
         │   scratchpad.entity_graph = predicted_entities
         │
         ├── Context Gatherer (код, 0 LLM):
         │   search target_entities → read related files
         │   extract dates → format for prompt
         │
         ▼
┌═══════════════════════════════════════════════════════════┐
║  5. EXECUTION LOOP  (max 30 iterations)                  ║
║                                                          ║
║  Каждая итерация:                                        ║
║                                                          ║
║  ┌───────────────────────┐                               ║
║  │ 5a. build_planner_    │  Формирует system prompt:     ║
║  │     prompt()          │  - sandbox env + date         ║
║  │                       │  - tool schema                ║
║  │                       │  - instruction hierarchy      ║
║  │                       │  - workspace rules (из boot.) ║
║  │                       │  - meta-rules                 ║
║  │                       │  - strategic context          ║
║  │                       │    (checklist, risks, scope)  ║
║  │                       │  - entity context             ║
║  │                       │  - scratchpad (entity_graph)  ║
║  │                       │  - task text                  ║
║  └───────┬───────────────┘                               ║
║          ▼                                               ║
║  ┌───────────────────────┐                               ║
║  │ 5b. plan_next_step()  │  [1 LLM call, ~15-25s]       ║
║  │                       │                               ║
║  │  Input: prompt +      │  Output: NextStep             ║
║  │  conversation_history │  - current_state              ║
║  │                       │  - plan_remaining_steps       ║
║  │                       │  - decision_justification     ║
║  │                       │    (RuleCitation: source_file, ║
║  │                       │     source_type, rule_quote)  ║
║  │                       │  - scratchpad_update          ║
║  │                       │    (entity_graph!)            ║
║  │                       │  - mutation_plan (if write)   ║
║  │                       │    (target, why, not_touched) ║
║  │                       │  - function (tool call)       ║
║  │                       │                               ║
║  │  Retry: если          │                               ║
║  │  justification пустой │                               ║
║  │  → feedback + retry   │                               ║
║  └───────┬───────────────┘                               ║
║          │                                               ║
║          ├── if report_completion:                        ║
║          │   ┌─────────────────────────────┐             ║
║          │   │ Unresolved entity check     │ (код)       ║
║          │   │ Если есть unresolved →      │             ║
║          │   │ feedback "resolve first"    │             ║
║          │   │ → continue loop             │             ║
║          │   │                             │             ║
║          │   │ Если все resolved →         │             ║
║          │   │ auto-build grounding_refs   │             ║
║          │   │ из entity_graph.resolved    │             ║
║          │   │ + LLM refs (deduplicated)   │             ║
║          │   │ → BREAK loop                │             ║
║          │   └─────────────────────────────┘             ║
║          │                                               ║
║          ├── if subagent_delegation:                      ║
║          │   run_subagent_session() → feedback            ║
║          │                                               ║
║          ├── else (normal tool call):                     ║
║          │                                               ║
║          ▼                                               ║
║  ┌───────────────────────┐                               ║
║  │ 5c. Mutation Plan     │  (код, 0 LLM)                ║
║  │     Check             │  Log: target, why,            ║
║  │                       │  not_touched                  ║
║  └───────┬───────────────┘                               ║
║          ▼                                               ║
║  ┌───────────────────────┐                               ║
║  │ 5d. execute_tool()    │  (код, 0 LLM)                ║
║  │                       │  PCM call: read/write/etc.    ║
║  │  Guardrails:          │                               ║
║  │  - path traversal     │                               ║
║  │  - read-only files    │                               ║
║  │  - sensitive files    │                               ║
║  │  - truncation 10k     │                               ║
║  └───────┬───────────────┘                               ║
║          ▼                                               ║
║  ┌───────────────────────┐                               ║
║  │ 5e. Post-execution    │                               ║
║  │     Guardrails        │  (код, 0-1 LLM)              ║
║  │                       │                               ║
║  │ e1. Security scan     │  Код-эвристика (regex):       ║
║  │     (inbox files)     │  - injection patterns         ║
║  │                       │  - false authority             ║
║  │                       │  - exfiltration               ║
║  │                       │  - destructive commands       ║
║  │                       │  Clean → 0 LLM               ║
║  │                       │  Flagged → 1 LLM escalation  ║
║  │                       │  Confirmed → BLOCK SECURITY   ║
║  │                       │                               ║
║  │ e2. Read tracking     │  Код:                         ║
║  │     + inbox counter   │  - track read source files    ║
║  │     + sequential read │  - count inbox msg reads      ║
║  │                       │  - 4+ reads same dir →        ║
║  │                       │    feedback "use search"      ║
║  │                       │                               ║
║  │ e3. Delete protection │  Код (HARD BLOCK):            ║
║  │     (MINIMAL DIFF)    │  file in read_sources AND     ║
║  │                       │  task has no "delete" →       ║
║  │                       │  BLOCK                        ║
║  │                       │                               ║
║  │ e4. Scope alert       │  Код (SOFT — feedback):       ║
║  │                       │  write/delete in must_not_    ║
║  │                       │  touch → alert to LLM         ║
║  │                       │                               ║
║  │ e5. RuleCitation      │  Код (SOFT — feedback):       ║
║  │     authority check   │  DATA_HINT for mutation →     ║
║  │                       │  alert "check README"         ║
║  │                       │                               ║
║  │ e6. Mutation validator│  Код:                         ║
║  │                       │  relevance check              ║
║  └───────┬───────────────┘                               ║
║          │                                               ║
║          ▼                                               ║
║  conversation_history.append(tool_call + result)         ║
║  → next iteration                                        ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
         │
         ▼
┌─────────────────────────┐
│  6. PRE-COMPLETION      │  [0 LLM, код]
│     REVIEW              │
│  - unresolved entities? │
│  - pending checklist?   │
│  → log issues           │
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│  7. SEND ANSWER         │  [0 LLM]
│  send_answer(           │
│    message,             │
│    outcome,             │
│    refs=grounding_refs  │  ← auto-built from
│  )                      │    entity_graph
└─────────────────────────┘
```

## LLM calls по этапам

| Этап | LLM calls | Когда больше |
|------|-----------|-------------|
| Triage | 1 | Всегда 1 |
| Bootstrap (context advisor) | 0-1 | 1 если есть workspace |
| Task Extraction | 1 | Всегда 1 |
| Strategic Analysis | 1 | Всегда 1 |
| Execution loop | N × 1 | 2 (lookup) — 14 (complex inbox) |
| Security escalation | 0-1 | 1 только если heuristic flagged |
| Justification retry | 0-1 | 1 если пустой justification |
| Pre-completion review | 0 | Код-проверка |
| **Total** | **4 + N** | **6 (simple) — 18 (complex)** |

## Модели данных (Pydantic)

### NextStep (каждый шаг execution loop)
```
current_state: str
plan_remaining_steps_brief: List[str]
decision_justification: RuleCitation
  ├── source_file: str        "/reminders/README.MD"
  ├── source_type: enum       README_INVARIANT | PROCESS_DOC | DATA_HINT | ...
  └── rule_quote: str         "keep them aligned when rescheduling"
mutation_plan: Optional[MutationPlan]
  ├── target_file: str
  ├── action: write|delete|move|mkdir
  ├── why_this_file: str
  └── similar_files_not_touched: List[str]
scratchpad_update: ScratchpadState
  ├── current_goal: str
  ├── entity_graph: List[TrackedEntity]
  │   └── entity_type, identifier, resolved_file, status, depends_on
  ├── missing_info: str
  ├── completed_steps: List[str]
  └── pending_items_to_process: List[str]
task_completed: bool
function: Union[ReportTaskCompletion, Req_Read, Req_Write, ...]
```

### StrategicAnalysis (перед execution)
```
predicted_entities: List[TrackedEntity]
verification_checklist: List[VerificationItem]
  └── check, source_rule, status (pending/passed/failed/skipped)
risks: List[Risk]
  └── description, mitigation, source_rule
scope_boundary: ScopeBoundary
  └── files_may_create, files_may_modify, files_must_not_touch, reasoning
execution_approach: str
```

## Код-guardrails (без LLM)

| Guardrail | Тип | Где |
|-----------|-----|-----|
| Path traversal (..) | HARD BLOCK | tool_executor.py |
| Read-only files (AGENTS.md) | HARD BLOCK | tool_executor.py |
| OTP direct read | HARD BLOCK | tool_executor.py |
| Delete source file (no "delete" in task) | HARD BLOCK | orchestrator.py |
| Contradiction in rules | HARD BLOCK | orchestrator.py (post-strategic) |
| Unresolved entities at completion | FEEDBACK LOOP | orchestrator.py |
| 4+ reads same directory | SOFT FEEDBACK | orchestrator.py |
| Multiple inbox messages | SOFT FEEDBACK | orchestrator.py |
| Scope boundary violation | SOFT ALERT | orchestrator.py |
| DATA_HINT for mutation | SOFT ALERT | orchestrator.py |
| Security heuristic (regex) | ESCALATE to LLM | security_node.py |
| Mutation relevance | SOFT WARNING | validator_node.py |

## Файлы системы

```
orchestrator.py              — State Machine, весь pipeline
agents/
  types.py                   — Все Pydantic модели
  triage_node.py             — Triage (1 LLM)
  bootstrap_node.py          — Universal workspace explorer (0-1 LLM)
  task_node.py               — Task extraction (1 LLM)
  strategic_analysis_node.py — Strategic analysis (1 LLM)
  execution_agent.py         — Prompt builder + plan_next_step (N LLM)
  security_node.py           — Heuristic + LLM escalation
  validator_node.py          — Post-mutation validation
  context_gatherer.py        — Entity context pre-search
  subagent_node.py           — Subagent delegation
  tool_executor.py           — PCM dispatch + guardrails
  pcm_helpers.py             — Low-level PCM wrappers
  pre_completion_review_node.py — (deprecated, replaced by code check)
  triage_and_task_node.py    — (deprecated, reverted to separate)
main.py                      — Entry point
llm_provider.py              — LLM providers (Claude, OpenRouter, etc.)
llm_logger.py                — Trace logging
```

---

## Подробное описание работы системы по шагам

### Контекст: что это такое

Система решает задачи **PAC1 бенчмарка** — бенчмарк для AI-агентов, работающих с файловыми рабочими пространствами (CRM, inbox, заметки и т.д.). Агент подключается к **изолированной песочнице** (PCM — виртуальная файловая система через gRPC), получает текстовое задание и должен выполнить его, используя только файловые операции (read/write/delete/search и т.д.).

---

### ШАГ 0: Точка входа (`main.py`)

1. Подключается к BitGN API, получает список задач бенчмарка
2. Для каждой задачи запускает `StartPlaygroundRequest` — получает `harness_url` (адрес песочницы) и `instruction` (текст задания)
3. Создаёт `LLMProvider` (OpenRouter/Claude CLI/etc.) и `Orchestrator`
4. Вызывает `orchestrator.run(harness_url, task_text, task_id)`
5. После завершения — `EndTrialRequest` → получает score

**Данные на входе**: `task_text` (текст задания), `harness_url` (адрес PCM)
**Данные на выходе**: score от бенчмарка

---

### ШАГ 1: Инициализация (`orchestrator.py:96-108`)

Создаётся `AgentState` — центральный объект-состояние, TypedDict:

```python
state = {
    "task_text": "...",               # исходное задание
    "triage_result": None,            # результат классификации
    "task_model": None,               # структурированная модель задачи
    "workspace_rules": {},            # файлы правил (путь → содержимое)
    "authority_map": AuthorityMap(),   # иерархия правил с приоритетами
    "strategic_analysis": None,       # стратегический анализ
    "scratchpad": ScratchpadState(),  # рабочая память агента
    "entity_context": "",             # собранный контекст по сущностям
    "conversation_history": [],       # история вызовов инструментов
    "is_completed": False,
    "final_outcome": "",
}
```

Затем:
- **Получает дату песочницы** через `vm.context()` — эта дата используется для всех расчётов "сегодня", "через неделю" и т.д. Дата вставляется в начало `task_text`: `[Current date: 2026-04-14]\n{task_text}`
- **Делает `tree /` (level=2)** — быстрый обзор структуры workspace для triage

**0 LLM вызовов, ~1-2 секунды**

---

### ШАГ 2: Triage (`triage_node.py`)

**Цель**: быстро классифицировать задачу — безопасна ли она, какой тип (чтение/запись/атака/unsupported).

**Вход**:
- `task_text` (с датой)
- `workspace_tree` (дерево файлов)

**Что делает**:
1. Формирует промпт `TRIAGE_SYSTEM_PROMPT` + задание + дерево
2. **1 вызов LLM** с Structured Output → `TriageDecision(is_safe, intent, domain, reason)`
3. Если `intent` == ATTACK/UNSUPPORTED/CLARIFY_NEEDED → `is_completed = True`, pipeline останавливается

**Выход**: `state["triage_result"]` заполнен. Если заблокировано — сразу отправляется `send_answer` и return.

**Как LLM отвечает**: через `llm_provider.complete_as(messages, TriageDecision)` — LLM получает JSON-схему Pydantic модели и обязан вернуть JSON, который парсится в эту модель.

---

### ШАГ 3: Bootstrap (`bootstrap_node.py`)

**Цель**: загрузить ВСЕ инструкции рабочего пространства (AGENTS.md, README.md, process docs) ДО начала работы.

**Фаза 1 (0 LLM, детерминистическая)**:
1. `tree / level=3` — полное дерево
2. Ищет и читает корневой `AGENTS.md` (пробует варианты имён)
3. Из AGENTS.md regex-ами извлекает ВСЕ ссылки на файлы: `[text](path)`, `` `path` ``, просто `file.md`
4. Каждую ссылку — читает файл или листает директорию. Если директория — ищет в ней README.md/AGENTS.md
5. Каждый файл добавляется в `rules` (путь → содержимое) и `AuthorityMap` с уровнем (ROOT/NESTED/FOLDER/PROCESS)

**Фаза 2 (1 LLM)**:
1. Отправляет LLM: дерево + уже загруженные файлы + задание
2. LLM возвращает `ContextAdvice(additional_paths, reasoning)` — какие ещё файлы нужно подгрузить
3. Это "контекстный советник" — он понимает задание и знает, какие правила будут нужны

**Фаза 3 (0 LLM)**:
1. Читает все файлы, рекомендованные LLM
2. Добавляет в `rules` и `AuthorityMap`

**Выход**: `state["workspace_rules"]` — словарь {путь: содержимое}, `state["authority_map"]` — иерархия правил

**Контекст передаётся дальше** через `state` — эти правила потом целиком вставляются в промпт execution agent'а.

---

### ШАГ 4: Task Extraction (`task_node.py`)

**Цель**: из текста задания + загруженных правил извлечь структурированную модель задачи.

**1 вызов LLM** → `TaskModel`:
```python
domain: DomainType          # KNOWLEDGE_REPO / TYPED_CRM / INBOX_WORKFLOW / etc.
intent: IntentType          # LOOKUP / MUTATION
requested_effect: str       # "send_email", "update_contact"
target_entities: List[str]  # ["Matthias Schuster", "acct_007"]
constraints: List[str]      # ["keep dates aligned"]
ambiguity_high: bool
security_risk_high: bool
```

**Выход**: `state["task_model"]`

---

### ШАГ 4.5: Decision Gate (код, 0 LLM)

Проверяет комбинацию ambiguity + intent:
- `ambiguity_high + MUTATION` → STOP, CLARIFICATION
- `security_risk_high + SECURITY_DENIAL` → STOP, DENY

---

### ШАГ 5: Strategic Analysis (`strategic_analysis_node.py`)

**Цель**: подумать о задаче ДО начала исполнения — спрогнозировать сущности, риски, чеклист.

**Вход LLM**: дерево + все правила + задание

**1 вызов LLM** → `StrategicAnalysis`:
- `predicted_entities` — какие сущности (контакты, аккаунты, записи) понадобятся, все `status="unresolved"`
- `verification_checklist` — что проверить перед завершением (из правил workspace)
- `risks` — что может пойти не так (спуфинг, cross-account access, противоречия правил)
- `scope_boundary` — какие файлы можно создавать/менять/нельзя трогать
- `execution_approach` — план из 2-3 предложений

**После LLM — код-проверка**: если в risks есть "contradiction"/"irreconcilable" → STOP, CLARIFICATION

**Выход**: `state["strategic_analysis"]`, инициализация `state["scratchpad"].entity_graph = predicted_entities`

---

### ШАГ 5.5: Context Gatherer (`context_gatherer.py`, 0 LLM)

**Цель**: предварительно найти и прочитать файлы, связанные с target_entities, и извлечь все даты.

**Что делает**:
1. Для каждой entity из `task_model.target_entities`:
   - `search` по имени entity во всей файловой системе
   - Читает найденные файлы
   - Из JSON файлов: рекурсивно извлекает все поля-даты (ISO формат)
   - Из текстовых файлов: regex-ами ищет даты (ISO + prose "March 15, 2026")
   - Извлекает cross-references (`contact_id` → `contacts/{id}.json`)
2. Формирует таблицу дат для каждой entity

**Выход**: `state["entity_context"]` — строка с таблицами дат, вставляется в промпт execution agent'а

---

### ШАГ 6: Execution Loop (до 30 итераций)

Это **главный цикл** — здесь агент реально работает с файлами.

**Каждая итерация**:

#### 6a. `build_planner_prompt(state)` — формирование промпта

Собирает ОГРОМНЫЙ system prompt из всех частей state:
1. **Sandbox env** — дата, описание мира
2. **Tool schema** — доступные инструменты (tree, list, read, write, delete, search, find, move, mkdir, report_completion)
3. **Instruction Hierarchy** — 5 уровней приоритета (system prompt > root AGENTS.md > child docs > task text > data files)
4. **Workspace rules** — ВСЕ загруженные правила, отсортированные по AuthorityLevel
5. **Meta-rules** — MINIMAL DIFF, ENTITY VERIFICATION, ONE-AT-A-TIME, etc.
6. **Strategic context** — чеклист, риски, scope boundaries
7. **Entity context** — таблицы дат из context gatherer
8. **Scratchpad** — текущая рабочая память агента (JSON)
9. **User request** — в `<user_input>` тегах (чтобы LLM не воспринимал как команды)

#### 6b. `plan_next_step()` — вызов LLM

**Вход**: system prompt + `conversation_history` (вся предыдущая переписка tool calls + results)

**1 вызов LLM** → `NextStep`:
```python
current_state: str               # описание текущего состояния
plan_remaining_steps_brief: []   # оставшиеся шаги
decision_justification: RuleCitation  # ОБЯЗАТЕЛЬНО: какое правило оправдывает действие
scratchpad_update: ScratchpadState    # обновлённая рабочая память
mutation_plan: MutationPlan?     # если пишем/удаляем — что именно и почему
task_completed: bool
function: Union[Read, Write, Search, ...]  # КОНКРЕТНЫЙ tool call
```

Если `decision_justification` пустой — retry с фидбэком (до 2 попыток).

#### 6c. Обработка результата

**Если `report_completion`**:
1. Проверяет entity_graph — есть ли `unresolved` entities
2. Если есть → feedback "resolve first", continue loop
3. Если все resolved → собирает `grounding_refs` из resolved_file paths, BREAK

**Если subagent_delegation**: запускает субагента (отдельный мини-pipeline)

**Если обычный tool call**:

#### 6d. `execute_tool()` — исполнение

**Guardrails (код, 0 LLM)**:
- Path traversal (`..`) → BLOCK
- Write/delete to AGENTS.md → BLOCK
- Direct read of `otp.txt` → BLOCK
- Результат > 10000 символов → truncation

Вызывает `dispatch_tool()` → gRPC к PCM (песочнице) → получает результат

#### 6e. Post-execution guardrails

**e1. Security scan** — только для read файлов из inbox:
- Regex-эвристика ищет injection-паттерны ("ignore rules", "admin override", etc.)
- Если чисто → 0 LLM
- Если подозрительно → 1 LLM call для подтверждения → если confirmed → BLOCK

**e2. Read tracking**:
- Считает прочитанные файлы, inbox messages
- 4+ reads из одной директории → feedback "use search"
- >1 inbox message → feedback "one at a time"

**e3. Delete protection**:
- Файл был прочитан как source + задание не содержит "delete" → HARD BLOCK

**e4. Scope alert**:
- Write/delete в файл из `must_not_touch` → soft alert в result

**e5. Authority check**:
- Если mutation основана на DATA_HINT (низший приоритет) → alert "check README"

**e6. Mutation validator**:
- Проверка релевантности мутации

#### 6f. Запись в conversation_history

```python
conversation_history.append(
    {"role": "assistant", "content": ..., "tool_calls": [...]},  # что LLM решил
)
conversation_history.append(
    {"role": "tool", "content": result_text, "tool_call_id": step_name},  # результат
)
```

Эта история передаётся в следующую итерацию в `plan_next_step()` — LLM видит ВСЮ историю своих действий.

---

### ШАГ 7: Pre-Completion Review (код, 0 LLM)

Финальная проверка перед отправкой:
- Есть ли unresolved entities?
- Есть ли pending checklist items?
- Логирует issues

---

### ШАГ 8: Send Answer (`pcm_helpers.send_answer`)

```python
vm.answer(AnswerRequest(
    message=final_answer,        # текст ответа
    outcome=OUTCOME_OK,          # enum результата
    refs=grounding_refs,         # пути к файлам-доказательствам
))
```

---

### Как передаётся контекст — сводка

| Откуда → Куда | Что передаётся | Как |
|---|---|---|
| main → orchestrator | `task_text`, `harness_url` | аргументы функции |
| triage → state | `TriageDecision` | `state["triage_result"]` |
| bootstrap → state | rules + AuthorityMap | `state["workspace_rules"]`, `state["authority_map"]` |
| task extraction → state | `TaskModel` | `state["task_model"]` |
| strategic analysis → state | entities, checklist, risks, scope | `state["strategic_analysis"]` |
| context gatherer → state | таблицы дат | `state["entity_context"]` (строка) |
| execution loop iteration N → iteration N+1 | tool call + result | `state["conversation_history"]` (append) |
| execution loop → LLM | ВСЁ вышеперечисленное | `build_planner_prompt(state)` — один огромный system prompt |
| LLM → execution loop | NextStep (tool call + scratchpad) | Pydantic structured output |

---

### LLM Provider — как вызывается LLM

Все вызовы LLM идут через `llm_provider.complete_as(messages, ResponseType)`:
1. Формирует `messages` (OpenAI-формат: system/user/assistant/tool)
2. Добавляет JSON-схему Pydantic модели как инструкцию "respond with this schema"
3. Вызывает LLM (OpenRouter API / Claude CLI subprocess / ручной ввод)
4. Парсит ответ: извлекает JSON → `ResponseType.model_validate(data)`

---

### Итого LLM вызовов на задачу

| Этап | Вызовов |
|---|---|
| Triage | 1 |
| Bootstrap context advisor | 1 |
| Task Extraction | 1 |
| Strategic Analysis | 1 |
| Execution loop (N итераций) | N |
| Security escalation (если срабатывает) | 0-1 |
| **Итого** | **4 + N** (обычно 6-18) |
