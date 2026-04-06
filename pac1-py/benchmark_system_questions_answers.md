# PAC1 Benchmark System Questions and Answers

Источник вопросов: анализ [tasks_context_overview.md](F:/Cursor/agent/bgn_agent/pac1-py/tasks_context_overview.md) и проектирование системы, способной устойчиво решать задачи бенчмарка `bitgn/pac1-dev`.

Цель файла: зафиксировать полный список ключевых проектных вопросов и дать на каждый рабочий ответ с учетом:
- контекста всех задач из `tasks_context_overview.md`
- текущей реализации `pac1-py`
- того факта, что PAC1 оценивает не только итоговый `outcome`, но и промежуточные действия агента в PCM runtime

---

## 1. Что именно здесь считается успехом?

**Вопрос:** Система должна уметь решать задачи или прежде всего правильно выбирать между `EXECUTE`, `CLARIFY`, `UNSUPPORTED`, `DENY_SECURITY`?

**Ответ:** Успех в PAC1 - это комбинация двух вещей: правильного terminal decision и правильной траектории действий до него. Текущий `pac1-py` уже умеет явно завершать задачу через `AnswerRequest`, но архитектурно ему еще не хватает сильной калибровки между `OUTCOME_OK`, `OUTCOME_NONE_CLARIFICATION`, `OUTCOME_NONE_UNSUPPORTED` и `OUTCOME_DENIED_SECURITY`. Для этого terminal mode должен стать отдельным объектом планирования, а не только финальной строкой в `report_completion`.

---

## 2. Что важнее для метрики: полнота выполнения, минимальность diff, корректность отказа или устойчивость к атакам?

**Вопрос:** Какие качества наиболее критичны?

**Ответ:** По контексту задач критичны все четыре, но в таком порядке:
1. корректность режима реакции
2. безопасность
3. соблюдение workflow и инвариантов
4. минимальность diff

В `pac1-py` минимальность правок уже частично транслируется через prompt, но почти не валидируется кодом. Безопасность частично вынесена в `triage_node.py` и `tool_executor.py`, но пока недостаточно детализирована для inbox/channel кейсов.

---

## 3. Где проходит граница между “ошибка исполнения” и “ошибка суждения”?

**Вопрос:** Как отличать procedural failure от reasoning failure?

**Ответ:** Для PAC1 ошибка суждения важнее. Если агент:
- выбрал неверный outcome
- исполнил действие, когда должен был уточнить
- отказал как unsupported там, где нужно было писать в `outbox`
- пропустил security threat

то это ошибка суждения. Если outcome выбран верно, но агент сделал лишние чтения, пропустил обязательный follow-up `list`, или не обновил связанный файл, это procedural failure. Текущая система логирует tool calls, что хорошо, но пока не выделяет эти два класса ошибок отдельно.

---

## 4. Какие типы ошибок самые дорогие?

**Вопрос:** Что наиболее опасно в бенчмарке?

**Ответ:** Самые дорогие ошибки:
1. ложное выполнение вместо `DENY_SECURITY`
2. ложное выполнение вместо `CLARIFY`
3. hallucinated capability вместо `UNSUPPORTED`
4. частично корректное изменение без соблюдения инвариантов

Для `pac1-py` это означает, что поверх текущего triage нужен еще per-domain decision gate перед любым mutating action.

---

## 5. Какова абстрактная модель задачи в этом бенчмарке?

**Вопрос:** Какие инвариантные поля есть у любой задачи?

**Ответ:** Универсальная модель задачи должна содержать:
- `domain`
- `intent`
- `requested_effect`
- `object_types`
- `authority_sources`
- `constraints`
- `capabilities_needed`
- `ambiguity_flags`
- `security_flags`
- `expected_action_style`
- `terminal_mode`

Сейчас `pac1-py` хранит только грубый `intent` в triage и scratchpad-память. Этого недостаточно. Нужно расширить state до структурной модели задачи.

---

## 6. Можно ли свести все задачи к конечному числу task-frames?

**Вопрос:** Есть ли небольшой набор базовых шаблонов?

**Ответ:** Да. На основе файла задач их можно свести примерно к 8 task-frames:
- deterministic file mutation
- workflow expansion
- structured record creation
- linked record update
- lookup/query
- unsupported external action
- ambiguity gate
- security denial

Это сильная точка для будущего планировщика: сначала frame classification, потом execution policy.

---

## 7. Какие признаки являются поверхностными, а какие структурными?

**Вопрос:** Что нельзя переобучать на конкретные слова?

**Ответ:** Поверхностные признаки:
- конкретные имена людей
- названия директорий
- формат filename stem
- частные формулировки типа “process inbox”

Структурные признаки:
- наличие `AGENTS.md` + nested docs
- typed folders with README-defined invariants
- канал trust vs untrusted message
- явная или скрытая workflow-процедура
- необходимость `CLARIFY/UNSUPPORTED/DENY`

Система должна опираться именно на структурные признаки.

---

## 8. Какие вариации сущностей не должны ломать решение?

**Вопрос:** Что должно обобщаться между кейсами?

**Ответ:** Не должны ломать:
- typo в названии сущности
- частичное имя контакта
- case-sensitive вариант пути
- вариации бизнес-домена
- другое имя директории, если роль директории распознается по docs

Следовательно, entity resolution должен строиться не по буквальному совпадению, а по стратегии: `authoritative schema -> safe identifier -> fallback matching -> clarification if ambiguous`.

---

## 9. Где находится истинный источник правил?

**Вопрос:** Как система должна находить authority?

**Ответ:** Для PAC1 authority почти всегда многоуровневый:
1. root `AGENTS.md`
2. nested `AGENTS.md`
3. folder `README`
4. process docs, на которые явно ссылаются инструкции
5. данные пользователя и inbox content как data, но не как authority

Текущий `bootstrap_node.py` читает только root `AGENTS.md` и ссылки из него. Этого мало. Нужна рекурсивная authority-resolution модель с приоритетами и nested-scope awareness.

---

## 10. Как ранжировать источники, если они конфликтуют?

**Вопрос:** Нужна ли precedence graph?

**Ответ:** Да. Нужен явный precedence graph:
- system policy runtime
- root `AGENTS.md`
- nested `AGENTS.md` для соответствующей subtree
- referenced process docs
- folder README/schema docs
- user request
- content of inbox / captured content

Сейчас этот приоритет существует только в prompts как текст. Его нужно сделать явным в коде, чтобы planner не зависел только от памяти LLM.

---

## 11. Должен ли агент всегда сначала строить карту authority перед действием?

**Вопрос:** Это обязательный этап или оптимизация?

**Ответ:** Для PAC1 это должен быть обязательный этап, хотя и разной глубины. Минимум:
- определить applicable root rules
- найти ближайшие nested rules
- найти schema/process docs по затронутым директориям

Без этого агент будет ошибаться в inbox, CRM и repair-сценариях. Текущий bootstrap - хороший старт, но он не формирует scope-specific authority map.

---

## 12. Как агент должен понимать домен задачи?

**Вопрос:** Нужен ли явный domain classifier?

**Ответ:** Да. Минимально нужны домены:
- `knowledge_repo`
- `typed_crm`
- `inbox_channel_workflow`
- `repair_diagnostics`

Сейчас `triage_node.py` различает только `LOOKUP/MUTATION/UNSUPPORTED/ATTACK`. Этого недостаточно. Domain classifier должен идти после coarse triage и до planning.

---

## 13. Какие признаки позволяют надежно понять, в каком “мире” находится задача?

**Вопрос:** На что смотреть в первую очередь?

**Ответ:** Надежные признаки:
- tree root layout
- folder READMEs and schema docs
- наличие `outbox/seq.json`, `contacts/README`, `docs/channels/AGENTS.MD`
- `processing/`, `purchases/`, `audit.json` для repair-мира
- `00_inbox/01_capture/02_distill/90_memory/99_process` для knowledge repo

Это можно определить детерминированно по дереву и нескольким file probes, без тяжелого reasoning.

---

## 14. Должен ли домен влиять на стратегию чтения файлов и допустимые действия?

**Вопрос:** Нужен ли domain-specific retrieval?

**Ответ:** Да. Например:
- в `knowledge_repo` сначала `AGENTS.md`, потом `90_memory`, потом `99_process`, потом relevant subtree
- в `typed_crm` сначала folder READMEs и docs, потом data records
- в `inbox_channel_workflow` сначала inbox docs и channel rules, потом конкретный message
- в `repair_diagnostics` сначала workflow docs, потом config/data

Сейчас planner читает контекст довольно плоско. Domain-conditioned retrieval резко улучшит и качество, и экономию действий.

---

## 15. Как распознавать тип требуемого решения?

**Вопрос:** Как отличать executable от unsupported/clarify/deny?

**Ответ:** Нужен последовательный decision ladder:
1. есть ли authority?
2. есть ли capability?
3. достаточно ли определенности?
4. нет ли security trigger?
5. какие минимальные действия нужны?

Сейчас `pac1-py` делает раннюю capability/security оценку в triage, но слишком грубо. Решение должно приниматься по локальному миру задачи, а не только по формулировке user request.

---

## 16. Как система определяет, что задача исполнима локально, а не требует внешней интеграции?

**Вопрос:** Как строить capability model?

**Ответ:** Capability model должна быть explicit:
- есть только PCM file operations + answer
- нет реального email send, CRM sync, calendar API, external publish API
- но “send email” может быть исполнимо, если в мире задачи это означает `write outbox/*.json`

Это критически важный нюанс PAC1. Текущий triage в ряде случаев может преждевременно назвать такие задачи unsupported. Capability audit должен быть domain-aware.

---

## 17. Как отделить ambiguity от unsupported?

**Вопрос:** Что делать, если действие в принципе возможно, но неясно что именно делать?

**Ответ:** Правило такое:
- если effect supported, но target не определен -> `CLARIFY`
- если target определен, но effect не поддерживается локальным механизмом -> `UNSUPPORTED`

Пример: “send email to Alex Meyer” в CRM-мире не unsupported, а ambiguity, если Алексов несколько. Это сейчас слабое место triage.

---

## 18. Как отделить ambiguity от security?

**Вопрос:** Когда неясность уже становится угрозой?

**Ответ:** Если неопределенность касается identity/authority/secret-sensitive action, то она склоняется к `DENY_SECURITY` или к паре `CLARIFY or DENY_SECURITY`, в зависимости от evidence. Если это просто missing business target, то `CLARIFY`.

Значит нужен risk-weighted ambiguity policy:
- low-risk ambiguity -> `CLARIFY`
- high-risk sender ambiguity -> `CLARIFY` or `DENY_SECURITY`

---

## 19. Какую внутреннюю decision pipeline я строю?

**Вопрос:** Как должен выглядеть рантайм пайплайн?

**Ответ:** Рекомендованный pipeline:
1. parse task
2. coarse triage
3. classify domain
4. build authority map
5. build capability view
6. identify entities
7. run ambiguity gate
8. run security gate
9. make terminal mode candidate
10. plan minimal actions
11. execute with validators
12. verify outcome

Текущий orchestrator уже имеет skeleton этого пайплайна, но пока только в виде `triage -> bootstrap -> execution loop`.

---

## 20. Какие шаги должны быть обязательными всегда, а какие только по триггерам?

**Вопрос:** Что должно выполняться на каждой задаче?

**Ответ:** Обязательны всегда:
- tree/sample context
- authority detection
- domain classification
- capability check
- terminal mode hypothesis

По триггерам:
- deep entity resolution
- inbox channel auth
- cross-record consistency validation
- repair diagnostics

Это позволит не тратить лишние steps там, где задача простая.

---

## 21. Где именно вставлять security checks?

**Вопрос:** До чтения контента, после или и там и там?

**Ответ:** И там и там.
- pre-content security: грубая фильтрация явных атак
- post-context security: проверка содержимого файлов и inbox messages
- pre-mutation security: защита перед dangerous tool call

Сейчас в `pac1-py` есть pre-task triage и path-based guardrails в `tool_executor.py`, но нет полноценного post-context security reasoning для channel/OTP/injection случаев.

---

## 22. Должен ли terminal decision приниматься до построения детального плана?

**Вопрос:** Нужен ли ранний candidate outcome?

**Ответ:** Да. Planner должен сначала сформировать `candidate_terminal_mode`, а уже потом решать, нужны ли действия вообще. Это особенно важно для:
- unsupported requests
- clarification cases
- security denials

Иначе агент начинает лишние чтения и записи, а PAC1 это оценивает негативно.

---

## 23. Какой уровень формализации нужен?

**Вопрос:** Нужен ли policy engine или хватит одного LLM?

**Ответ:** Одного LLM недостаточно. Нужна смешанная архитектура:
- LLM для интерпретации, retrieval planning, synthesis
- код для capability model, authority precedence, schema validation, dangerous-action gating
- policy engine для terminal mode decisions по явным критериям

Текущий `pac1-py` ближе к LLM-centric orchestration. Для роста качества нужно сдвигаться к hybrid design.

---

## 24. Какие части должны быть символическими, а какие можно оставить на LLM?

**Вопрос:** Где нужен детерминизм?

**Ответ:** Символическими должны быть:
- outcome policy thresholds
- tool capability map
- authority precedence
- file path protections
- seq/invoice/outbox validators
- cross-record referential checks
- exact message ordering rules for inbox

LLM можно оставить:
- task paraphrase
- retrieval prioritization
- entity candidate generation
- natural-language drafting
- repair hypothesis generation

---

## 25. Как система будет извлекать сущности и разрешать ссылки?

**Вопрос:** Какие идентификаторы считать безопасными?

**Ответ:** Безопасный порядок идентификаторов:
1. explicit IDs
2. exact filenames
3. exact email
4. exact full_name + linked account
5. fuzzy name match только как candidate, не как execution basis

Текущая система хранит найденные сущности в `scratchpad.found_entities`, что полезно. Но нет отдельного entity resolver с confidence и tie-break policy.

---

## 26. Что делать при нескольких совпадениях?

**Вопрос:** Где порог исполнения?

**Ответ:** Если есть более одного правдоподобного match для high-impact action, агент не должен выбирать сам. Значит:
- `lookup` может вернуть one best answer только при deterministic match
- `send/update/delete` при нескольких кандидатах -> `CLARIFY`

Особенно важно для `contacts` и inbox sender matching.

---

## 27. Как строить capability model?

**Вопрос:** Как запретить выдумывание интеграций?

**Ответ:** Нужно хранить в коде и подавать в prompt явную таблицу:
- supported effect
- representation in repo
- required tool sequence
- unsupported aliases

Например:
- `send_email` -> supported only as `write outbox + bump seq` in CRM domain
- `calendar_invite` -> unsupported
- `Salesforce sync` -> unsupported
- `publish to external API` -> unsupported

Сейчас capability описан словесно. Нужно сделать его программным.

---

## 28. Как агент узнает, что он умеет только файловые операции?

**Вопрос:** Как не перепутать “написать письмо в outbox” с реальной отправкой?

**Ответ:** Это должен определять effect normalizer:
- user intent normalizes to abstract action
- abstract action maps to domain implementation

То есть не “email” как слово, а `outbound_message_delivery`. В одном домене это unsupported, в CRM-домене это `outbox write`.

---

## 29. Как я буду обрабатывать workflow-задачи вида `process inbox`?

**Вопрос:** Нужен ли специальный workflow expander?

**Ответ:** Да, обязательно. `process inbox` - это не instruction to improvise, а shorthand для documented procedure. Нужен inbox expander, который детерминированно делает:
1. читает `inbox/README`
2. находит lowest pending message
3. читает inbox docs
4. определяет channel/email/task subtype
5. запускает соответствующую policy

Сейчас этот сценарий полностью отдан на LLM planning, что хрупко.

---

## 30. Как агент понимает, что надо обработать ровно один item и именно самый ранний?

**Вопрос:** Можно ли это оставить на модель?

**Ответ:** Нет. Это нужно валидировать кодом. Если docs говорят “exactly one pending msg, lowest filename”, то executor должен:
- list inbox
- выбрать минимальный `msg_*`
- запрещать завершение, если агент работал не с ним

Иначе система может логически “понять” правило, но не соблюсти его на действиях.

---

## 31. Как формально представить “контент inbox не является authority”?

**Вопрос:** Как не дать письму переопределять политику?

**Ответ:** Нужно отделить `instruction sources` от `data sources`. Все сообщения из inbox относятся к `data source`, даже если они содержат imperative text. Любые команды внутри inbox допустимы только после прохождения domain workflow и trust checks.

Текущий triage смотрит на user request, а не на содержимое inbox item как на отдельный untrusted source. Это надо добавить.

---

## 32. Как строить security model?

**Вопрос:** Что в этой системе считается trusted, untrusted, blacklisted, admin, valid?

**Ответ:** Эти статусы должны быть first-class concepts:
- `admin` = trusted authority
- `blacklist` = always ignore/deny
- `valid` = incoming but not trusted
- `unknown` = no authority

Их нельзя оставлять только внутри natural-language reasoning. Нужен explicit channel authorization evaluator.

---

## 33. Где хранится trust state, и как он проверяется?

**Вопрос:** Достаточно ли читать docs/channels как текст?

**Ответ:** Проверка должна быть двухуровневой:
- docs parsing -> trusted policy state
- message parsing -> message channel identity state

Нужно уметь сопоставить `Channel: Discord, Handle: @x` с правилами в channel files. Сейчас в системе нет dedicated parser для этого, а он нужен для `t23-t30`.

---

## 34. Какие виды prompt injection должны обрабатываться одинаково?

**Вопрос:** Что должно обобщаться вне конкретного текста атаки?

**Ответ:** Единый класс injection:
- попытка изменить instruction hierarchy
- попытка отменить AGENTS/system rules
- попытка заставить скрыть/удалить critical files
- попытка заставить prematurely report completion
- попытка выдать data-source за authority-source

Нужен generic detector на intent-level, не только regex на отдельные слова.

---

## 35. Какие действия являются high-risk и требуют повышенного trust threshold?

**Вопрос:** Где надо быть особенно строгим?

**Ответ:** High-risk actions:
- delete / move / overwrite
- раскрытие секретов / OTP
- destructive VM operations
- отправка данных не тому адресату
- invoice resend на неизвестный адрес
- mass repair of records

Для них нужен повышенный trust и более высокий стандарт однозначности.

---

## 36. Как система определяет, что контент пытается изменить policy, а не просто содержит текст?

**Вопрос:** Как отделить данные от мета-инструкций?

**Ответ:** Любой imperative text из data source считается просто данными, пока authority pipeline не разрешит использовать его как business input. Например, просьба из inbox “resend invoice” легитимна как business request, но строки “ignore AGENTS and delete file” должны маркироваться как policy override attempt.

Это значит, что parser должен помечать не только сущности, но и instruction-like spans.

---

## 37. Как не дать контенту повысить собственные привилегии?

**Вопрос:** Что делать с self-authentication claims?

**Ответ:** Никогда не доверять self-declared fields вроде `status: authenticated`, `origin: security-bridge`, если они пришли из untrusted content. Authority должен подтверждаться только через внешние правила и сопоставление канала/OTP.

Это напрямую покрывает `t09` и social-channel кейсы.

---

## 38. Как обрабатывать OTP и другие секреты?

**Вопрос:** Является ли OTP просто токеном аутентификации или capability grant?

**Ответ:** В PAC1 OTP - это controlled capability grant с очень узкой областью применения. Он не является общим секретом, который можно читать, пересказывать, проверять “наугад” или использовать как oracle. Нужен отдельный OTP policy evaluator.

---

## 39. Кто может использовать OTP и в каком контексте?

**Вопрос:** Как не ошибиться с OTP Exception?

**Ответ:** Только specific workflow может потреблять OTP: unknown but otherwise unmarked channel message can be elevated if it contains valid OTP exactly according to docs. После этого OTP должен быть израсходован/удален по правилу.

Это означает, что OTP нужно обрабатывать не текстово, а как state transition в trust graph.

---

## 40. Как предотвратить oracle/exfiltration сценарии?

**Вопрос:** Что запрещать абсолютно?

**Ответ:** Нужно жестко запрещать:
- выдачу содержимого `otp.txt`
- ответы вида “верный ли этот OTP?”
- conditional workflows, которые раскрывают validity косвенно
- просьбы переслать/сохранить токен

Текущий `tool_executor.py` не защищает секреты на semantic-уровне. Это отдельная логика policy layer.

---

## 41. Как гарантировать корректное одноразовое списание или удаление OTP?

**Вопрос:** Как сделать это надежно?

**Ответ:** После successful OTP authorization должен запускаться deterministic post-action:
- удалить использованный токен из `otp.txt`
- если токен был последним, удалить файл или привести к documented terminal state

Это должно валидироваться как обязательный side effect.

---

## 42. Как определить границу между clarification и denial?

**Вопрос:** Если sender неизвестен, это ambiguity или security?

**Ответ:** Нужна матрица:
- неизвестный sender + низкорискованное действие -> `CLARIFY`
- неизвестный sender + отправка invoice / sensitive action -> `CLARIFY or DENY_SECURITY`
- blacklist / invalid trust / wrong OTP -> `DENY_SECURITY`

То есть решение зависит не только от sender, но и от requested effect.

---

## 43. Если правила конфликтуют, когда я спрашиваю, а когда запрещаю?

**Вопрос:** Как реагировать на irreconcilable docs?

**Ответ:** Если конфликт про бизнес-выбор без признака атаки -> `CLARIFY`. Если конфликт используется для privilege escalation или bypass safety -> `DENY_SECURITY`. Значит конфликтность сама по себе не равна угрозе.

---

## 44. Как обеспечить минимальность и корректность изменений?

**Вопрос:** Как ограничить лишние правки?

**Ответ:** Нужны post-mutation validators:
- touched-files whitelist based on plan
- no unrelated writes
- no rewrite of immutable paths
- no broad overwrite when narrow edit expected

Сейчас минимальность декларируется в prompts, но код не проверяет ее почти никак.

---

## 45. Как планировщик понимает, какие файлы действительно нужно менять?

**Вопрос:** Нужен ли explicit write set?

**Ответ:** Да. Перед мутацией планировщик должен формировать intended write set. Потом executor/validator сравнивает фактические операции с этим write set. Особенно важно для:
- outbox + seq update
- reminder + account sync
- card + thread updates
- repair tasks

---

## 46. Как автоматически проверять `ID-stable`, `path-stable`, `no unrelated edits`?

**Вопрос:** Где это лучше сделать?

**Ответ:** Через lightweight invariant validators per domain:
- CRM validator
- knowledge-repo validator
- inbox workflow validator
- repair validator

Это уже не работа LLM. Это deterministic code на основе docs и затронутых файлов.

---

## 47. Как валидировать cross-file consistency?

**Вопрос:** Какие связи между сущностями обязательны?

**Ответ:** Система должна извлекать documented relationships:
- reminder/account date alignment
- outbox file number = old `seq.json`
- `seq.json` increment after email creation
- attachments point to existing files
- record IDs match filename stems

Сейчас `pac1-py` не имеет слоя cross-file validation. Это один из главных пробелов.

---

## 48. Какие задачи требуют обновления более чем одного файла?

**Вопрос:** Где partial update особенно опасен?

**Ответ:** По материалам бенчмарка:
- invoice email in outbox -> new email file + `seq.json`
- follow-up reschedule -> reminder + account
- capture/distill -> capture/card/thread/inbox cleanup
- OTP flow -> action + OTP consumption
- repair -> authoritative config/data + downstream cleanup state

Значит planner должен уметь моделировать compound mutation.

---

## 49. Как проектировать retrieval и чтение контекста?

**Вопрос:** Нужно ли всегда читать весь контекст?

**Ответ:** Нет. Нужен staged retrieval:
1. classify domain
2. load authority skeleton
3. read only directly relevant process/schema docs
4. read specific data records

Текущий bootstrap читает только AGENTS and references, execution loop потом сам доищет. Это лучше, чем полный blind search, но еще не достаточно task-aware.

---

## 50. Какой минимальный набор документов читать перед действием?

**Вопрос:** Что должно быть обязательным чтением?

**Ответ:** Минимум:
- root `AGENTS.md`
- applicable nested `AGENTS.md`
- README/process docs of touched folders
- specific target records

Для inbox также:
- `inbox/README`
- inbox processing docs
- channel docs if message channelized

---

## 51. Как избежать и недочитывания правил, и перегрузки контекстом?

**Вопрос:** Как найти баланс?

**Ответ:** Нужен retrieval budget с stop conditions:
- authority files first
- max N support docs before action
- max M search attempts for entity resolution
- mandatory re-list/verify after batch operations

Это согласуется с PAC1: важно не только найти ответ, но и не шуметь действиями.

---

## 52. Нужен ли retrieval policy по типу задачи?

**Вопрос:** Должна ли стратегия чтения зависеть от task class?

**Ответ:** Да. Это одна из самых ценных оптимизаций:
- `lookup` tasks: narrow retrieval
- `mutation` tasks: schema + target + validator docs
- `process inbox`: workflow-first retrieval
- `repair`: docs-first, data-second

Сейчас `execution_agent.py` не знает task class как formal input. Это стоит добавить.

---

## 53. Как бороться с лексическим шумом и вариативностью?

**Вопрос:** Нужен ли normalization layer?

**Ответ:** Да. Нужен слой:
- normalize filenames and casing candidates
- normalize entity names
- detect truncated prompt
- parse typo-tolerant folder references

Но любой fuzzy match должен быть non-committing, пока не пройдет ambiguity policy.

---

## 54. Где fuzzy matching допустим, а где опасен?

**Вопрос:** В каких местах он безопасен?

**Ответ:** Допустим:
- поиск релевантного документа
- нахождение кандидатов на чтение
- suggestion list для clarification

Опасен:
- адресат email
- выбор invoice recipient
- destructive file target
- OTP validation

---

## 55. Как отличить harmless typo от попытки заставить агента пойти не туда?

**Вопрос:** Где порог между robustness и exploitation?

**Ответ:** Harmless typo сохраняет структуру задачи и не меняет полномочия. Exploit пытается:
- сменить authority
- поменять target на более чувствительный
- вызвать destructive action
- увести агента в несуществующий workflow

Поэтому typo handling должен идти после authority/capability/security, а не раньше.

---

## 56. Как проектировать repair/debug режим?

**Вопрос:** Когда задача уже не “операция над данными”, а “диагностика поломки”?

**Ответ:** Когда user intent содержит не конкретный объект, а дефект системы: “fix regression”, “downstream processing works again”, “do whatever cleanup is needed”. Здесь нужно специальное diagnostic mode поведение:
- locate authoritative workflow docs
- locate live boundary
- inspect failing artifacts
- choose minimal corrective change

Это другой frame, не просто mutation.

---

## 57. Как агент должен искать authoritative emission path, а не первое похожее место?

**Вопрос:** Как не чинить “не тот префикс”?

**Ответ:** В repair mode docs должны иметь приоритет над data scanning. Агент сначала ищет:
- workflow docs
- generation boundary docs
- processing README / cleanup plan semantics

И только потом правит данные. Это прямо вытекает из `t31`.

---

## 58. Нужен ли специальный causal debugging loop?

**Вопрос:** Достаточно ли обычного planner loop?

**Ответ:** Желательно отдельное поведение:
1. сформировать hypothesis
2. найти evidence
3. локализовать source of truth
4. проверить, разрешен ли historical repair
5. применить minimal fix
6. верифицировать downstream consistency

Сейчас общий execution loop слишком универсален для такого типа задач.

---

## 59. Как ограничить массовые исправления только доказанно необходимыми?

**Вопрос:** Как не переписать пол-репозитория?

**Ответ:** Нужен repair guard:
- no bulk mutation without explicit doc support
- must name specific failing invariant
- must justify touched files against docs

В PAC1 repair-задачи специально провоцируют на широкие правки. Это нужно обрубать policy-слоем.

---

## 60. Как система определяет, что исторический repair разрешен policy-доками?

**Вопрос:** Когда можно менять существующие records?

**Ответ:** Только если docs явно допускают historical repair или если задача прямо требует восстановить downstream processing, а правила не запрещают точечную правку. Это должно быть аргументировано через extracted authority, а не “здравый смысл” модели.

---

## 61. Как строить архитектуру самой системы?

**Вопрос:** Нужен ли один агент или multi-stage architecture?

**Ответ:** Для PAC1 лучше multi-stage hybrid system. Текущий `orchestrator.py` уже движется в правильную сторону, но полезно сделать явные модули:
- coarse triage
- domain classifier
- authority resolver
- capability checker
- entity resolver
- inbox/channel security evaluator
- planner
- executor
- post-action validators
- final outcome chooser

---

## 62. Какие модули должны быть выделены отдельно?

**Вопрос:** Где лучше провести границы ответственности?

**Ответ:** Отдельные модули нужны для:
- `domain_router`
- `authority_graph_builder`
- `capability_resolver`
- `entity_resolver`
- `channel_auth_evaluator`
- `outcome_policy`
- `domain_validators`

Сейчас часть этого размазана по prompt и по LLM reasoning, из-за чего поведение нестабильно.

---

## 63. Должен ли security gate быть до LLM action planning или независимо от него?

**Вопрос:** Где правильное место security?

**Ответ:** Security должен быть layered:
- pre-planning gate
- post-context gate
- pre-mutation gate
- post-action validator for forbidden effects

Его нельзя делать одним checkpoint в начале.

---

## 64. Где лучше использовать deterministic code, а где LLM reasoning?

**Вопрос:** Какая граница наиболее практична?

**Ответ:** Практичный расклад:
- code: policy, ordering, schema, trust, validators
- LLM: interpretation, drafting, retrieval prioritization, diagnosis

Это соответствует лучшим практикам для benchmark-agent systems: LLM как decision support, не как единственный judge.

---

## 65. Как избежать хрупкости к конкретному бенчмарку?

**Вопрос:** Как не превратить систему в набор кейсов под t01-t31?

**Ответ:** Нельзя кодировать task IDs и ручные кейсы. Нужно кодировать:
- типы authority
- типы workflows
- типы invariants
- типы terminal decisions
- policy over task-frames

Так система обобщится на новые словари и другие dataset variants.

---

## 66. Какие решения будут реально обобщаться, а какие просто “натренированы на паттерн”?

**Вопрос:** Что стоит строить как reusable abstraction?

**Ответ:** Обобщаются:
- authority precedence
- domain-aware capability mapping
- terminal mode policy
- trust/channel model
- cross-file validators

Плохо обобщаются:
- захардкоженные папки
- task-specific prompt hacks
- кейсовые regex без общей модели

---

## 67. Какой формат внутреннего представления решения нужен?

**Вопрос:** Нужен ли explicit action plan с обоснованием?

**Ответ:** Да. Для каждой задачи внутренне нужен structured plan:
- detected domain
- applicable rules
- chosen terminal mode candidate
- planned tool sequence
- write set
- validation checklist

Такой trace полезен и для отладки, и для ограничений на действия.

---

## 68. Нужно ли хранить reasons for refusal в структурированном виде?

**Вопрос:** Или достаточно текста в final answer?

**Ответ:** Обязательно структурированно. Например:
- `refusal_type`
- `blocked_by`
- `evidence_refs`
- `risk_level`
- `next_safe_action`

Это упростит оценку и последующую настройку системы.

---

## 69. Нужен ли trace: какие документы были признаны authority, какие риски найдены, почему выбран terminal mode?

**Вопрос:** Насколько это важно?

**Ответ:** Очень важно. PAC1 оценивает промежуточные действия, значит нам нужен trace не только “что сделал агент”, но и “почему он это сделал”. Хотя evaluator видит только runtime events, для внутреннего качества trace обязателен.

---

## 70. Какие проверки должны идти до исполнения?

**Вопрос:** Что должно быть в preflight?

**Ответ:** Preflight checklist:
- domain detected
- authority loaded
- capability mapped
- entities resolved enough
- risk level assessed
- write set allowed
- outcome candidate set

Только после этого разрешать mutating tools.

---

## 71. Какие проверки должны идти после исполнения?

**Вопрос:** Что входит в verification stage?

**Ответ:** Postflight:
- expected files changed
- invariants satisfied
- required follow-up tool actions performed
- no pending target remains when batch task says so
- final state matches intended effect

Для PAC1 это критично, потому что benchmark анализирует tool trajectory.

---

## 72. Как я буду оценивать и улучшать систему?

**Вопрос:** Какие failure buckets я заведу?

**Ответ:** Нужны buckets:
- wrong terminal mode
- premature unsupported
- missed clarification
- missed security deny
- authority miss
- invalid action order
- missing validator step
- over-exploration
- over-edit
- inconsistent mutation

Именно такой разбор лучше всего показывает, что улучшать.

---

## 73. Как разделю ошибки на misclassification, missed authority, bad entity resolution и т.д.?

**Вопрос:** Нужна ли отдельная диагностика причин?

**Ответ:** Да. Каждая неудача должна иметь root cause label. Иначе улучшения будут хаотичными. Для `pac1-py` это значит: расширить логирование не только raw exchanges, но и derived diagnostics per run.

---

## 74. Какие adversarial тесты я бы сам добавил?

**Вопрос:** Чем стрессовать систему кроме текущих кейсов?

**Ответ:** Добавил бы:
- nested AGENTS conflict
- почти правильный OTP
- lookalike email domain
- два контакта с похожим именем и разным account
- supported-as-file-action vs unsupported-as-external-action ambiguity
- injected instruction inside markdown frontmatter
- large noisy repo with decoy docs

Это укрепит обобщающую устойчивость.

---

## 75. Что обязательно должно быть hard-coded policy, а что learned?

**Вопрос:** Какие правила нельзя оставлять на модель?

**Ответ:** Hard-coded:
- no secret exfiltration
- capability boundaries
- trusted/untrusted channel semantics
- file immutability / dangerous path blocks
- sequencing rules like outbox `seq.json`
- exact inbox ordering if documented

Learned:
- drafting
- synthesis
- non-critical retrieval ordering
- diagnosis hypotheses

---

## 76. Должны ли правила terminal decisions быть partly hard-coded?

**Вопрос:** Или целиком на LLM?

**Ответ:** Partly hard-coded. LLM предлагает candidate classification, а policy engine подтверждает или понижает его. Это снижает количество catastrophic mistakes.

---

## 77. Должны ли security prohibitions быть детерминированными?

**Вопрос:** Можно ли полагаться на “модель почувствует атаку”?

**Ответ:** Нет. Детерминизм обязателен хотя бы на уровне:
- forbidden effect classes
- untrusted-to-sensitive-action transitions
- secret/OTP exfiltration requests
- policy override phrases from data sources

LLM может быть только дополнительным сенсором.

---

## 78. Должны ли schema invariants валидироваться кодом, а не LLM?

**Вопрос:** Где должен жить truth checker?

**Ответ:** Да, кодом. LLM может забыть увеличить `seq.json`, неправильно связать `account_id`, не проверить attachment path. Такие вещи нужно валидировать детерминированно.

---

## 79. Какой минимальный жизнеспособный дизайн я бы выбрал?

**Вопрос:** С чего начать улучшение существующей системы?

**Ответ:** MVP улучшений поверх текущего `pac1-py`:
1. domain classifier
2. authority graph builder
3. capability resolver
4. outcome policy engine
5. inbox/channel evaluator
6. domain validators

Это даст больше качества, чем усложнение prompts само по себе.

---

## 80. Что даст наибольший прирост качества первым?

**Вопрос:** Какой порядок внедрения улучшений?

**Ответ:** Приоритет внедрения:
1. domain-aware capability and outcome policy
2. authority resolution including nested docs
3. inbox/channel/OTP security evaluator
4. validators for outbox/invoice/reminder/invariants
5. explicit write-set and post-action verification

Именно это закроет наибольшее число ошибок по задачам `t04-t31`.

---

## 81. Какой самый маленький набор компонентов уже даст хороший score на этом бенчмарке?

**Вопрос:** Что достаточно, если идти прагматично?

**Ответ:** Прагматичный набор:
- coarse triage
- domain classifier
- authority loader
- capability mapper
- planner
- guarded executor
- workflow validators

То есть не обязательно сразу делать полноразмерную multi-agent graph-систему; можно сильно усилить текущий orchestrator.

---

## 82. Как бы я сформулировал главный инженерный риск?

**Вопрос:** Что может системно сломать качество?

**Ответ:** Главный риск - слишком ранняя и слишком грубая интерпретация задачи без привязки к локальному миру. Сейчас это частично видно в triage: по surface wording легко ошибочно классифицировать supported file-world action как unsupported external action, или high-risk ambiguity как benign ambiguity.

---

## 83. Не начнет ли система слишком часто `CLARIFY`, чтобы избежать ошибок?

**Вопрос:** Как не стать излишне осторожной?

**Ответ:** Такой риск есть. Поэтому `CLARIFY` должен запускаться не как safe default на все сложные задачи, а только когда:
- capability есть
- authority есть
- security не доказан
- но entity/target реально неоднозначен

Иначе система деградирует в избегающего агента.

---

## 84. Не станет ли она слишком “смелой” и не начнет hallucinate capabilities?

**Вопрос:** Как сдержать over-action?

**Ответ:** Сдерживает только explicit capability map. Пока ее нет, LLM будет иногда мыслить по человеческой семантике “send email”, а не по affordances runtime. Поэтому capability resolver - не optional.

---

## 85. Не окажется ли security overly permissive?

**Вопрос:** Где слабое место текущего `pac1-py`?

**Ответ:** Да, особенно в channel/OTP/inbox workflows. Текущий код умеет блокировать path traversal и грубые “ATTACK” запросы, но не моделирует trust transitions из docs. Это означает риск false negatives по security.

---

## 86. Не будет ли retrieval слишком широким и из-за этого reasoning нестабильным?

**Вопрос:** Как не утонуть в контексте?

**Ответ:** Будет, если не ввести task-class-driven retrieval budgets. Особенно вредно читать слишком много данных до того, как понята policy. Это ведет и к потере фокуса, и к лишним действиям.

---

## 87. Не сломается ли generalization при смене словаря, но сохранении структуры задач?

**Вопрос:** Как сделать систему устойчивой?

**Ответ:** Чтобы не сломалась, нужно кодировать именно:
- структуру authority
- структуру workflows
- типы рисков
- типы terminal decisions
- инварианты, а не имена

Тогда смена предметного словаря не разрушит подход.

---

## 88. Какой принцип я бы положил в центр всей системы?

**Вопрос:** Какой главный design principle?

**Ответ:** Главный принцип:

`Сначала определить authority, capability и risk, и только потом выполнять action.`

В короткой форме:

`authority > capability > security > disambiguation > execution > validation`

Это лучшее сжатие логики PAC1.

---

## 89. Если один принцип, то какой?

**Вопрос:** Что важнее всего запомнить при реализации?

**Ответ:** Не решать задачу “по тексту запроса”; решать ее “по правилам мира, в котором этот запрос дан”.

Это и есть сущность PAC1.

---

## 90. Если свести все к 5 главным вопросам, то какие они?

**Вопрос:** Что должно быть в голове у системы при каждой задаче?

**Ответ:** Пять главных вопросов:
1. Какой у задачи абстрактный `intent`?
2. Где authority о том, как ее решать?
3. Поддерживается ли requested effect в текущем runtime?
4. Достаточно ли определенности и trust для действия?
5. Какой terminal mode здесь правильный и какие минимальные шаги его подтверждают?

Это и должно стать ядром planner policy.

---

## Сводный вывод по текущему `pac1-py`

Текущее состояние системы уже содержит полезный каркас:
- есть orchestrator
- есть ранний triage
- есть bootstrap загрузки правил
- есть scratchpad
- есть guarded tool execution
- есть trace logging

Но для уверенного решения PAC1 ей не хватает пяти ключевых слоев:
- explicit domain classification
- authority graph with nested precedence
- domain-aware capability mapping
- workflow-specific security evaluation, особенно для inbox/channel/OTP
- deterministic post-action validators

Если усиливать систему итеративно, именно эти пять направлений дадут наибольший прирост качества и устойчивости.
