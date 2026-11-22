# RecoverAI Complete Handover aur Learning Guide

**Snapshot date: 22 November 2026**  
**Language: Hinglish, Roman Hindi plus standard technical terms**  
**Repository: https://github.com/Sneha-090/RecoverAI**  
**Authoritative local checkout: `D:\RecoverAI`**  
**Reviewed application baseline: `d744a8748d8efda4bbf483b0310eccd88d72f3f0`**

Yeh ek self-contained project handbook hai. Isko tum khud padh sakti ho ya kisi future coding agent ko de sakti ho. Ismein project ka purpose, actual implementation, design reasons, verified evidence, pending work, Windows commands, complete project-focused syllabus, exercises aur interview preparation ek jagah hain. Code references relative to repository root hain. File ko akele share karne par bhi explanations readable rahengi; actual code run karne ke liye repository chahiye.

**Current conclusion:** RecoverAI ka tested Test Mode scope resume, recorded demo aur interview explanation ke liye ready hai. Real merchant deployment ki readiness establish nahi hui. Ab random features aur repeated manual payment testing resume wrap-up ki requirement nahi hain. Future merchant pilot ek separate, explicitly approved phase hoga.

Is handbook mein passwords, password hashes, API secrets, ngrok authtoken, raw customer payloads ya database copies nahi hain. Private configuration ko public GitHub ya kisi chat mein paste mat karna.

## Contents

1. [Project ko simple language mein samjho](#01-project-ko-simple-language-mein-samjho)
2. [Current verified status](#02-current-verified-status)
3. [Architecture aur stack](#03-architecture-aur-stack)
4. [Payment se recovery tak actual flow](#04-payment-se-recovery-tak-actual-flow)
5. [Decision aur scoring ko samjho](#05-decision-aur-scoring-ko-samjho)
6. [ML training aur honest evaluation](#06-ml-training-aur-honest-evaluation)
7. [Database aur state machines](#07-database-aur-state-machines)
8. [Kya improve kiya aur kyun](#08-kya-improve-kiya-aur-kyun)
9. [Kya complete hai aur kya pending](#09-kya-complete-hai-aur-kya-pending)
10. [Code map aur reading order](#10-code-map-aur-reading-order)
11. [Windows setup aur daily operation](#11-windows-setup-aur-daily-operation)
12. [Offline demo aur checks](#12-offline-demo-aur-checks)
13. [Troubleshooting aur operational rules](#13-troubleshooting-aur-operational-rules)
14. [Stack ka project focused syllabus](#14-stack-ka-project-focused-syllabus)
15. [Self study schedule](#15-self-study-schedule)
16. [Interview preparation](#16-interview-preparation)
17. [Resume content](#17-resume-content)
18. [Future agent ko dene wala prompt](#18-future-agent-ko-dene-wala-prompt)
19. [Files aur knowledge ko preserve kaise karein](#19-files-aur-knowledge-ko-preserve-kaise-karein)
20. [Glossary aur official resources](#20-glossary-aur-official-resources)

## 01 Project ko simple language mein samjho

### Problem kya hai

Customer ka payment fail ho jata hai, lekin merchant ke paas follow-up ka reliable process nahi hota. Sirf ek aur payment link bhejna enough nahi: pehla payment baad mein succeed ho sakta hai, ek webhook multiple baar aa sakta hai, provider response lose ho sakta hai, aur operator ko samajhna hota hai ki kis case mein kya karna sahi hai.

RecoverAI ek ML-assisted payment recovery aur reconciliation application hai. Yeh failure ko record karta hai, eligibility check karta hai, supported situations mein recovery options score karta hai, zaroorat par human approval leta hai, aur payment result verify karke original case update karta hai.

### Ek example

Ek course fee Rs.499 hai. Original payment fail hua. System pehle check karega: original order unpaid hai? Case recovery window ke andar hai? Stop ya opt-out nahi hai? Pehle same action execute nahi hua? Supported failure cause hai?

Agar context supported hai to model har eligible action ki estimated recovery probability deta hai. Policy cost-adjusted value se rank karti hai. Agar failure unknown hai to model recommendation invent karne ke bajaye manual assessment aati hai. Customer ke actual payment karne aur provider ke full capture verify hone ke baad hi recovery record hoti hai.

### Teen candidate actions

| Action | Actual implementation | Important meaning |
| --- | --- | --- |
| `retry` | Fresh Razorpay Test order aur explicit checkout | Automatic debit ya saved-card charge nahi hota |
| `payment_link` | Fresh Test payment link | Link banana payment success nahi hai |
| `alt_method` | Test payment link jisme original failed method hide hota hai | Capture ka actual method bhi verify hota hai |

`manual_assessment` ek review recommendation hai, fourth automatic provider action nahi. Unsupported cause par operator ko action explicitly choose karna padta hai.

### Is project mein AI ka matlab

AI component logistic-regression probability model hai. Diagnosis rules, financial eligibility, scoring policy aur workflow transitions explicit Python logic hain. Is implementation mein LLM, RAG, MCP server, LangChain ya conversational coding agent nahi hai. Resume par "ML-assisted payment recovery" sabse accurate description hai.

### Kis business ke liye useful ho sakta hai

Recommended future pilot: ek small Indian online-course creator ya adult skill-training business jo one-time INR fees Razorpay se collect karta ho. Yeh suggested customer segment hai; abhi koi merchant onboarded ya demand validated nahi hai. Production subscription auto-debits, loans, debt collection aur enterprise multi-tenant billing current scope nahi hain.

## 02 Current verified status

### Evidence ka meaning

| Item | Verified state | Isse kya conclude kar sakte ho |
| --- | --- | --- |
| Fresh local regression run | 22 Nov 2026 ko **645 tests passed** | Current source par automated regression suite green hai |
| Test files | 50 `test_*.py` files | Suite services, API, UI aur concurrency cover karti hai; 645 independent live payments nahi |
| Offline walkthrough | Six isolated scenarios recorded aur regression suite mein exercised | Real service logic fake provider ke saath reproduce hota hai |
| Latest pre-handover code/documentation CI | `d744a87` successful | Head-specific GitHub validation passed; future commits ka apna result check karna |
| Local database | Schema revision `0003` | Three reviewed migrations applied hain |
| Local Test cases | Five cases: three recovered, one failed, one closed unrecovered | Yeh local snapshot hai, merchant population nahi |
| Test recovery amount | **Rs.1,497**, three recovered groups | Simulated Test Mode payment evidence; real revenue nahi |
| Model data | 2,000 synthetic contexts, 6,000 action rows | Real merchant training data available nahi |
| Merchant/live deployment | Not validated | Real ROI, business recovery rate aur production readiness claim nahi |

Fresh local test report: `var/handover_validation_20261122/tests.xml` (ignored private artifact). Complete command section 12 mein hai.

Verified CI links:

- https://github.com/Sneha-090/RecoverAI/actions/runs/42754022182 (`d744a87`)
- https://github.com/Sneha-090/RecoverAI/actions/runs/42753754049 (`ff7a995`)
- https://github.com/Sneha-090/RecoverAI/actions/runs/42752191261 (`387d5e8`)

### Actual hosted verification ka conclusion

Do earlier Test Mode recovery captures verify hue the. Latest completed alternate-method flow mein original netbanking failure hua, ek explicitly approved retry fail hua, failure ko verified review mein return kiya gaya, aur separately approved alternate link card se paid hua. Full amount, INR currency, exact execution aur captured alternate method verify karke reviewed settlement hua. Signed capture inbox event processed hua. Repeat replay check ne extra resource/outcome nahi banaya.

Uske baad ek **additional fresh retry capture** test attempt hua. Original mock Failure confirm hua, lekin provider GET connection resets aur held-state handling ke issues mile. Read retry handling aur narrow reviewed resumption fix/test kiye gaye. Fresh retry order par final capture complete nahi hua; zero paid aur zero attempts verify hone par unused local case ko `operator_stop` se `closed_unrecovered` kiya gaya. **Is fresh retry capture ko successful mat bolna.** External order cancellation ya refund issue nahi hua.

Owner ko same payment instructions repeat karwana explicitly stop kiya gaya. Future agent resume/demo ke liye wahi manual loop restart na kare. Automated regressions aur existing recorded evidence default hain. Detailed historical record: `TEST_MODE_VERIFICATION.md`.

### Runtime ko current samajhne ki galti mat karna

Stored test results aur DB snapshot ka matlab yeh nahi ki API/dashboard/tunnel abhi live hain. Runtime state alag se check hoti hai. Is handover task ne services/tunnel start nahi kiye, koi provider payment create nahi kiya aur koi capture repeat nahi kiya.

## 03 Architecture aur stack

### System ko blocks mein dekho

```text
Razorpay Test Mode
    | signed payment.failed / payment.captured event
    v
Webhook-only gateway on 127.0.0.1:8002
    | body limit + HMAC verification
    v
Minimal durable inbox + exclusive event claim
    v
Ingestion -> Diagnosis -> Eligibility -> ML probabilities -> Policy
                                          |                  |
                                 unsupported context      auto or review
                                          |                  |
                                          +---- Human review-+
                                                             v
                          Durable recovery intent BEFORE provider creation
                                                             v
                         Saved order/link + attributable RecoveryExecution
                                                             v
                    Provider check -> ExecutionOutcome -> Case status + audit

SQLite <---- private API on 8001 <---- operator dashboard on 8501
   ^
   +---- replay worker / review-deadline worker / pending-outcome worker
```

### Local listeners

| Surface | Port | Role | Exposure rule |
| --- | --- | --- | --- |
| Private FastAPI API | 8001 | Operator endpoints, prediction, checkout config, readiness | Local/private only |
| Webhook gateway | 8002 | Signed webhook endpoint | Sirf isi port ko approved tunnel target banana |
| Streamlit dashboard | 8501 | Login, cases, reviews, audit, benchmark | Local/private only |
| Workers | No public listener | Replay, deadline maintenance, outcome polling | Same DB/config use karein |

`app/config.py` aur `.env.example` mein historical default API port 8000 ho sakta hai. Current supervised workflow 8001 use karta hai; supervisor child environment mein correct API URL deta hai. Manual setup mein `API_BASE_URL=http://127.0.0.1:8001` explicitly set karo. Kisi unrelated service on 8000 ko stop mat karo.

### Stack aur kyun use hua

Installed-version snapshot, 22 Nov 2026. Yeh latest-version recommendations nahi; current tested environment ki inventory hai.

| Technology | Installed version | Project mein role aur reason |
| --- | --- | --- |
| Python | 3.13.2, supported series 3.13 | Services, model pipeline, workers aur automation ek language mein |
| FastAPI | 0.162.0 | Typed HTTP API, validation, dependencies, middleware |
| Uvicorn | 0.54.0 | ASGI server jo FastAPI app run karta hai |
| Pydantic | 2.14.2 | Input constraints, types, invalid values reject karna |
| pydantic-settings | 2.16.2 | Environment/config loading |
| SQLAlchemy | 2.1.6 | ORM models, sessions, queries aur transactions |
| SQLite | Python-linked library | Local relational persistence; separate DB server setup nahi |
| Alembic | 1.20.1 | Versioned schema migrations |
| scikit-learn | 1.9.0 | Feature preprocessing, logistic regression, grouped evaluation |
| pandas | 3.1.0 | Feature frames, synthetic CSV, reports |
| NumPy | 2.5.4 | Numeric work, synthetic generation, metrics/bootstrap support |
| joblib | 1.6.0 | Trained estimator save/load |
| Razorpay Python SDK | 2.0.1 | Test orders, links, payment/order retrieval |
| requests | 2.34.2 | Bounded provider HTTP transport |
| Streamlit | 1.66.1 | Operator UI without building a separate React frontend |
| pytest | 9.2.0 | Automated service/API/UI/concurrency tests |
| Git and GitHub Actions | Repository + workflow | Version history, automated validation, evidence artifacts |
| psutil | Locked runtime dependency | Process identity, descendants aur owned supervision |
| ngrok | Existing local CLI, not core Python library | Approved Test webhook routing when actual provider testing is needed |

React, Node.js, MongoDB, ChromaDB, Docker, Kubernetes, Redis, Celery, PostgreSQL aur cloud deployment ko current implemented stack mein add mat karna. Kuch future options ho sakte hain, lekin abhi implemented feature claims nahi.

## 04 Payment se recovery tak actual flow

### Normal failed-payment workflow

1. Gateway raw body size bound karta hai: maximum **256 KiB**.
2. Exact raw bytes par HMAC-SHA256 signature verify hoti hai. Invalid signature reject hoti hai.
3. Event ID aur minimal correlation data durable inbox mein save hote hain.
4. Database claim ek processor ko ownership deta hai; duplicate request financial work dobara start nahi kar sakti.
5. Fresh provider payment data fetch hota hai. Webhook ke amount ko blind trust nahi kiya jata.
6. Known original order ka one permanent recovery owner bind hota hai.
7. Original order/history check hota hai: captured, partial, refunded, authorized/pending ya inconsistent evidence par new collection block hoti hai.
8. Rule-based diagnosis **specific provider error reason** use karti hai. Broad `BAD_REQUEST_ERROR` ko bank decline assume nahi karte.
9. Case-wide eligibility check hota hai. Unsupported cause/range par manual assessment aati hai.
10. Supported context ke liye three action probabilities, scores aur reasons record hote hain.
11. Policy auto action, human review ya skip return karti hai.
12. Execution ke pehle durable intent save hota hai; phir exactly one selected provider creation request hoti hai.
13. Issued resource ID action/audit/amount/currency se bind hota hai. Claim `awaiting_outcome` mein jata hai.
14. Capture event/poll/review ke through fresh provider evidence check hoti hai.
15. Verified full capture par exact execution ko success milti hai aur case `recovered` hota hai.

### Unknown failure ka flow

`payment_failed` generic reason hai. Isse actual bank/network cause establish nahi hota. Current model sirf four trained causes cover karta hai. Unknown cause par `manual_assessment` dikhega aur operator untried eligible action choose karega. Model se artificial high-confidence probability invent nahi hoti.

### Original checkout baad mein pay ho jaye

Original order ka verified success `paid_original` hota hai. Follow-up stop hota hai, pending reviews expire ho sakti hain, aur is natural/original success ko recovery-resource revenue credit nahi milta. Agar original aur recovery dono paid milen to duplicate investigation hoti hai; automatic refund nahi.

### Late capture aur early event

- **Late capture:** pehle failed maana gaya older execution baad mein captured ho sakta hai. Exact execution ki failed observation success mein upgrade ho sakti hai; newer action ke outcome ko overwrite nahi karte.
- **Early capture:** provider event creation response save hone se pehle aa sakta hai. Inbox wait/replay karta hai; intent/resource attribution milne par settle hota hai.
- **Response lost:** provider ne order create kiya ho, par app response na dekh payi ho. Is uncertainty mein POST repeat nahi karte. Existing resource ko verify/bind karne ka reconciliation path use hota hai.

### Human control ka meaning

Review automatic debit approve nahi karti. Approval ek eligible recovery resource create kar sakti hai. Customer ko actual payment explicitly complete karna hota hai. Operator stop local further work rokta hai; already-open/shared external checkout ko atomically recall nahi kar sakta.

## 05 Decision aur scoring ko samjho

Formula:

```text
Estimated net value(action) = predicted probability(action) * amount - configured action cost
```

Illustrative teaching example, measured project result nahi:

| Action | Assumed probability | Rs.499 par expected gross | Assumed cost | Score |
| --- | --- | --- | --- | --- |
| retry | 0.45 | 224.55 | 5 | 219.55 |
| payment_link | 0.60 | 299.40 | 15 | 284.40 |
| alt_method | 0.55 | 274.45 | 10 | 264.45 |

Agar sab eligible hon to example mein payment_link top score hai. Lekin eligibility score se pehle apply hoti hai. Highest score wala action already executed, stopped ya unsupported ho to select nahi hota.

Default business policy (`app/config.py`; local env override kar sakta hai):

| Setting | Default | Meaning |
| --- | --- | --- |
| Recovery window | 14 days | Case itna old ho to new recovery block |
| Max executed retries | 3 | Upper bound; current one-execution-per-action rule stricter ho sakti hai |
| Retry cooling-off | 4 hours | Executed retries ke timestamps use hote hain |
| Review deadline | 24 hours | Deadline expiry new payment authorize nahi karti |
| Score floor | 0 | Non-positive best value par skip |
| Near-tie margin | 2% of payment amount | Top two net values close hon to review |
| High-value review | Amount above Rs.50,000 | Human review guard; model support limits separately apply |
| Costs | retry 5, link 15, alternate 10 | Modeled business assumptions, actual Razorpay fee schedule nahi |

2% margin **statistical model confidence** nahi. Rs.499 ka 2% Rs.9.98 hai; eligible top-two scores ka difference iske andar ho to review hoti hai. High-value guard ki unit rupees hai. Numeric training support Rs.10,000 tak hai, isliye app mein koi input pehle out-of-range manual assessment mein ja sakta hai; thresholds ko guaranteed branch order mat samajhna.

Already-tried actions ka meaning **executed actions** hai. Pending/manual recommendations attempt budget consume nahi karti. `decision_type=auto` database category human-approved executions ko bhi store karti hai; audit/reason se authorization source distinguish hota hai. "auto row" ka matlab hamesha "without human approval" nahi.

### Action distribution mein bias kaise investigate karna hai

Agar ek recovery action zyada select hua to sirf count dekhkar bias conclude nahi karte. Failure causes, amounts, method availability, excluded/tried actions, eligible candidates, policy costs aur review deferrals compare karo. Dashboard ka Action Distribution view first decisions, executions aur human approvals alag dikhata hai, source/cause filters ke saath. Same-case repeated records ko independent customers mat count karo.

Real action effectiveness ke liye actual outcome data aur appropriate comparison chahiye. Unchosen action ka result real world mein unknown hota hai; usko failure label banana galat hai.

## 06 ML training aur honest evaluation

### Dataset shape

`data/generate_synthetic_data.py` 2,000 base contexts generate karta hai. Har context ke three action rows hain, isliye `data/synthetic_payments.csv` mein 6,000 rows hain.

Columns: `customer_id`, `amount`, `cause`, `attempts`, `days_since_failure`, `past_rate`, `action_type`, `recovered`.

Synthetic causes: `network_error`, `insufficient_funds`, `bank_declined`, `card_declined`. Generator ke synthetic customer IDs grouping keys hain; real merchant customer population nahi.

### Feature pipeline

Numeric features: amount, executed attempts, days since failure, past rate. Categorical features: cause, action type, aur engineered `cause_action` interaction. Interaction example: `network_error__retry`.

`ColumnTransformer` numeric data ko `StandardScaler` deta hai aur categorical data ko `OneHotEncoder`. Dono classifier ke saath `Pipeline` mein hain. Training preprocessing ko training partition se fit kiya jata hai; inference mein same transformations reuse hote hain.

### Leakage avoid kaise hua

Same context ke three action rows ko random row split karte to related information train aur test dono mein aa sakti thi. `GroupShuffleSplit` synthetic customer/context ID use karta hai.

- Outer training: 1,600 contexts / 4,800 rows.
- Outer test: 400 contexts / 1,200 rows.
- Context overlap: zero.
- Inner selection within training: 1,280 fit contexts / 320 validation contexts.
- Four predefined candidates: logistic regression C=0.1, C=1, C=10, aur random forest.
- Selection: validation log loss, then Brier score, then stable name.
- Selected: `logistic_c01`; outer training par refit. Saved estimator outer training partition par fitted hai, poore 6,000 rows par nahi.
- Outer test candidate selection/tuning ka input nahi tha. Existing synthetic test results ab inspect ho chuke hain; yeh future blind merchant audit nahi hain.

### Recorded classifier metrics

`ML/evaluation.json` ki recorded evaluation 7 Nov 2026 ki hai. 22 Nov handover validation ne existing reports/source verify kiye; naya training run claim nahi.

| Metric | Recorded value | Meaning |
| --- | --- | --- |
| Accuracy | 76.17% | Threshold 0.5 par total labels correct fraction |
| Prior baseline accuracy | 73.75% | Imbalanced dataset mein simple majority-like result bhi high lag sakta hai |
| ROC-AUC | 0.7591 | Positive-vs-negative ranking quality on synthetic test rows |
| Prior baseline ROC-AUC | 0.500 | Constant-score baseline ranking |
| Precision | 62.61% | Predicted positives mein true positives |
| Recall | 22.86% | Actual positives mein threshold par caught positives |
| F1 | 0.3349 | Precision/recall balance at threshold |
| Brier score | 0.1625 | Probability error; lower better under same evaluation |
| Log loss | 0.4925 | Probabilistic error including confident mistakes |

AUC 0.759 ka matlab 75.9% payments recovered nahi. Accuracy model/business quality ka complete summary nahi, especially low recall ke saath. Policy probability estimates ko expected-value ranking mein use karti hai; classifier threshold aur policy action selection same cheez nahi.

### Input coverage guards

Recorded training ranges: amount Rs.100-10,000; attempts 0-3; days 0-14; past rate 0-1. Cause/action interaction support bhi check hoti hai. Unsupported numeric/categorical context par manual assessment hoti hai. Encoder ka `handle_unknown=ignore` alone enough safety nahi hota.

Customer history only other finalized, evidenced cases se nikalti hai. Current/pending/future case ko feature mein leak nahi karte. Identity/history missing ho to explicit default past rate 0.5 aur default-use flag store hota hai. Feature snapshot audit mein save hota hai, contacts nahi.

### Policy benchmark ka honest result

`reports/POLICY_BENCHMARK.md` four policies compare karta hai: blanket retry, cause rules, ML value ranking, guarded ML. Har policy ko same held-out contexts, fixed synthetic potential outcomes, costs aur one-intervention budget milta hai. Baseline outcomes evaluated model ki probabilities se generate nahi hote.

Primary split mein ML value ranking minus cause rules ka net difference **Rs.-735.83** hai; paired 95% bootstrap interval **[-12,971.92, 13,456.14]**. Interval zero cross karta hai: clear ML advantage establish nahi hua. Guarded policy ke deferred reviews unresolved hain; unko successful recovery assume nahi karte.

Five fixed split results hain, lekin repeated test sets overlap karte hain. Unke customers ko pool karke artificial sample size mat badhao. Synthetic labels real intervention effect, merchant ROI ya sequential retry uplift establish nahi karte. Real data ke bina cosmetic retraining se business proof nahi milta.

## 07 Database aur state machines

### Teen identities ko mix mat karo

1. **Original order:** merchant ki ek provider order reference.
2. **Payment attempt:** us order ke against ek individual payment try.
3. **Recovery execution:** RecoverAI ne jo separate retry order/link issue kiya, uski action/resource binding.

Same original order ke multiple failed payment IDs ho sakte hain. Unko independent fee obligations maanoge to duplicate collection ka risk hai. Isi liye canonical original-order ownership add hui. Alag provider orders ek hi merchant invoice represent kar sakte hain; current system unko automatically merge nahi karta.

### Main tables

| Model or table | Kya store hota hai | Design reason |
| --- | --- | --- |
| `Payment` / payments | Original attempt, order, provider state, case status, stop flags | Provider charge aur recovery case separate concepts |
| `Diagnosis` | Cause aur diagnosis time | Rule output explainable rahe |
| `MLPrediction` | Per-action probability and time | Recommendation audit ho sake |
| `RecoveryScore` | Score, cost, eligibility, reason | Candidate comparison record ho |
| `Action` | Recommendation or executed action | Suggested action ko real execution se distinguish kare |
| `Outcome` | Observed result | Outcome ko payment/action context mile |
| `AuditLog` | Events, reasons, minimal payload | Operator/system history reconstruct ho |
| `Customer` | Optional provider customer reference | Known identity ke cases link ho sakein |
| `WebhookReceipt` | Exclusive event claim/state | Same event competing processors se protect ho |
| `WebhookInbox` | Minimal verified event, attempts, next time | Early/retryable event durable rahe |
| `RecoveryReservation` | Case claim, owner token, phase | One financial workflow at a time |
| `RecoveryIntent` | Pre-request intent, provider reference, binding | Lost response ko blind repeat na karna pade |
| `RecoveryExecution` | Action, audit, provider ID, expected paise/currency | Exact issued resource attributable ho |
| `ExecutionOutcome` | Unique execution-to-outcome binding | Duplicate result aur wrong-attempt settlement avoid ho |
| `OriginalOrderRecovery` | Permanent canonical owner per original order | Same obligation par independent collection na ho |

`RecoveryExecution.action_id` aur `.audit_id` unique hain. Provider type plus provider ID bhi unique binding hai. `ExecutionOutcome` ek execution ka single attributed outcome rakhta hai. Outcome failed se later verified success update ho sakta hai; har duplicate event se naya success row nahi banta.

### Provider state versus case status

`Payment.razorpay_state` original payment ka latest provider state hai. `Payment.status` app recovery case ka state hai. Original payment failed reh sakta hai jab case separate recovery payment se recovered ho jaye.

Important case statuses:

- `failed`: original failure ka open recovery case.
- `recovered`: exact recovery execution ki full success verified.
- `paid_original`: original checkout se fee paid; recovery credit nahi.
- `closed_unrecovered`: case closed without verified recovery, for example explicit stop/expiry.
- `needs_reconciliation`: inconsistent/duplicate case evidence investigation mein.

Reservation state case status se alag hai. Case `failed` hote hue reservation `needs_reconciliation` ho sakta hai. UI/debug mein dono read karo.

### Reservation lifecycle

```text
No claim -> processing
processing -> awaiting_outcome     resource saved, customer payment pending
processing -> pending_review       operator choice/approval required
processing -> needs_reconciliation outcome uncertain
awaiting_outcome -> processing     observe exact existing resource
pending_review -> processing       approve or expire under exclusive claim
needs_reconciliation -> processing explicit reviewed operation
processing -> no claim            completed or safe terminal path
```

Claim ownership database conditional updates/uniqueness se enforced hoti hai. Python variable ya local thread lock multiple processes ke liye enough nahi. "Check row absent, then create" mein race ho sakti hai; database must decide who owns the operation.

Old timestamp dekhkar `processing` delete karna unsafe hai. Provider request accept ho chuki ho sakti hai. General claim-expiry/crash recovery current application mein solved nahi hai.

### Intent before request kyun

Sequence hai: intent durable save -> provider POST -> response/resource store -> execution bind. Agar POST ke baad network toot jaye to intent present rahega. Provider notes mein intent reference correlation mein help karti hai. Database aur external API ek atomic transaction nahi hain, isliye local transaction se external exactly-once charge guarantee nahi banti.

### Reviewed controls

- **Verified success settlement:** existing execution ya matching intent/resource freshly verify karo, phir exact outcome settle karo.
- **Verified failure to review:** all known resources freshly failed hon, original order open ho, unresolved intent na ho, latest execution selected ho; then manual review create ho sakti hai. Koi new checkout automatically nahi.
- **Resume unattempted retry:** exactly one attributed first retry order, status created, zero paid, full due, zero attempts, independent empty payment list, open original order, no outcome/review/unresolved intent/stop. Sirf observation `awaiting_outcome` mein return hoti hai. Active, partial/paid/attempted ya ambiguous cases blocked rehte hain.
- **Operator stop:** opt-out, merchant cancellation, fraud concern ya operator stop persist hota hai; automatic resume nahi.
- **Old unpaid link cleanup:** eligible closed case ka exact unpaid Test link verify karke explicit cancel. Paid/partial links aur orders automatic cancellation scope mein nahi.

### Money handling

Provider expectations integer paise mein hain. `Decimal(str(amount))` se exact conversion hota hai; Rs.19.90 = 1,990 paise. Float multiplication ko accounting conversion ke liye trust nahi karte. Payment rupee display column abhi Float hai, isliye ise complete accounting ledger mat bolo. Future ledger/partial settlement design ko carefully migrate karna hoga.

## 08 Kya improve kiya aur kyun

"Earlier risk" ka matlab har row mein confirmed real-money incident nahi; yeh design risks aur earlier limitations hain.

| Area | Earlier risk or limitation | Kya change hua aur kyun |
| --- | --- | --- |
| Generic failures | Broad error ko specific cause assume karna | Specific reason mapping; unknown cause manual assessment |
| Model coverage | Encoder unknown input silently accept kar sakta tha | Cause/action aur numeric-range guards |
| Data split | Related action rows train/test mein leak ho sakte the | Grouped split and disjoint inner selection |
| Evaluation | Accuracy alone weak evidence thi | Baseline, AUC, recall, Brier, log loss, calibration, hashes |
| Policy comparison | Model-generated baseline circular ho sakti thi | Fixed matched outcomes and shared pure selector |
| Duplicate events | Concurrent requests extra resources issue kar sakte the | Durable event/case claims and uniqueness tests |
| Same original order | Failed attempts independent recovery create kar sakte the | One permanent canonical recovery owner |
| Natural success | Original checkout ko recovery credit mil sakta tha | `paid_original`, fresh order/history verification |
| Lost response | Provider POST repeat se duplicate risk | Intent-before-request and reviewed reconciliation |
| Early or late events | Missing/wrong execution attribution | Inbox replay and exact execution/outcome IDs |
| Human review | Recommendation and execution confuse ho sakte the | Executed-only budgets, explicit override, exact audit |
| Deadlines | Approval versus expiry race | Same case claim and transactional expiry |
| Money | Binary float paise error | Shared Decimal conversion and tests |
| Security | Operator surface expose hone ka risk | Auth, salted password hashes, session expiry, split gateway |
| Provider mode | Env key swap se unintended live request | Transport and creation boundary Test-only guards |
| Request size | Unbounded public webhook input | 256 KiB streamed limit, malformed signature/JSON checks |
| Operator stops | Opt-out/risk state lost ho sakta tha | Persistent stop fields across known same-order attempts |
| Reporting | Attempts ko orders/revenue ki tarah double count | Grouped headline totals and source-separated distributions |
| Old links | Recovered case ka external link open reh sakta tha | Reviewed unpaid-link cleanup; remaining external race disclosed |
| Local operation | Many unmanaged terminals/processes | Six-service supervisor, PID identity and restart budgets |
| Schema changes | Unknown legacy schema adopt karne ka risk | Frozen baseline, Alembic revisions and explicit adoption |
| Backup confidence | Backup file restore proof nahi thi | Isolated restore, migration, record/source digest checks |
| Browser auth | In-app HTTP Basic checkout issue | Existing authenticated dashboard session mein verified checkout |
| GET resets | Safe read failure unnecessarily held ho sakti thi | GET retry once; pre-ingestion failure typed/replayable |
| Write uncertainty | Blanket retry creation repeat kar sakta tha | POST/PUT/PATCH/DELETE transport retries disabled |
| Repetitive testing | Fresh retry exercise repeated user steps maang rahi thi | Unused case stopped; capture unverified; resume scope frozen |

Selected commit references:

- `76c448b`: original-order recovery owner.
- `18a794b`: original success without recovery credit.
- `1df2487`: Test-only transport/creation boundaries.
- `a875636`: order-level totals.
- `707d501`: persistent operator stops.
- `721e9a2`: isolated backup restore.
- `9267eec`: webhook body/signature limits.
- `55f6951`: dashboard-session checkout.
- `3a1c6c8`: verified failed execution to review.
- `079440b`: actual approved action and exact audit.
- `a79cc22`: completed alternate Test capture evidence.
- `387d5e8`: bounded GET retries without repeating writes.
- `ff7a995`: reviewed resume of never-attempted retry.
- `d744a87`: frozen resume scope and interview guide.

Commit URL pattern: `https://github.com/Sneha-090/RecoverAI/commit/COMMIT_SHA`. `git log` actual history ka source hai. Arbitrary tiny changes sirf commit count ke liye nahi; each coherent committed state usable/tested rahe.

## 09 Kya complete hai aur kya pending

### Current resume and demonstration scope

**Implemented and regression-tested:** ingestion, diagnosis, inference, value ranking, review, exact attribution, original-order ownership, natural-success exclusion, durable claims, intent-before-request, early-event replay, expiry, polling, reviewed reconciliation/resumption, stops, authenticated UI/API, split gateway, hash-locked setup, migrations, restore verification and local supervision.

**Actually captured in provider Test Mode:** three recovery groups, including latest alternate-method full card capture and reviewed settlement. **Simulation:** six isolated scenarios. **Not completed:** additional fresh hosted retry capture. Browser-control problems occurred during testing; fresh acceptance is deferred. Completed service/UI tests do not turn an uncompleted hosted capture into a success.

### Future merchant phase

| Priority | Remaining work | Acceptance ka example | Resume wrap-up ke liye required now |
| --- | --- | --- | --- |
| P0 before live | Merchant, written scope, approved outcomes | Shadow-mode need/volume validation and named operator | No |
| P0 | Invoice mapping across separate orders | Same fee ke two orders duplicate recovery na create karein | No; limitation explain karo |
| P0 | Consent, contact, refund/dispute/partial handling | Merchant-approved audited procedure | No |
| P0 | Reviewed HTTPS hosting and rate limits | Private operator surface and bounded public ingress | No |
| P0 | Job-progress alerts, hosted backup/recovery | Stuck job detect ho; independent restore drill | No |
| P1 | Fresh hosted retry success if explicitly resumed | One planned test, supported browser, exact verification | Deferred |
| P1 | Real-data calibration/policy validation | Leakage-safe comparison, sample size and uncertainty | Synthetic uplift claim nahi |
| P1 | Full historical model-version lineage | Every historical decision immutable model se traceable | Future work |
| P1 before scale | Async path profiling and I/O offload or queue review | Blocking provider/DB calls event loop ko saturate na karein; measured load results | Not benchmarked |
| P1 | Reviewed general crash/lease recovery | No blind expiry of uncertain financial operation | Not implemented |
| P2 if needed | PostgreSQL, queue, RBAC, tenant isolation | Load/integration tests and reviewed migration | Future options |

Maintenance backlog: dependency deprecation warnings, operational diagnostics, optional date filters/pagination, log retention and cleanup of old manual demo scripts. Inko product impact ke basis par prioritize karo, test/commit counts ke basis par nahi.

### Original question ka direct answer

**Tested resume/demo application ke core scope mein implementation complete enough hai aur freeze karna reasonable hai. Real-money production business product complete nahi hai.** Ab project ko samajhna, explain karna aur evidence present karna most useful hai. Real pilot ke bina extra AI/agent features missing business validation solve nahi karenge.

## 10 Code map aur reading order

All paths repository root ke relative hain.

| Path | Kya milega | Kab padho |
| --- | --- | --- |
| `README.md`, `ARCHITECTURE.md` | Setup/evidence and architecture | First |
| `dashboard.py` | Eight operator tabs and queries | UI and reporting |
| `app/main.py` | Private routes, validation, error handling | HTTP/API |
| `app/webhook_gateway.py` | Restricted public app | Exposure boundary |
| `app/api/webhooks.py` | Signature/intake, matching and processing | Event flow |
| `app/config.py`, `.env.example` | Config names/defaults | Private local setup |
| `app/db/session.py`, `app/models/models.py` | Engine, sessions, tables and constraints | ORM/data model |
| `app/services/ingestion.py` | Fresh provider fetch/upsert | Payment input |
| `app/services/diagnosis.py` | Specific reason mapping | Diagnosis |
| `app/services/eligibility.py` | Case/retry guards | Window/budget/cooling-off |
| `app/services/original_orders.py` | Canonical owner and original success | Duplicate obligation protection |
| `app/services/ml_service.py` | Model loading, coverage, features | Inference |
| `app/services/customer_history.py` | Evidence-based past rate | Leakage and defaults |
| `app/services/policy.py` | Pure action selector | Decision entry point |
| `app/services/decision.py` | DB/model orchestration and explanations | Complete decision |
| `app/services/execution.py` | Execution, outcomes and approval | Workflow core |
| `app/services/reservations.py` | Durable ownership | Concurrency |
| `app/services/execution_records.py` | Resource/action/audit binding | Attribution |
| `app/services/webhook_inbox.py`, `app/services/webhook_replay.py` | Minimal storage and bounded replay | Event ordering |
| `app/services/reconciliation.py` | Success, failure review, unattempted resume | Explicit recovery controls |
| `app/services/recovery_stops.py` | Persistent stops | Opt-out/risk |
| `app/services/checkout_maintenance.py` | Unpaid old link review | Resource lifecycle |
| `app/services/operator_checkout.py`, `app/ui/operator_checkout.py` | Verified config and Test frame | Checkout |
| `app/services/razorpay_client.py`, `app/services/order_service.py` | Mode guards, retries and provider creation | External API contract |
| `app/services/money.py` | Whole-paise conversion | Money correctness |
| `app/services/passwords.py`, `app/services/operator_auth.py`, `app/api/auth.py` | Password hashes and Basic auth | Authentication |
| `app/ui/operator_login.py` | Dashboard session guard | UI authentication |
| `app/services/order_reporting.py`, `app/services/action_reporting.py` | Group totals and distributions | Units and samples |
| `app/services/benchmark_reporting.py` | Stale-evidence checks | Honest metric display |
| `app/services/readiness.py`, `app/services/local_runtime.py` | Readiness and supervision | Operations |
| `ML/train_model.py` | Pipeline, splits, selection | Training |
| `ML/evaluation.json`, `ML/recovery_model.joblib` | Metrics and fitted estimator | Evidence/artifact |
| `ML/benchmark_policies.py` | Matched policy evaluation | ML versus business policy |
| `data/generate_synthetic_data.py`, `data/synthetic_payments.csv` | Synthetic recipe and rows | Dataset meaning |
| `scripts/offline_demo.py`, `scripts/demo_provider.py`, `scripts/render_demo_html.py` | Isolated scenarios and replay | Safe demo |
| `scripts/run_local.py` | Supervisor CLI | Daily operation |
| `scripts/replay_webhooks.py`, `scripts/maintain_reviews.py`, `scripts/poll_outcomes.py` | Three workers | Background processing |
| `scripts/verify_backup.py`, `app/db/init_db.py`, `app/db/schema.py` | Restore/migrations/readiness | Maintenance |
| `migrations/versions/` | Revisions 0001-0003 | Schema history |
| `.github/workflows/tests.yml` | CI validation steps | Reproducibility |
| `requirements.in`, `requirements.lock`, `requirements-dev.txt` | Source requirements and locks | Setup |
| `tests/` | Combined 645-case suite | Learn expected behavior |

Reading order: `policy.py` -> `diagnosis.py` -> `eligibility.py` -> models -> `decision.py` -> `execution.py` -> webhooks/reservations/inbox -> `original_orders.py` -> reconciliation -> tests -> UI -> operations. Saara repo ek sitting mein ratna zaroori nahi.

### Legacy utilities par caution

`scripts/ingest_payment.py`, `scripts/fetch_payment.py`, `scripts/create_order.py`, `scripts/add_demo_human_review_cases.py`, `scripts/add_demo_halted_case.py` aur `scripts/run_batch_simulation.py` older/manual utilities hain. Kuch hard-coded provider IDs ya configured DB use karte hain. Historical batch outcome simulator matched benchmark ka replacement nahi. Active DB mein demo rows casually insert mat karo. Safe demonstration entry point `scripts.offline_demo` hai; `scripts.live_demo` safe alias hai.

## 11 Windows setup aur daily operation

### Existing clone pehle identify karo

Authoritative checkout `D:\RecoverAI` hai. Old `C:\...\OneDrive\Documents\ChatGPT\recoverAI` chat workspace ho sakta hai, lekin active D source ka replacement nahi. C space aur OneDrive access issues ke baad work D par continue hua tha. Dono clones/workers ko same SQLite DB ke against parallel mat chalao.

**Windows CMD, existing installation:**

```bat
cd /d D:\RecoverAI
git status --short
git log -5 --oneline
.venv\Scripts\python.exe --version
```

Git ownership error par verified path ke liye per-command form available hai:

```bat
git -c safe.directory=D:/RecoverAI status --short
```

Sab directories ko globally trust mat karo. Handover start par unrelated `tests/test_webhook_gateway.py` modified status aur untracked `python` file thi. Yeh task unko stage/delete/overwrite nahi karta. Future agent actual diff inspect kare, clean-tree assumption na banaye.

### Sirf fresh installation ya new machine par

Existing D installation ko download/clone/venv creation repeat karne ki zaroorat nahi. Fresh path par Python 3.13 available ho tab:

```bat
cd /d D:\
git clone https://github.com/Sneha-090/RecoverAI.git
cd /d D:\RecoverAI
python -m venv .venv
mkdir .venv\tmp
set TEMP=%CD%\.venv\tmp
set TMP=%TEMP%
set PYTHONDONTWRITEBYTECODE=1
.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements-dev.txt
```

Runtime-only lock `requirements.txt` hai. Development/test installation `requirements-dev.txt` hai. Hash locks versions/distributions constrain karte hain; blind `pip install --upgrade` mat run karo. Project artifacts/downloads/temp D par route karo. Windows/tools ke apne system files ka location isse change nahi hota.

**PowerShell equivalent environment setup:**

```powershell
Set-Location D:\RecoverAI
$env:TEMP='D:\RecoverAI\.venv\tmp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements-dev.txt
```

CMD ka `set VAR=value` aur `cd /d` PowerShell mein same syntax nahi hai. Above examples shell labels ke hisaab se use karo. Full venv Python path activation confusion avoid karta hai.

### Private Test Mode configuration

Offline tests/demo ko real Razorpay keys nahi chahiye. Actual Test provider operation ke liye existing `.env` preserve karo; only absent ho to template copy karo:

```bat
if not exist .env copy .env.example .env
```

Locally configure names, real values is file mein nahi hain:

```dotenv
RAZORPAY_KEY_ID=your_test_key_id
RAZORPAY_KEY_SECRET=your_private_test_secret
RAZORPAY_WEBHOOK_SECRET=your_private_test_webhook_secret
DATABASE_URL=sqlite:///./recoverai.db
OPERATOR_USERNAME=your_local_operator_name
API_BASE_URL=http://127.0.0.1:8001
ALLOWED_ORIGINS=[]
```

Yeh placeholders valid credentials nahi. Actual Test key ID `rzp_test_` prefix use karti hai. Live key paste karna production upgrade nahi: transport non-Test configuration refuse karta hai. `.env` GitHub par commit mat karo.

Password locally reset/set karo:

```bat
.venv\Scripts\python.exe -m scripts.reset_operator_password
```

Password 12-1024 characters aur confirmation matching honi chahiye; hidden typing normal hai. Plaintext password store nahi hota. Historical username `sneha` tha; future private config different ho sakti hai. Password/hash chat mein nahi. Credential rotation ke baad operator processes ko new config load karne ke liye restart karna hota hai.

### DB initialize ya migrate kaise karein

App/workers stop karke hi schema maintenance karo. Existing DB delete karke problem solve mat karo.

```bat
.venv\Scripts\python.exe -m scripts.run_local --stop
.venv\Scripts\python.exe -m scripts.run_local --status
.venv\Scripts\python.exe -m app.db.init_db --status
```

Supervisor absent/stopped ho to bhi independent manual processes verify karo. Fresh empty DB ke liye:

```bat
.venv\Scripts\python.exe -m app.db.init_db
```

Existing unversioned DB ke liye **sirf reviewed baseline adoption**:

```bat
.venv\Scripts\python.exe -m app.db.init_db --adopt-legacy
```

Unknown schema/revision, failed integrity/FK ya baseline mismatch par stop. Random stamp/lock deletion mat karo. Revision 0001 frozen existing schema hai; 0002 canonical order ownership; 0003 persistent operator stops. Verified local backup `var/backups` mein retained hota hai. Same-drive copy off-device disaster backup nahi.

### Daily supervised start and stop

```bat
.venv\Scripts\python.exe -m scripts.run_local --check
.venv\Scripts\python.exe -m scripts.run_local
```

Terminal alive rakho. Another terminal se:

```bat
cd /d D:\RecoverAI
.venv\Scripts\python.exe -m scripts.run_local --status
.venv\Scripts\python.exe -m scripts.run_local --stop
```

- Dashboard: http://127.0.0.1:8501/
- Private readiness: http://127.0.0.1:8001/ready
- Private liveness: http://127.0.0.1:8001/health

Readiness schema, model artifact aur auth setup check karti hai; Razorpay credentials ka network validation nahi. Worker monitoring process liveness hai, completed-job heartbeat nahi. Supervisor startup service/OS registration nahi hai.

### Manual mode only as alternative

Supervisor running ho to manual duplicate processes mat start karo. Deliberate manual mode mein **separate terminals**:

```bat
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
.venv\Scripts\python.exe -m uvicorn app.webhook_gateway:app --host 127.0.0.1 --port 8002
.venv\Scripts\python.exe -m streamlit run dashboard.py --server.address 127.0.0.1 --server.port 8501
.venv\Scripts\python.exe -m scripts.replay_webhooks --watch --interval 15
.venv\Scripts\python.exe -m scripts.maintain_reviews --watch --interval 60
.venv\Scripts\python.exe -m scripts.poll_outcomes --watch --interval 60
```

Ek terminal mein sequential paste se six services simultaneously start nahi hoti; first foreground process terminal occupy karega. Default recommendation supervisor hai. All workers same config/database use karein.

### Actual webhook tunnel kab chahiye

Normal learning/interview ke liye ngrok required nahi. Historical configured endpoint ko currently running assume mat karo. Actual provider testing explicitly resumed ho tab approved tunnel upstream **8002 only**. API 8001 ya dashboard 8501 expose mat karo. Ngrok authtoken private configuration hai, source code nahi. Existing executable reuse karo; wrong architecture download ya browser/antivirus warning bypass koi required project step nahi hai.

## 12 Offline demo aur checks

### Payment clicks ke bina safest demonstration

CMD:

```bat
cd /d D:\RecoverAI
set TEMP=%CD%\.venv\tmp
set TMP=%TEMP%
set PYTHONDONTWRITEBYTECODE=1
.venv\Scripts\python.exe -m scripts.offline_demo --output-dir var\learning\offline_demo --work-dir var\learning\offline_db
```

Output `var/learning/offline_demo/offline_demo.html`, JSON, Markdown aur unique SQLite fixture hai. Real `.env`/configured DB replace nahi hota. Fake provider aur external-network guard use hota hai; Windows asyncio ke local IPC ko allow kiya jata hai. HTML recorded trace replay karta hai, backend financial mutation trigger nahi karta. Already committed `reports/offline_demo.html` bhi browser mein directly read ho sakta hai.

Six scenarios: duplicate failure/pending/capture, human approval, lost response reconciliation, older retry late capture, review expiry, aur capture-before-persistence inbox replay.

### Full regression suite

PowerShell:

```powershell
Set-Location D:\RecoverAI
$env:TEMP='D:\RecoverAI\.venv\tmp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --disable-warnings
```

`tests/conftest.py` Test dummy keys aur in-memory default DB set karta hai; individual fixtures temporary DBs use karti hain. Live payments test suite ka requirement nahi.

Topic slices:

```bat
.venv\Scripts\python.exe -m pytest -q tests/test_diagnosis.py tests/test_decision.py tests/test_money.py
.venv\Scripts\python.exe -m pytest -q tests/test_original_orders.py tests/test_original_order_success.py tests/test_duplicate_execution.py
.venv\Scripts\python.exe -m pytest -q tests/test_reconciliation.py tests/test_failed_execution_review.py tests/test_unattempted_retry_review.py
.venv\Scripts\python.exe -m pytest -q tests/test_webhook_inbox.py tests/test_webhook_limits.py tests/test_provider_mode.py
.venv\Scripts\python.exe -m pytest -q tests/test_dashboard_login.py tests/test_dashboard_reconciliation.py
```

Suite wrong ID/amount/currency, late capture, partial payment, auth, competing workers, rollback, UI, migrations aur process ownership check karti hai. 645 pass ka matlab 100% coverage, load-test capacity, 645 users ya guaranteed correctness nahi.

### Training experiment without current model overwrite

```bat
.venv\Scripts\python.exe -m ML.train_model --model var\learning\recovery_model.joblib --report var\learning\evaluation.json
.venv\Scripts\python.exe -m ML.benchmark_policies --output-dir var\learning\policy_benchmark
```

Default training command tracked application artifact overwrite kar sakti hai; learning mein explicit ignored paths use karo. Dataset generator tracked CSV rewrite karta hai; deliberately isolated lab/branch par hi experiment karo. Current estimator replace hone par model/report hash pair aur readiness ka effect review karna padega.

### Read-only operations

```bat
.venv\Scripts\python.exe -m scripts.inspect_reservations
.venv\Scripts\python.exe -m scripts.replay_webhooks --list
.venv\Scripts\python.exe -m app.db.init_db --status
```

`replay_webhooks --event-id ...` list-only command nahi. Woh eligible saved event ko process kar sakta hai, although held/processing claims force nahi karta. Learning fixtures ko prefer karo.

### Isolated restore verification

Existing reviewed backup ki actual path se:

```bat
.venv\Scripts\python.exe -m scripts.verify_backup "D:\RecoverAI\var\backups\YOUR_EXISTING_BACKUP.sqlite" --output-root "D:\RecoverAI\var\learning\restore_checks"
```

Placeholder replace karna hoga. Command source read-only rakhti hai, unique restored copy migrate/check karti hai. Original record digests, source hash, integrity aur FK checks hote hain. Running DB overwrite nahi hota. Yeh **backup verify** karti hai; fresh consistent backup banane ya hosted disaster plan ka replacement nahi.

## 13 Troubleshooting aur operational rules

| Symptom | Investigation | Safe response |
| --- | --- | --- |
| No space left | C temp/cache ya target full | Project/venv/TEMP/TMP D par; pip no-cache; personal files blindly delete nahi |
| OneDrive OSError 22 | Sync/placeholder/file access possible | Verified local D clone; exact cause bina proof assert nahi |
| Could not resolve GitHub host | DNS/network | Connectivity check and later retry |
| cd path missing | Clone incomplete/wrong drive | Clone completion verify; CMD `cd /d D:\RecoverAI` |
| Only .env.example | Template expected | Locally create .env only if absent; existing preserve |
| Password reset failure | Length/mismatch/file access | Matching 12-1024 characters; no password/hash in chat |
| Checkout 401 | Operator auth required | Supported external browser or logged-in dashboard checkout |
| Checkout 503 | Bounded provider read unavailable | Existing ID retain; later Load order; no repeated Create order |
| Old 500/reset | Provider ConnectionError possible | Sanitized stage/category inspect; writes blindly repeat nahi |
| Checkout inactive/409 | Case held/stopped/paid/ineligible | Case, reservation, original order and execution inspect |
| Old processing claim | Owner alive ya side effect uncertain | Claim delete/expire nahi; deliberate review |
| needs_reconciliation | Mismatch/ambiguity/possible side effect | Existing resource verify, applicable reviewed control only |
| Duplicate webhook | Event redelivery normal ho sakti hai | Receipt/inbox inspect; extra resource expected nahi |
| Gateway ready/docs 404 | Restricted gateway expected | Private API readiness on 8001 check |
| Model artifact mismatch | Saved estimator/report pair changed | Correct reviewed pair restore/reproduce; readiness bypass nahi |
| Stale benchmark | Source/data/decision CSV changed | Regenerate/review evidence in isolated output |
| Port occupied | Owned service ya unrelated app | PID, creation time, command, cwd verify; random kill nahi |
| OTP/popup confusion | Mock payment vs phone-login flow | Real credentials/OTP share nahi; resume demo ke liye repeat testing nahi |
| Agent browser fails | Control runtime issue | Source/CLI/test work continue; browser success invent nahi |

Provider GET ko at most two transport attempts milte hain; each default connect/read timeout 5/20 seconds hai. Isse under-5ms response promise nahi milta. POST/PUT/PATCH/DELETE transport retries disabled hain. Initial pre-write payment lookup typed hai; later financial ambiguity held rehti hai.

Private logs mein full credentials/payloads share mat karo. Useful diagnostic record: exception category, operation stage, relevant Test references, time, claim state aur sanitized reason. Supervisor status ka full raw JSON control token contain kar sakta hai; share karte waqt allowlisted summary use karo.

## 14 Stack ka project focused syllabus

Yeh syllabus tumhe RecoverAI independently samajhne, debug karne aur interview mein defend karne ke level tak le jane ke liye hai. Har library ka poora internet syllabus zaroori nahi. **Core** topics pehle; advanced topics future scale/pilot ke liye. Exercise actual configured merchant DB ke bajaye memory/temp fixture ya `var/learning` output mein karo.

Har module mein sequence rakho: concept ko Hinglish mein explain karo -> relevant source padho -> exercise banao -> existing test dekho -> bina agent ke result explain karo. Sirf code dekhkar familiar lagna aur khud solve kar pana alag levels hain.

### Module 01 Python fundamentals aur clean functions

**Project mein kyun:** Saara backend, training, workers aur tests Python mein hain.

**Aana chahiye:** variables/types, strings, list/dict/set/tuple, loops, comprehensions, functions and return values, positional/keyword arguments, default arguments, scope, imports/modules/packages, exceptions and try/except/finally, custom exceptions, context managers, file reading/writing, pathlib, JSON/CSV, type hints, enums, classes/basic OOP, virtualenv/pip and module execution (`python -m ...`). Mutable default argument ka risk samjho.

**Project map:** `policy.py`, `diagnosis.py`, `money.py`, config and models. Python decorators FastAPI routes mein use ho rahe hain. `with SessionLocal()` resource lifecycle handle karta hai.

**Exercise:** Function likho jo finite probability, positive amount aur nonnegative cost validate karke expected value return kare. Unknown action par clear exception do. Dict se already-tried actions exclude karo. JSON fixture file read karke decisions print karo; network call nahi.

**Checkpoint:** Function return aur print ka difference, dict/set lookup, exception propagate kyun hoti hai, finally cleanup kyun chahiye, aur `python script.py` versus `python -m package.module` explain kar sako.

### Module 02 Money datetime aur numerical correctness

**Project mein kyun:** Paise off-by-one aur timezone/window mistakes financial behavior change kar sakti hain.

**Aana chahiye:** binary float limitation, `Decimal(str(value))`, integer paise, finite/NaN/infinity checks, rounding versus rejecting fractional paise, UTC timestamps, aware versus naive datetime, elapsed time, boundary `>=` versus `>`, serialization and clock-controlled tests.

**Exercise:** Rs.19.90 -> 1990, Rs.0.29 -> 29, and invalid 0, negative, NaN, infinity, 0.001 inputs reject karo. 14-day deadline ki exact boundary test karo. Actual DB update nahi.

**Checkpoint:** Money expectation integer kyun hai? Data model ka existing Float column limitation kya hai? System clock patch kiye bina deterministic deadline test kaise karoge? Current code mein deprecated naive UTC calls maintenance debt hain; timezone changes ko schema/API expectations ke saath review karna hoga.

### Module 03 HTTP REST JSON aur webhooks

**Project mein kyun:** Dashboard/API requests aur provider push events dono HTTP use karte hain.

**Aana chahiye:** client/server, request/response, method/path/query/body/header, JSON types, Content-Type, status codes 200/400/401/403/409/413/422/500/503, GET versus POST, authentication headers, timeout, retry/backoff, localhost/ports, HTTPS/TLS, polling versus webhook, duplicate delivery, event ordering, idempotency and CORS/same-origin basics.

**Exercise:** Paper par checkout-config GET aur process-payment POST ke request fields/status responses likho. Ek signed webhook ka flow draw karo. Network failure ko wrong-password 401 se distinguish karo.

**Checkpoint:** 200 kya prove karta hai? Checkout completed text provider verification ka replacement kyun nahi? GET read retry relatively safe, POST creation retry uncertain kyun? Webhook delivery ko exactly-once assume kyun nahi karte?

### Module 04 FastAPI Uvicorn aur Pydantic

**Project mein kyun:** Private API and gateway routes, typed schemas and auth dependencies.

**Aana chahiye:** FastAPI app/router, path operation decorators, request models, Field bounds, finite floats/Decimal, regex-constrained IDs, `extra=forbid`, dependency injection with Depends, HTTPException, exception handlers, middleware, response classes, OpenAPI/docs, environment settings and server process. Uvicorn ASGI server hai; FastAPI framework hai.

**Sync/async depth:** async syntax blocking SDK ko automatically nonblocking nahi banati. Current async webhook processor ke synchronous provider/DB work ko production scale par profile karna hoga. Thread offload ya durable job queue possible future options hain; implementation assume mat karna.

**Exercise:** Isolated mini API banao jo `amount` aur action validate kare aur pure score function call kare. Invalid action, extra fields, bad amount aur missing auth ke tests banao. Provider SDK connect nahi karna.

**Project map:** `app/main.py`, `app/api/webhooks.py`, `app/api/auth.py`, `app/config.py`. Route list section 10 aur source mein dekho.

**Checkpoint:** 422 versus 500, dependency versus middleware, request validation versus business eligibility, sync I/O versus async scheduling explain karo. API schema valid hone ka matlab recovery financially eligible hona nahi.

### Module 05 SQL aur SQLite

**Project mein kyun:** Payment/workflow state durable relational tables mein hai.

**Aana chahiye:** tables/rows, primary/foreign keys, unique constraints, nullable fields, SELECT/WHERE/ORDER BY/LIMIT, INSERT/UPDATE, JOIN/LEFT JOIN, GROUP BY/COUNT/SUM, indexes, transactions, commit/rollback, referential integrity, isolation and concurrent write contention. SQLite multiple readers but one simultaneous writer allow karta hai; deployment design is constraint ko consider kare.

**Exercise:** In-memory SQLite mein payments and outcomes tables banao; failed cases query karo, recovered count/amount group karo. Same provider resource unique ID twice insert karke constraint failure dekho. Original success ko recovery sum se exclude karo.

**Checkpoint:** Payment-attempt count aur original-order count alag kyun? Primary key event ID duplicate processing ko kaise help karti hai? Application-side existence check without database constraint kyun weak hai?

### Module 06 SQLAlchemy ORM aur transactional state

**Project mein kyun:** Domain models and database work Python objects/sessions ke through hota hai.

**Aana chahiye:** Engine, Session, sessionmaker, declarative Base, mapped columns, relationships, one-to-many, unique FK bindings, query filters, joins, get, flush, commit, rollback, refresh, expire_all, conditional UPDATE, rowcount and IntegrityError handling. Flush SQL send kar sakta hai; commit durability/transaction completion hai. Ek Session ko blindly multiple threads mein share mat karo.

**Exercise:** Two independent sessions se same reservation claim acquire karne ka fixture banao. Ek winner, ek blocked hona chahiye. Provider creation ko Mock rakho. Failed database write ke baad duplicate resource create nahi hona chahiye.

**Project map:** models, session, reservations, execution_records, original_orders; `tests/test_reservations.py`, `tests/test_duplicate_execution.py`.

**Checkpoint:** `db.flush()` versus `db.commit()`, stale ORM instance ko refresh kyun, local thread lock versus database ownership, and transactional audit+state consistency samjha sako.

### Module 07 Razorpay integration aur requests transport

**Project mein kyun:** External Test orders/links aur fresh verified status source.

**Aana chahiye:** order versus payment versus link, INR paise, created/attempted/paid order state, failed/authorized/captured payment state, full capture, amount_paid/amount_due, provider IDs, SDK methods, public key versus secret, Test versus Live, webhook configuration, HMAC verification, minimal storage, method availability, connect/read timeouts and lost response ambiguity.

**Exercise:** Fake provider fixture se created, paid, partial, wrong currency, wrong ID, authorized aur expired responses feed karo. Real keys ki zaroorat nahi. GET ConnectionError first attempt par aur success second par simulate karo; POST error mein call_count one assert karo.

**Project map:** razorpay_client, order_service, ingestion, operator_checkout, payment_methods; provider_mode, order_service and alternate_checkout tests.

**Checkpoint:** Full link amount and amount_paid dono kyun check karte hain? Alternate link hide karna plus captured method verification dono kyun? Already shared order/link ko local DB lock atomically recall kyun nahi kar sakta?

### Module 08 Workflow design concurrency aur failure handling

**Project mein kyun:** Hard part sirf probability prediction nahi, safe multi-step external workflow hai.

**Aana chahiye:** state machines, allowed transitions, idempotency keys, durable intent, event inbox, exclusive ownership, race conditions, late/early/out-of-order events, at-least-once delivery, bounded backoff, unresolved/poison events, crash windows, natural success, operator stop and explicit reconciliation. Local DB plus external API ko single transaction treat mat karo.

**Exercise:** Paanch timelines draw karo: duplicate failure; provider created but response lost; capture before DB execution row; old failed retry later succeeds; original and recovery both succeed. Har step par DB state, provider state aur permitted next action label karo.

**Project map:** execution, reservations, webhook_inbox, webhook_replay, original_orders, reconciliation. Tests mein ThreadPoolExecutor/Barrier/Event coordination ka use samjho.

**Checkpoint:** Sleeping for one second race proof nahi. State `processing` old hone se ownership reset safe kyun nahi? Intent external exactly-once guarantee kyun nahi? Verified resumption sirf never-attempted first retry tak limited kyun hai?

### Module 09 pandas NumPy aur reproducible synthetic data

**Project mein kyun:** Dataset generation, feature frames, analysis and benchmark artifacts.

**Aana chahiye:** DataFrame selection, masks, assign/copy, groupby/aggregation, merge basics, missing values, dtypes, CSV I/O, NumPy arrays/vectorization, random seeds, distributions, repeated grouped contexts, label generation and data provenance. Seed reproducibility deta hai, realism ki guarantee nahi.

**Exercise:** Synthetic CSV ko read karo; 6,000 rows, 2,000 unique contexts, each context exactly three action rows assert karo. Cause/action distribution aur label rate group karo. No merchant DB writes.

**Checkpoint:** Row versus independent context difference explain karo. Same cause ke zyada records ya different label recipe se model/action distribution kaise change hoga? Synthetic label ko real observation kyun nahi bol sakte?

### Module 10 Machine learning aur scikit learn

**Project mein kyun:** Supported context/action ke liye binary recovery probability estimate.

**Aana chahiye:** supervised learning, X/y, binary classification, positive label, train/validation/test roles, grouped split, leakage, overfitting, regularization, logistic sigmoid, feature scaling, one-hot encoding, interactions, ColumnTransformer, Pipeline, fit/transform/predict_proba, hyperparameter selection and fixed seeds. Model three-action classifier nahi; action type input feature hai aur target binary recovered label hai.

**Selection depth:** C inverse regularization strength hai. Candidate comparison inner validation par log loss then Brier use karti hai. Outer test selection ke liye reuse nahi hota. Selected estimator ko outer training contexts par refit kiya jata hai.

**Evaluation depth:** confusion matrix, precision/recall/F1, class imbalance, ROC-AUC versus PR/AP, prior baseline, Brier and log loss, calibration bins/sample sizes, threshold versus score ranking, uncertainty, per-cause/per-action slices and distribution shift. Accuracy/AUC ko recovery rate mat bolo.

**Exercise:** Existing train function isolated output path par run karo. Same grouped split ka zero-overlap assert dekho. Threshold 0.5 se badalne par precision/recall ka behavior samjho, lekin held-out results dekhkar app policy tune karke independent validation claim mat karna.

**Checkpoint:** 0.759 AUC aur 76.17% accuracy ka difference, low recall limitation, supported_ranges guard, `cause_action` interaction, aur unknown category manual assessment explain karo. Training 2,000 rows bolne ki jagah contexts/rows/train partition accurately distinguish karo.

### Module 11 Business evaluation statistics aur policy thinking

**Project mein kyun:** Classifier score useful ho sakta hai, lekin best business action/causal benefit automatically prove nahi hota.

**Aana chahiye:** expected value, intervention/operator costs, score floors, near ties, baseline fairness, shared eligible population, matched outcomes, holdouts, paired differences, bootstrap intuition, confidence interval, effect size, sample size, selection bias, missing counterfactuals, human deferral and uncertainty. Sensitive decision context mein probabilities ko guaranteed outcome mat treat karo.

**Exercise:** Same five teaching contexts par blanket retry, fixed cause rules and ML score compare karo. Sabko same costs/outcome labels do. Unchosen real action ko failure label mat do. Synthetic example ko illustrative label do. Reports mein zero-crossing interval interpret karo.

**Checkpoint:** Model AUC baseline se better ho phir bhi ML policy rules ko net value mein clearly beat kyun nahi kar rahi? Review-deferred cases ko automatic successes ginna kyun misleading hai? 2% guard statistical confidence kyun nahi?

### Module 12 Streamlit operator dashboard

**Project mein kyun:** Case visibility, explicit human decisions aur evidence UI.

**Aana chahiye:** script reruns, widgets and keys, session_state, forms/buttons, tabs/expanders, dataframes/metrics/charts, cache_data versus cache_resource, auth guard before queries, stale preview invalidation, empty/error states, source filters and AppTest. UI state persistent business state ka replacement nahi.

**Current tabs:** Live Razorpay Cases, Action Distribution, Case Simulation, Human Review, Recovery Review, Guardrails, Policy Benchmark, Decision Explanation.

**Exercise:** Temporary fixture mein login gate, manual override and exact audit history test karo. Two approvals on same case ka resource mix-up reproduce karke regression assertion padho. Real UI ko payment clicks se repeatedly prove karna required nahi.

**Checkout detail:** Verified public configuration HTML frame mein jaati hai, operator password/provider secret nahi. JSON escaping aur preview expiry necessary hain. Custom components/JS source edit karne se pehle installed Streamlit docs/skill read karo; unnecessary CSS injection avoid karo.

**Checkpoint:** User session state aur DB case state alag kyun? Tabs collapse hone par computation automatically stop hoti hai kya? Action Distribution attempt-level hai jab headline order-level hai, toh labels kyun necessary?

### Module 13 Testing with pytest mocks aur AppTest

**Project mein kyun:** Financial workflow ke failure paths happy-path se zyada important ho sakte hain.

**Aana chahiye:** arrange/act/assert, fixtures, tmp_path, parametrization, monkeypatch, Mock.side_effect, assert_not_called/call_count, API TestClient, in-memory versus file SQLite, concurrent separate sessions, deterministic clocks, cleanup, unit/integration/UI distinctions and regression tests. Test real behavior/property; implementation line ko mechanically mirror nahi.

**Exercise:** Ek transient read failing then replay success test, one POST failure never retried test, amount/currency mismatch settlement rejection, duplicate event single execution, operator stop during provider read, aur unauthorized UI no-query test samjho/recreate karo.

**Checkpoint:** What would this test catch? Could two workers accidentally share one Session? Why does mocking every important function make a workflow test weak? Pass count aur coverage percentage alag metrics hain. Production behavior ke liye separate load/operational/provider evidence chahiye.

### Module 14 Security configuration aur secrets

**Project mein kyun:** Operator financial actions aur public webhook boundary protect karni hai.

**Aana chahiye:** authentication versus authorization, salted password hashing versus encryption, PBKDF2, secret generation, constant-time compare, SHA256 artifact digest versus HMAC authenticity, HTTP Basic plus TLS, session expiry/credential rotation, secret loading, CSRF/same-origin/CORS basics, raw-body signature validation, input bounds, payload minimization, log redaction and least exposure.

**Current implementation:** Password PBKDF2-HMAC-SHA256 with random salt and 600,000 iterations generate hota hai; plaintext store nahi. API Basic auth aur dashboard session guard alag surfaces hain. Yeh single-operator model hai; full RBAC/multi-tenant identity system implemented nahi.

**Exercise:** Fake secret/body par signature generate/verify karo; one byte change par fail. Same password do baar hash karo, salts ki wajah se encoded outputs different honge. Invalid credentials par provider call zero assert karo.

**Checkpoint:** SecretStr accidental display reduce karta hai; field presence/representation ko complete secrecy guarantee mat samjho. Joblib/pickle artifact untrusted source se load nahi karna: deserialization code execute kar sakti hai. App hash match tampering mismatch detect karta hai, trusted publisher ko replace nahi karta.

### Module 15 Alembic migrations backup aur operations

**Project mein kyun:** Existing payment evidence lose kiye bina schema evolve karna.

**Aana chahiye:** schema version versus Python model, revision upgrade, frozen baseline, legacy adoption, foreign-key validation, transaction/DDL limits, migration ownership, consistent backup, restore testing, source/record digests, off-device backup, environment reproducibility, process liveness versus readiness versus job progress, restart budgets and PID reuse.

**Exercise:** Temporary fresh DB migrate karo; fixture data insert karke next revision path validate karo. Isolated backup restore compare karo; running configured DB par practice nahi. Supervisor tests mein unrelated process preserve hota hai, woh assertion padho.

**Checkpoint:** `create_all` existing production schema migration ka replacement kyun nahi? Backup file milna restore success kyun nahi? PID alone kill authorization kyun weak hai? Automatic restart stuck financial claim ko safe kyun nahi banata?

### Module 16 Git GitHub Actions aur dependency locks

**Project mein kyun:** Reproducible changes, owner history and automated verification.

**Aana chahiye:** repository/worktree, diff/status/log, staging, coherent commit, branches, merge/PR basics, revert versus destructive reset, remotes/push, .gitignore, tracked versus ignored files, lock hashes, Python version/platform markers, CI triggers/jobs/steps, JUnit reports and artifact retention. Owner author identity change nahi karni.

**Exercise:** Read-only `git diff`, `git status --short`, `git log --oneline` se current task ka exact change identify karo. `.env`, DB, logs, local backups stage na hon. Workflow ko explain karo: install hash lock -> pip check -> tests -> migration -> restore -> held-out evaluation -> matched benchmark -> isolated demo -> reports upload.

**Checkpoint:** Local tests green aur GitHub CI green alag facts kyun? Commit count engineering impact ka substitute kyun nahi? Lock security/update policy ka complete substitute kyun nahi? CI reports expire ho sakti hain, isliye long-term verified results repository docs mein scoped record hone chahiye.

### Ek executable learning example

Isko separate local Python scratch file mein run kar sakti ho. Yeh pure policy function hai; no provider call, no DB write:

```python
from app.services.policy import select_recovery_action

result = select_recovery_action(
    amount=499,
    predictions={"retry": 0.45, "payment_link": 0.60, "alt_method": 0.55},
    retry_eligible=True,
    retry_reason="Teaching fixture only",
    action_costs={"retry": 5, "payment_link": 15, "alt_method": 10},
    min_action_margin_ratio=0.02,
)
print(result)
assert result["chosen_action"] == "payment_link"
```

Phir probabilities itni close karo ki top-two difference Rs.9.98 ke andar aaye. Decision human_review hona chahiye. Ek tried action exclude karke result explain karo. Yeh artificial example recorded merchant evidence nahi.

## 15 Self study schedule

Suggested **30 study sessions**, har session roughly 60-90 minutes ka starting target. Agar fundamentals naye hain to ek session ko multiple days dena normal hai. Yeh fixed-time mastery promise nahi; module checkpoints pass karna calendar finish karne se important hai.

| Session | Kaam | Apne paas kya output hona chahiye |
| --- | --- | --- |
| 01 | Sections 01-04 padho | 60-second Hinglish project explanation |
| 02 | Python functions/dicts/sets | Pure score function |
| 03 | Exceptions, files, JSON | Fixture read and safe error output |
| 04 | Decimal and datetime | Money/window boundary tests |
| 05 | HTTP basics | GET/POST/webhook request diagram |
| 06 | SQL basics | In-memory cases and aggregate query |
| 07 | PK/FK/uniqueness | Duplicate insert rejected example |
| 08 | SQLAlchemy sessions | Flush/commit/rollback demonstration |
| 09 | Pydantic and mini API | Invalid inputs return 422 |
| 10 | API auth and config | Missing/wrong auth no provider call |
| 11 | Webhook signature | Modified raw body fails verification |
| 12 | Diagnosis and eligibility | Unknown cause manual-review explanation |
| 13 | Pure policy/scoring | Candidate exclusion and near-tie result |
| 14 | pandas data inspection | 6,000 rows / 2,000 contexts verified |
| 15 | Pipeline/grouped split | Zero-overlap assertion explained |
| 16 | Classifier metrics | AUC, recall, baseline meaning in own words |
| 17 | Policy benchmark | Why ML advantage unproven explanation |
| 18 | Reservations/races | One-winner concurrent claim fixture |
| 19 | Durable intent | Lost-response timeline |
| 20 | Early/late capture | Correct execution attribution diagram |
| 21 | Reconciliation/stops | Allowed versus blocked transition table |
| 22 | pytest regression reading | Explain five meaningful failure tests |
| 23 | Streamlit and AppTest | UI state versus DB state explanation |
| 24 | Supervisor/readiness | Safe local process map and port table |
| 25 | Alembic | Fresh temporary DB migration result |
| 26 | Backup restore | Isolated restore proof explanation |
| 27 | Git/CI/locks | Explain full workflow and artifact scopes |
| 28 | Offline demonstration | Six scenarios without provider clicks |
| 29 | Mock interview | Answer sections 16 questions aloud |
| 30 | Independent lab | Implement and test a tiny fixture-only change without following an agent line by line |

### Learning ka daily method

Pehle 10 minutes previous concept bina notes explain karo. Next 25-40 minutes code and one concept read karo. Phir small exercise khud likho. Last 10-15 minutes test/result aur "yeh kyun" note karo. Kisi agent se seedha full solution lene ke bajaye hints, counterexamples aur code review maango. Jab concept explain na ho, usko mark karo; memorized buzzwords add mat karo.

### Self assessment

| Level | Tum kya kar sakti ho |
| --- | --- |
| 1 Recognition | File/term dekhkar familiar lagta hai |
| 2 Explanation | Bina notes simple language mein explain kar sakti ho |
| 3 Application | Isolated example/test khud bana sakti ho |
| 4 Debugging | Failure reproduce, root cause isolate and safe change propose kar sakti ho |
| 5 Design | Tradeoffs, limits and validation plan defend kar sakti ho |

Interview ke core modules mein at least levels 2-3 aim karo; all advanced topics ka level 5 abhi compulsory nahi.

## 16 Interview preparation

### 60 second answer

"Maine RecoverAI banaya, jo failed-payment recovery aur reconciliation handle karta hai. Razorpay ke signed Test Mode webhooks se failure ingest hota hai. Rule-based diagnosis aur eligibility checks ke baad supported contexts mein logistic model recovery probabilities estimate karta hai. Cost-adjusted policy action select karti hai, aur uncertain cases operator review mein jate hain. Har issued order/link exact execution aur amount/currency se bound hota hai. Sirf verified capture par original case recovered hota hai. Duplicate events, lost responses, late captures aur original checkout success ke safeguards hain. Current suite mein 645 tests hain. Training synthetic hai; actual verification Test Mode mein hui hai, real merchant uplift claim nahi."

### Five minute walkthrough ka order

1. **Problem:** link create karna aur verified recovery same nahi; duplicates/uncertainty important hain.
2. **Architecture:** gateway, private API, SQLite, dashboard and three workers.
3. **Decision:** explicit guards, supported causes, probabilities and value ranking.
4. **Execution:** intent before POST, exact resource binding, no blind write retry.
5. **Evidence:** actual alternate-method Test capture, six offline scenarios and test suite.
6. **Limits:** synthetic model, no proven merchant uplift, unverified fresh retry acceptance and pending deployment gates.

Live checkout demo required nahi. Recorded offline replay aur verified historical record use karo. Button se record replay ho raha hai toh usko live provider request mat describe karo.

### Common questions with answer direction

**Q1 What exactly did you build?**  
ML-assisted payment-recovery workflow plus verification and operator controls. FastAPI/SQLAlchemy/Streamlit application; LLM planner nahi.

**Q2 Why this problem?**  
Failed fee payments ke follow-up mein duplicate requests, uncertain payment status aur operational visibility ki need ho sakti hai. Proposed merchant segment defined hai; demand validation abhi future pilot mein hogi.

**Q3 Why logistic regression?**  
Structured features, probability output, reproducible pipeline and a straightforward baseline-friendly model. Four predefined candidates inner validation par compare hue; selected regularized logistic model lowest validation loss se chosen hua. Bigger model automatically better business policy nahi.

**Q4 How is an action selected?**  
First hard eligibility, supported context and already-tried exclusions. Then p*amount-cost. Near ties/high values/unknown contexts need review. Actual action costs assumptions hain.

**Q5 Do unknown failures get a probability?**  
Unsupported causes/ranges manual assessment mein jate hain. Generic payment_failed ko fabricated bank/network cause assign nahi karte.

**Q6 What is the hardest engineering issue?**  
External side effect aur local persistence ke beech atomic transaction nahi. Provider create accept kare aur response lose ho jaye to duplicate POST avoid karna hard hai. Durable intent, resource notes, claims and reviewed reconciliation use hue.

**Q7 Is it exactly once?**  
Database ownership/uniqueness many duplicates prevent karti hai, lekin external collection exactly once guarantee nahi. Shared old checkouts and separate orders for one merchant invoice remaining risks hain.

**Q8 What if original payment succeeds later?**  
Fresh original evidence recovery stop karti hai, paid_original record hota hai, successful recovery outcome invent nahi hota. Original plus recovery paid ho to duplicate investigation, automatic refund nahi.

**Q9 Why are GET and POST retried differently?**  
A transient provider read can be attempted once more. Creation POST ka lost response unknown accepted side effect ho sakta hai; transport automatic retry nahi karta.

**Q10 How do early and late webhooks work?**  
Early event durable inbox mein match ka wait karta hai. Late capture exact older execution ko settle kar sakti hai. Event ID aur resource/intent correlation separate layers hain.

**Q11 How is human approval recorded?**  
Recommendation and executed Action alag rows. Actual override, provider execution and its exact audit binding stored hain. Budget executed actions se calculate hota hai.

**Q12 What is your dataset?**  
2,000 synthetic grouped contexts, three action rows each. Train 1,600 contexts/4,800 rows; held-out 400/1,200; zero overlap. Inner selection training groups ke andar hui.

**Q13 What does 0.759 AUC mean?**  
Synthetic test label ranking quality, recovery percentage nahi. Recall at threshold 0.5 around 22.9% hai; accuracy alone model strength ka complete proof nahi.

**Q14 Does ML beat simple rules?**  
Matched benchmark mein clear advantage establish nahi hua. Primary net difference minus Rs.735.83 ka interval zero cross karta hai. Yeh limitation honestly report ki gayi.

**Q15 Is model confidence the 2% setting?**  
Nahi. It is a predeclared business margin between top net-value estimates, expressed as share of payment amount. Statistical confidence interval se alag hai.

**Q16 What does the test suite cover?**  
API security, money, eligibility, concurrency, exact attribution, early/late events, ambiguous creation, stops, reconciliation, UI, migrations, restore and supervision. 645 tests includes parameterized cases, not 645 live transactions.

**Q17 Why SQLite?**  
Local single-operator scope ko simple reproducible relational persistence milti hai. Concurrent write contention aur scaling limits hain. PostgreSQL/queue future choices hain, implemented deployment claim nahi.

**Q18 Is the async API fully nonblocking?**  
Async route ka hona enough nahi; current synchronous SDK/DB work ko real load par profile/offload/queue decision chahiye. Latency/load SLA measured nahi.

**Q19 What would you do next for a business?**  
Merchant need and approved outcomes validate karungi; invoice mapping, consent/refund/dispute handling, reviewed deployment, monitoring and controlled pilot. Cosmetic retraining pehle nahi.

**Q20 How would you measure business impact?**  
Unique fee/order unit, verified net value after measured costs, operator effort, opt-outs and duplicate/partial outcomes. Merchant normal process ke against pre-agreed comparable holdout/randomization where practical; sample size and uncertainty report karungi.

**Q21 Why not say real revenue recovered?**  
Existing three captures Razorpay Test Mode simulated payments hain. Real merchant settlement/ROI observation available nahi.

**Q22 What did you personally learn and own?**  
Apna actual role explain karo: requirements/tradeoffs, assisted implementation ka review, testing, provider walkthrough, debugging and understanding. Tools use kiye hain to accurately describe karo. Har line khud se likhne ka fabricated claim nahi; code path aur tests explain karke ownership demonstrate karo.

### Live coding ke liye practice tasks

- Pure expected-value selector with eligibility and already-tried exclusion.
- Decimal money conversion with validation.
- SQL query counting unique orders rather than attempts.
- Mock provider timeout and no-second-POST assertion.
- Fresh-capture amount/currency mismatch reject karne wala function.
- Same event twice process karke one execution assert karne wala fixture.

In tasks ko scratch fixtures mein solve karo. Actual payment DB par interview practice nahi.

## 17 Resume content

**RecoverAI - ML-Assisted Payment Recovery and Reconciliation**  
**Aug 2026 - Nov 2026 | Solo Project**

- Built a FastAPI recovery workflow for Razorpay Test Mode payments, combining signed webhooks, cost-adjusted action selection and human review in Streamlit.
- Implemented original-order duplicate guards, durable recovery intents and execution-level reconciliation; validated with 645 automated tests and GitHub Actions.
- Evaluated logistic regression on 400 held-out synthetic contexts: ROC-AUC 0.759 vs. a 0.500 constant-prior baseline, with zero train/test context overlap.

**Technologies:** Python, FastAPI, SQLAlchemy, SQLite, scikit-learn, Streamlit, Razorpay API Test Mode, pytest, GitHub Actions.

Dates mein actual start timeline owner verify kare; improvements November tak hui hain. Row 1-3 concise resume bullets hain; PDF formatting mein actual rendered line lengths check karna. AUC/synthetic/Test Mode labels retain karo. No production users, real merchant revenue, guaranteed recovery, LLM autonomy, measured speed or proven ML uplift claims. Rs.1,497 Test amount ko business impact headline banana useful nahi.

## 18 Future agent ko dene wala prompt

Neeche block copy-paste karo aur is handbook ko attach karo. Agar specific change chahiye to last line par woh task add karo.

```text
RecoverAI project continue karna hai. Attached Hinglish handover ko pehle padho.

Repository: https://github.com/Sneha-090/RecoverAI
Owner's active Windows checkout: D:\RecoverAI
Old C:\...\OneDrive\Documents\ChatGPT\recoverAI clone ko active source assume mat karo.
If the machine/path differs, identify the actual repo and remote before any write.

Follow applicable system/tool permissions and repository AGENTS.md. Start with a
read-only git status, diff, log and relevant code/report inspection. Preserve owner
changes. Unrelated tests/test_webhook_gateway.py status and untracked python file
were present at the handover; inspect current state rather than assuming clean.

The application is Razorpay Test Mode only, with synthetic ML evaluation.
On 22 Nov 2026 the existing suite passed 645 tests. Last recorded provider Test
recovery totals were three recovered groups / INR 1,497. These are not live revenue.
A further fresh retry capture remains unverified; its unused case was operator-
stopped. Do not restart repetitive manual checkout testing as a resume requirement.

Scope is frozen for resume/demo/interview. First help me understand and present
what exists. Implement new features only if I explicitly request that next phase.
Use isolated tests and scripts.offline_demo by default; keep learning output under
ignored D-drive var/learning or .venv paths. No merchant DB reset or synthetic seeding.

Never request/expose plaintext passwords, password hashes, API secrets, ngrok
credentials or raw personal payloads. .env and local DB/backups are not in Git.
Keep operator API/dashboard private and public tunnel upstream limited to gateway
8002. Do not change non-Test provider mode or initiate real-money collection.
Do not delete/expire/force processing claims, force held events, repeat uncertain
POSTs, or treat created links/orders as recovery. Use reviewed service paths only.

Owner authorizes completed coherent tested commits and pushes per AGENTS.md.
Do not change author identity, rewrite history, stage unrelated files or split
arbitrary lines merely for commit count. Report actual checks and commit links.

Check current facts before asserting them. Preserve distinctions among actual Test
captures, fake-provider simulation, local test passes and head-specific CI. Model
AUC is not a recovery rate; matched synthetic results did not establish ML uplift.
Don't assume old services, tunnel, credentials, provider resources or browser tools
are currently available. Browser failures should not cause repeated user payment
steps; use the recorded evidence and explain any real blocker honestly.

My requested task now: [write your specific question or change here]
```

### Agent ke first independent checks

1. Correct repo/remote and branch identify; AGENTS.md read.
2. Working-tree changes classify, preserve owner work.
3. Relevant source plus existing tests read, current reports validate.
4. Learning/read-only request ho to services/payments/migrations unnecessarily start nahi.
5. Code change ho to meaningful targeted tests; suite broaden only when justified.
6. Provider/DB writes se pehle current authorization and financial state verify.
7. Final response: kya change hua, kyun, actual validation, limits and links.

Is file mein enough context hai ki previous chat transcript mandatory na ho. Secrets ya personal account access is context ka part nahi.

## 19 Files aur knowledge ko preserve kaise karein

### Public source versus private runtime

| Item | Git mein normally included | Handover meaning |
| --- | --- | --- |
| Source, tests, migrations and locks | Yes | Fresh clone se milte hain |
| Model artifact and synthetic CSV | Yes | Trusted repo/version se use karo |
| Recorded reports and docs | Yes | Metrics and source fingerprints available |
| `.env` | No | Private Test config separately recreate/securely transfer |
| `recoverai.db` | No | Local case/audit history public clone mein nahi aati |
| `var/backups`, `var/restore_checks` | No | Protected local backups/drills separately preserve |
| `.venv` | No | New machine par locked setup rebuild karo |
| Logs/runtime control files | No | Machine-specific private artifacts; blindly reuse nahi |
| Ngrok authtoken/config | Outside source | Private account configuration; publish mat karo |

### Minimum personal handover checklist

- [ ] Is single handbook ki D-drive copy aur accessible repository copy rakho.
- [ ] Repo remote par intended final commit pushed hai, verify karo.
- [ ] Private .env/password manager/Test account access ka secure record owner ke paas ho.
- [ ] Agar local case history preserve karni hai to consistent verified backup privately rakho.
- [ ] Backup ki protected off-device copy plan karo; same-drive backup drive failure cover nahi karti.
- [ ] Model plus evaluation report matched pair aur dependency locks preserve ho.
- [ ] Sirf source chahiye to tracked-file archive useful hai; secrets/DB usmein normally nahi honge.
- [ ] Unused services/tunnel ki necessity review karo; active processes ko ownership verify kiye bina kill nahi.
- [ ] Screenshots/recordings share karne se pehle customer/contact/auth data redact karo.

Optional source archive, **handbook commit ke baad**, from project CMD:

```bat
git archive --format=zip --output=D:\RecoverAI_Source_Backup_2026-11-22.zip HEAD
```

Yeh tracked HEAD files archive karta hai; `.git` history, ignored .env, DB, backups aur venv include nahi. Archive ka content verify karo. Yeh private DB backup ya full machine backup nahi. Is guide ke authoring task ne archive/private files copy nahi kiye.

### Existing operations ko blind resume mat karna

New machine par fresh empty DB aur old DB ka restored copy different situations hain. Restoring `.env` without correct DB/model mapping ya two copies simultaneously run karna unexpected workflow state create kar sakta hai. Runtime status/owner tokens/process IDs old machine-specific hain. Public source aur secret configuration ko alag maintain karo.

## 20 Glossary aur official resources

### Common terms in simple Hinglish

| Term | Meaning |
| --- | --- |
| API | Defined interface jisse program request/response exchange karta hai |
| Endpoint | HTTP method plus path ka operation |
| Webhook | Provider ka event push request |
| Signature | Secret-based authenticity check; plain JSON identity proof nahi |
| HMAC | Shared-secret keyed message authentication |
| SHA256 digest | Artifact content fingerprint, sender authentication by itself nahi |
| Salt | Password hash ke saath random per-hash input |
| PBKDF2 | Password hashing/key derivation with deliberate repeated work |
| Authentication | Kaun operator hai verify karna |
| Authorization | Verified actor ko kaunsa action allowed hai |
| Idempotency | Same logical request repeat se extra intended side effect na ho |
| Durable | Process end hone par state persistence mein retained rahe |
| Reservation or claim | Exclusive operation ownership record |
| Intent | External request se pehle saved durable plan/reference |
| Execution | Actually issued provider resource/action ka binding |
| Outcome | Existing execution ka observed result |
| Reconciliation | Fresh provider evidence se uncertain local state resolve karna |
| Natural success | Customer original checkout pay kare, recovery resource nahi |
| Attribution | Result ko correct executed action/resource se link karna |
| Race condition | Concurrent timing se result change ho jana |
| Backoff | Repeated eligible retries ke beech increasing delay |
| Transaction | Related DB changes ka controlled commit/rollback unit |
| Migration | Stored schema ka versioned change |
| FK | Reference integrity enforce karne wala foreign key |
| Baseline | Fair reference method jisse measured comparison hota hai |
| Leakage | Evaluation information indirectly training mein aa jana |
| Group split | Related rows ko same train/test partition mein rakhna |
| Calibration | Predicted probabilities ka observed frequencies se agreement |
| ROC-AUC | Positive/negative label ranking quality across thresholds |
| Brier score | Probability ka squared error metric |
| Counterfactual | Same context par unchosen action ka unknown alternate outcome |
| CI | Commit-triggered automated validation |
| Readiness | App required dependencies/schema/artifacts ke saath ready hai kya |
| Liveness | Process responding/alive hai kya |
| Job heartbeat | Worker useful progress kar raha hai kya |
| Test Mode | Simulated provider transactions; merchant revenue nahi |
| Source fingerprint | Code/data hash that ties evidence to exact inputs |

### Official learning resources

Links 22 Nov 2026 ko primary documentation pages ke against checked hain. Docs site ka latest patch local pinned environment se newer ho sakta hai. Concepts samjho; API examples ko installed version/source se match karo. Yeh poora syllabus read karne ke links hain, paid course requirement nahi.

1. **Python 3.13 tutorial:** functions, data structures, modules, errors and classes. [Python 3.13 tutorial](https://docs.python.org/3.13/tutorial/)
2. **FastAPI tutorial:** request models, dependencies, middleware, testing. [FastAPI tutorial](https://fastapi.tiangolo.com/tutorial/)
3. **Pydantic models:** validation, fields and model configuration. [Pydantic model concepts](https://pydantic.dev/docs/validation/latest/concepts/models/)
4. **SQLAlchemy 2.1 ORM quick start:** models, sessions and queries. [SQLAlchemy 2.1 ORM quick start](https://docs.sqlalchemy.org/en/21/orm/quickstart.html)
5. **SQLite transactions:** concurrent read/write and commit/rollback semantics. [SQLite transactions](https://sqlite.org/lang_transaction.html)
6. **Alembic tutorial:** revision and migration environment. [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
7. **scikit-learn metrics:** classifier/probability evaluation concepts. [scikit-learn model evaluation](https://scikit-learn.org/stable/modules/model_evaluation.html)
8. **Streamlit concepts:** execution/reruns, state, auth and testing. [Streamlit development concepts](https://docs.streamlit.io/develop/concepts)
9. **pytest documentation:** fixtures, parametrize, monkeypatch, temporary directories. [pytest documentation](https://docs.pytest.org/en/stable/)
10. **Requests quick start:** HTTP request/response usage and timeout concepts. [Requests quick start](https://requests.readthedocs.io/en/latest/user/quickstart/)
11. **Razorpay webhook validation:** raw body signature and event-delivery behavior. [Razorpay webhook validation](https://razorpay.com/docs/webhooks/validate-test)
12. **Pro Git:** commits, staging, branches and remotes. [Pro Git book](https://git-scm.com/book/en/v2)
13. **GitHub Actions:** jobs, workflows and artifacts. [GitHub Actions documentation](https://docs.github.com/en/actions)

### Project evidence sources

This handbook ka application-specific content repository source and records se verified hai. Original files further detail ke liye available hain; key conclusions is single guide mein included hain.

- Source baseline: https://github.com/Sneha-090/RecoverAI/tree/d744a8748d8efda4bbf483b0310eccd88d72f3f0
- General setup and boundaries: https://github.com/Sneha-090/RecoverAI/blob/main/README.md
- Architecture: https://github.com/Sneha-090/RecoverAI/blob/main/ARCHITECTURE.md
- Actual Test evidence: https://github.com/Sneha-090/RecoverAI/blob/main/TEST_MODE_VERIFICATION.md
- Operations: https://github.com/Sneha-090/RecoverAI/blob/main/OPERATIONS.md
- Model report: https://github.com/Sneha-090/RecoverAI/blob/main/ML/evaluation.json
- Matched benchmark: https://github.com/Sneha-090/RecoverAI/blob/main/reports/POLICY_BENCHMARK.md
- Offline scenarios: https://github.com/Sneha-090/RecoverAI/blob/main/reports/OFFLINE_DEMO.md
- Merchant pilot gates: https://github.com/Sneha-090/RecoverAI/blob/main/PILOT_PLAN.md
- Migration contract: https://github.com/Sneha-090/RecoverAI/blob/main/migrations/README.md

### Apne liye final completion checklist

- [ ] Main project 60 seconds aur five minutes mein explain kar sakti hoon.
- [ ] Main original order, payment attempt aur recovery execution ka difference samajhti hoon.
- [ ] Main rules, ML probability aur business policy ko mix nahi karti.
- [ ] Main p*amount-cost aur near-tie setting calculate/explain kar sakti hoon.
- [ ] Main 2,000 contexts, 6,000 rows aur held-out split accurately bata sakti hoon.
- [ ] Main synthetic AUC ko merchant recovery rate nahi bolti.
- [ ] Main duplicate/concurrent/lost-response safeguards aur remaining external races samajhti hoon.
- [ ] Main zero real-payment clicks ke saath offline demo dikha sakti hoon.
- [ ] Main safe D-drive setup, tests, status, migrations and backup verification ke right commands identify kar sakti hoon.
- [ ] Main unfinished fresh retry capture aur future merchant gates openly explain kar sakti hoon.
- [ ] Main source/secrets/private DB ka handover difference samajhti hoon.
- [ ] Main small fixture exercise bina agent ke khud solve aur test kar sakti hoon.

**Aaj ka practical next step:** Session 01 se shuru karo. Is guide ko file ke roop mein preserve karo. Core implementation ko baar-baar modify karne ke bajaye understanding, recorded demo aur interview answers par kaam karo. Future business phase owner-approved need/evidence ke saath hi resume karo.
