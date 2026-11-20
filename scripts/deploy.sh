#!/bin/sh
# Release: push main with tags (the GitHub release carries the built artifacts).
# Antagor runs commands without a shell, so && lives here.
set -e
git push origin main --follow-tags
