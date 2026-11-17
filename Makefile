PY := .venv/bin/python
OUT ?= out
STORES ?=

.PHONY: history-frozen rules dashboards dashboards-check setup-elastic collector-up collector-down collector-logs install lookups backfill-local replay replay-fast demo rehearse restore agent agent-check clean-run reset plan-aws setup-aws verify-infra teardown-aws test clean

install:
	python3 -m venv .venv
	$(PY) -m pip install -q -r requirements.txt

# Generate the knowledge-base lookup files from config/chain.yaml.
lookups:
	$(PY) -m coldchain.lookup

# Generate the synthetic history into a local directory using the bucket layout.
# Example: make backfill-local STORES=S03,S07 DETECT_DAYS=2
backfill-local:
	$(PY) -m coldchain.backfill --target local --out $(OUT) \
		$(if $(STORES),--stores $(STORES)) \
		$(if $(DETECT_DAYS),--detect-days $(DETECT_DAYS)) \
		$(if $(RAW_DAYS),--raw-days $(RAW_DAYS)) \
		$(if $(FLOW_DAYS),--flow-days $(FLOW_DAYS))

# Scenario A at stage speed (1x). T0 = start + 3 min; restore is automatic at T0+10 min.
# Use RESTORE=trigger so the mock response service restores via `python -m coldchain.replay trigger`.
replay:
	$(PY) -m coldchain.replay run --t0 now --speed 1 --restore $(or $(RESTORE),auto) --target $(or $(TARGET),local)

replay-fast:
	$(PY) -m coldchain.replay run --t0 now --speed 10 --restore $(or $(RESTORE),auto) --target $(or $(TARGET),local)

# Live run on the real clock: the attack happens about 3 minutes after you start, so a dashboard on "Last 24 hours" shows it
# unfold (a faster speed would stamp the data ahead of the wall clock, where the picker hides it). Uploads to S3, loads .env.
# Enables both detection rules first (rule 1 alerts within about a minute of the data arriving, rule 2 and the "warm, no
# defrost" tile come alive about 10 minutes after the attack), clears the overlapping baseline, then waits for `make restore`
# (Act 7). Without it the setpoints are restored by themselves 30 minutes after the attack.
demo:
	set -a; . ./.env; set +a; $(PY) -m coldchain.rules push --enable && $(PY) -m coldchain.prep && $(PY) -m coldchain.replay run --t0 now --speed 1 --restore trigger --restore-timeout 30 --target s3

# Hands-off version for rehearsal: same, but the setpoints are restored automatically about 9 minutes after the attack
# (so rule 2 and the "warm" panels never get their 3 minutes; use `make demo` to see those).
rehearse:
	set -a; . ./.env; set +a; $(PY) -m coldchain.rules push --enable && $(PY) -m coldchain.prep &&$(PY) -m coldchain.replay run --t0 now --speed 1 --restore auto --target s3

# The "go" for the restore (Act 7); the mock response service will call this. Run in a second terminal.
restore:
	$(PY) -m coldchain.replay trigger

# Clears local replay state only. Cluster and bucket data are not touched (object lock, see CLAUDE.md 4.2).
reset:
	$(PY) -m coldchain.replay reset

# AWS side only (bucket, SQS, IAM). The Elastic Cloud steps come later.
# Set AWS_PROFILE (or TF_VAR_profile) first. `make plan-aws` changes nothing.
plan-aws:
	terraform -chdir=infra init -input=false
	terraform -chdir=infra plan -input=false

setup-aws:
	terraform -chdir=infra init -input=false
	terraform -chdir=infra apply
	$(PY) -m coldchain.infra write-env

verify-infra:
	$(PY) -m coldchain.infra check

# Deletes every object version in the bucket (governance bypass), then destroys the stack.
teardown-aws:
	$(PY) -m coldchain.infra empty-bucket --yes
	terraform -chdir=infra destroy
	rm -f store-keys.json
	rm -rf .secrets

# Elastic Cloud side of the detection path: templates, pipeline, lookup indices, Fleet policy.
setup-elastic: lookups
	$(PY) -m coldchain.elastic setup
	$(PY) -m coldchain.elastic check
	$(PY) -m coldchain.fleet setup

collector-up:
	docker compose -f compose/collector/docker-compose.yml up -d

collector-down:
	docker compose -f compose/collector/docker-compose.yml down

collector-logs:
	docker compose -f compose/collector/docker-compose.yml logs -f --tail 50

test:
	$(PY) -m pytest -q

clean:
	rm -rf $(OUT) .pytest_cache

# Kibana dashboards for the acts (Dashboards API, 9.5+). `make dashboards-check` runs every panel query first.
dashboards:
	$(PY) -m coldchain.dashboards push

dashboards-check:
	$(PY) -m coldchain.dashboards check $(if $(RANGE),--range $(RANGE))

# Act 2 detection rules (ES|QL, created disabled). Enable for a show: make rules ENABLE=1
rules:
	$(PY) -m coldchain.rules push $(if $(ENABLE),--enable)

# Act 5b: index the raw audit history, snapshot it and mount it on the frozen tier (needs a frozen node and AWS credentials).
history-frozen:
	set -a; . ./.env; set +a; $(PY) -m coldchain.frozen load && $(PY) -m coldchain.frozen check

# The agentic SOC (Agent Builder, preview): create the tools and the agent, test the tool queries, ask the scripted question.
agent:
	$(PY) -m coldchain.agent push

agent-check:
	$(PY) -m coldchain.agent check

agent-ask:
	$(PY) -m coldchain.agent ask $(Q)

# After a live run: delete the indexed replay documents and the run's alerts, and switch the rules off again. Example: make clean-run SINCE=2026-11-11T12:15:00Z
# (The S3 objects stay: object lock; the operator removes them with the governance bypass.)
clean-run:
	set -a; . ./.env; set +a; $(PY) -m coldchain.prep clean $(SINCE) && $(PY) -m coldchain.rules push

# The scheduled hunt (AlertZero pattern): the SOC agent sweeps the estate every 30 minutes through an Elastic Workflow and records
# findings in cc-hunt-findings. `make hunt` creates or updates it; `make hunt-run` runs it now and waits (about 2 to 4 minutes).
.PHONY: hunt hunt-run
hunt:
	set -a; . ./.env; set +a; $(PY) -m coldchain.hunt push && $(PY) -m coldchain.dashboards push --only coldchain-hunt-findings

hunt-run:
	set -a; . ./.env; set +a; $(PY) -m coldchain.hunt run && $(PY) -m coldchain.hunt findings

# ======================================================================================================================
# Runbook targets: see README.md for the order, the prerequisites and what each step needs.
# ======================================================================================================================
.PHONY: help setup backfill backfill-epilogue federation federation-check epilogue baselines sources correlation content verify teardown teardown-elastic \
        clean-raw hunt-clear reset-demo

help:
	@echo "First time, in order (README.md has the details):"
	@echo "  make install                 python venv and dependencies"
	@echo "  make setup                   AWS (Terraform), Elastic side, collector, federation data source"
	@echo "  make backfill                12 months raw + 35 days indexed history to S3 (long, restartable)"
	@echo "  make backfill-epilogue       scenario B (the TV box) to S3"
	@echo "  make baselines epilogue      knowledge base baselines, epilogue ML and rule"
	@echo "  make history-frozen          Act 3b (needs a frozen node on the deployment)"
	@echo "  make sources content         the source catalog (Act 0), then dashboards, rules, agent, hunt"
	@echo "  make verify                  infrastructure, pipeline, federation, dashboards, agent checks"
	@echo "A demo:        make demo (live, 1x) | make rehearse (hands-off) | make restore (in a second terminal)"
	@echo "Between runs:  make reset-demo SINCE=<replay start, printed by the run> [DELETE=1]"
	@echo "Tear down:     make teardown   (the Elastic Cloud deployment itself is yours to delete)"

# AWS (Terraform), then the Elastic side, then the collector, then the federation data source. Needs .env filled in (README step 3).
setup: setup-aws verify-infra setup-elastic collector-up federation

# The history: raw/ (12 months of audit, 7 days of flows) and detect/ (35 days indexed). Tens of thousands of PUTs; safe to re-run.
backfill:
	set -a; . ./.env; set +a; $(PY) -m coldchain.backfill --target s3 --resume

backfill-epilogue:
	# No --resume on purpose: scenario B reuses the object keys of the main backfill for the same store and hour (netflow.summary,
	# and S07's netflow.log), and --resume would skip them, leaving the epilogue streams about a third short.
	set -a; . ./.env; set +a; $(PY) -m coldchain.scenario_b --target s3

# The data source and datasets only: a check needs files under raw/, so it is `make federation-check` after the backfill.
federation:
	$(PY) -m coldchain.federation setup

federation-check:
	$(PY) -m coldchain.federation check

# After the detect/ history is indexed (the collector drains the queue): what is normal for the Act 2 tiles.
baselines:
	$(PY) -m coldchain.baselines

# Act 0 and the "one question, three places" panel: measures every source (the raw files are counted in place, about 5 minutes)
# and the same question against the live index, the frozen tier and the raw files. Run after history-frozen and both backfills.
sources:
	$(PY) -m coldchain.sources

# The cross-source correlation example of Act 0 (live index + raw files + knowledge base in one statement, about 75 s). Re-run it
# after the attack to see today's visits next to the history. `make sources` includes it.
correlation:
	$(PY) -m coldchain.sources correlation

# Scenario B: ML jobs and datafeeds over the epilogue window, and the new-terms rule (created disabled).
epilogue:
	$(PY) -m coldchain.epilogue setup
	$(PY) -m coldchain.epilogue start
	$(PY) -m coldchain.epilogue rule

# Everything shown in Kibana: dashboards, detection rules (disabled; the demo enables them), the agent, the scheduled hunt.
content: dashboards rules agent hunt

verify: verify-infra
	$(PY) -m coldchain.elastic check
	$(PY) -m coldchain.federation check
	$(PY) -m coldchain.dashboards check
	$(PY) -m coldchain.agent check

# Raw files of a run, dry run unless DELETE=1. Example: make clean-raw SINCE=2026-11-16T08:50:00Z DELETE=1
clean-raw:
	@test -n "$(SINCE)" || (echo "usage: make clean-raw SINCE=<UTC time> [DELETE=1]"; exit 1)
	set -a; . ./.env; set +a; $(PY) -m coldchain.infra clean-raw --since $(SINCE) $(if $(DELETE),--delete)

hunt-clear:
	set -a; . ./.env; set +a; $(PY) -m coldchain.hunt clear

# Everything a run leaves behind: indexed data, alerts, hunt findings, and (listed, deleted with DELETE=1) the raw files.
# SINCE is the replay's start (T0 minus 3 minutes; the run prints it): after the pre-roll, so the day of context stays.
# With DELETE=1 the frozen copy of the history is rebuilt afterwards and the Act 0 correlation is measured again (history only).
reset-demo:
	@test -n "$(SINCE)" || (echo "usage: make reset-demo SINCE=<replay start, printed by the run> [DELETE=1]"; exit 1)
	$(MAKE) clean-run SINCE=$(SINCE)
	$(MAKE) hunt-clear
	$(MAKE) clean-raw SINCE=$(SINCE) $(if $(DELETE),DELETE=1)
	$(if $(DELETE),$(MAKE) history-frozen)
	$(if $(DELETE),$(MAKE) correlation)

# Removes what the repo created: the hunt, the frozen copy, the collector and the AWS stack (bucket versions included).
# The Elastic Cloud deployment is not touched: delete it in the Elastic Cloud console.
teardown: teardown-elastic teardown-aws

teardown-elastic:
	-set -a; . ./.env; set +a; $(PY) -m coldchain.hunt delete
	-set -a; . ./.env; set +a; $(PY) -m coldchain.frozen delete
	-docker compose -f compose/collector/docker-compose.yml down
