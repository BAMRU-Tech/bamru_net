#!/bin/bash

# Any parameters will be passed through to `uv pip compile`

set -e

uv pip compile $@ requirements/base.in -o requirements/base.txt
uv pip compile $@ requirements/opentelemetry.in -o requirements/opentelemetry.txt
uv pip compile $@ requirements/test.in -o requirements/test.txt
uv pip compile $@ requirements/dev.in -o requirements/dev.txt
