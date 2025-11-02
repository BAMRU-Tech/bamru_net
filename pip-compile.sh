#!/bin/bash

# Any parameters will be passed through to `uv pip compile`

set -e

uv pip compile --generate-hashes $@ requirements/base.in -o requirements/base.txt
uv pip compile --generate-hashes $@ requirements/opentelemetry.in -o requirements/opentelemetry.txt
uv pip compile --generate-hashes $@ requirements/test.in -o requirements/test.txt
uv pip compile --generate-hashes $@ requirements/dev.in -o requirements/dev.txt
