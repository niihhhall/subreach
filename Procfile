web: uvicorn reddit_outreach.web:app --host 0.0.0.0 --port ${PORT:-8000}
watch: python -m reddit_outreach.cli watch ${CAMPAIGN:-campaigns/markeye.yaml} --interval 1800 --draft-budget 10
scout: python -m reddit_outreach.cli scout ${CAMPAIGN:-campaigns/markeye.yaml} --loop --interval 86400 --per-vertical 8
warm: python -m reddit_outreach.cli warm ${CAMPAIGN:-campaigns/markeye.yaml} --confirm --loop --interval 3600
