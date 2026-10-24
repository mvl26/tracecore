#!/usr/bin/env bash
set -eu
cd ~/tracecore-dev
set -a
. ~/.tracecore-e2e.env
set +a
bench --site tracecore-dev.local execute runpy.run_path --args '["/mnt/d/tracecore/.superpowers/sdd/task-7-api-diagnose.py"]'
