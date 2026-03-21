#!/usr/bin/env bash
set -euo pipefail

sudo apt install -y stress
stress --cpu 4 --timeout 120s
