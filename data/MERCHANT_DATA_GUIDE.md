# Real-data validation plan

Current training and policy results are synthetic. Two Test Mode recoveries are
integration evidence, not a merchant training dataset or a performance estimate.

Collect an approved, anonymised export with stable merchant-local customer and
case IDs, event/decision/outcome timestamps, amount/currency, payment method,
provider reason, eligibility, every proposed action, the action actually executed,
its selection probability if randomised, and verified final outcome/cost. Exclude
card data, passwords, API keys, names, phone numbers and email addresses.

Only observed executed actions have observed outcomes. Do not label unchosen
actions as failures or invent all three potential outcomes for real customers.
The existing matched synthetic benchmark requires three counterfactual labels per
context and cannot directly assess an observational merchant export. That needs
an appropriately designed experiment or separately justified off-policy analysis.

Group repeat customers within a split and use forward-time validation for the
merchant workflow. Reserve a fresh blind test period; fit transformations and
select candidates/thresholds on earlier training/validation only. Report action,
cause, method and amount coverage, calibration, case counts and uncertainty,
including missing/unsupported reasons and deferred operator decisions.

Compare against fixed business rules using the same eligible population, costs,
observation window and intervention budget. A merchant-approved controlled pilot
and verified outcomes are needed before claiming recovery improvement or ROI.
