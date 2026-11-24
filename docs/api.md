# API contract (NestJS, port 3000, all routes under `/api`)

Configs are immutable: `POST /api/configs` with an existing `name` creates the next version. A config id is `name@vN`.

| Route | Returns |
|---|---|
| `GET /api/meta` | `{harnesses:[{name,capabilities:string[]}], models:[{id,price_per_1m:{input,output}}]}` |
| `GET /api/tasks` | `[{id,title,category,grader,requires:string[]}]` |
| `GET /api/configs` | `[Config]` (all versions, newest first) |
| `POST /api/configs` body `{name,harness,model,settings:{skills:bool,memory:bool,temperature:number(0-2),max_turns:int(1-200),token_budget:int(1000-5000000),nudge:bool}}` (name: letters, digits, space, `. _ -`; no `@`) | `Config` (400 on invalid input) |
| `GET /api/experiments` | `[Experiment]` |
| `POST /api/experiments` body `{name,config_ids:string[],task_ids?:string[],trials:number}` | `Experiment` (starts running in background) |
| `GET /api/experiments/:id` | `Experiment` |
| `GET /api/experiments/:id/summary` | `Summary` |
| `GET /api/experiments/:id/compare?a=<configId>&b=<configId>` | `Comparison` (400 if a == b or not part of the experiment) |
| `GET /api/experiments/:id/trials?config_id=&task_id=` | `[TrialRow]` (no events) |
| `GET /api/experiments/:id/failures` | `Failures` (rule-based classification of failed trials) |
| `GET /api/trials/:id` | `Trial` (with events) |
| `GET /api/experiments/:id/export.json` / `export.csv` | file download of all trials |

```ts
Config      = {id:string, name:string, version:number, hash:string, harness:string, model:string,
               settings:{skills:boolean, memory:boolean, temperature:number, max_turns:number}, created_at:string}
Experiment  = {id:string, name:string, status:'running'|'done', trials_per_task:number, config_ids:string[], task_ids:string[],
               created_at:string, progress:{total:number, done:number, infra_errors:number}, total_cost:number}
TrialRow    = {id:string, experiment_id:string, config_id:string, task_id:string, trial_idx:number,
               status:'queued'|'running'|'passed'|'failed'|'timeout'|'infra_error'|'grader_error'|'not_applicable',
               score:number|null, reasoning:string|null, duration_ms:number|null, cost_usd:number|null,
               usage:{prompt_tokens:number, completion_tokens:number, calls:number, latency_ms:number}|null}
Trial       = TrialRow & {final_text:string, files:string[], events:Event[]}
Event       = {type:'assistant', text, phase} | {type:'tool_call', id, name, input, kind:'tool'|'skill'|'memory', phase}
            | {type:'tool_result', id, name, output, error:boolean, phase} | {type:'error', message, phase}
            | {type:'grade', score:number|null, passed:boolean, reasoning:string}      // phase: 'seed'|'task'
Summary     = {experiment:Experiment, configs:[{config_id, name, harness, model, trials, scored, meanScore, ci:[number,number],
               infraErrors, timeouts, notApplicable, meanCostUsd, totalCostUsd, meanLatencyMs, meanTokens}]}
Comparison  = {a:string, b:string, pairedTasks:number,
               score:Stat, cost:Stat, latency_ms:Stat, tokens:Stat,          // Stat = {meanA,meanB,diff,ci:[lo,hi]}; diff = B - A
               verdict:'b_better'|'a_better'|'inconclusive'|'insufficient_data',   // CI excludes 0 / spans 0 / fewer than 3 paired tasks
               running:boolean, trialsUsed:{a:number,b:number},               // partial-result flag, trials behind each side
               mcnemar:{a_only:number, b_only:number, p:number}|null,
               perTask:[{task_id,title,category,n,nA,nB,meanA,meanB,delta,ci:[lo,hi],significant:boolean}]}   // significant needs nA,nB >= 2
Failures    = {categories:Category[], configs:[{config_id, failed:number, counts:Record<Category,number>}],
               trials:[{id, config_id, task_id, category:Category}]}          // trials: failures only
Category    = 'timeout'|'grader_error'|'budget_exhausted'|'capability_disabled'|'hallucinated_tool_args'|'capability_unused'|'gave_up_early'|'judge_borderline'|'wrong_answer'
                                                                              // first match wins, in this order
```
